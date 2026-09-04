/**
 * Media analysis worker for Yomi
 * Analyzes media files (images, videos) using multimodal Gemini
 * Runs as background job triggered by API
 */

import { GoogleGenerativeAI } from '@google/generative-ai';
import { readFileSync, existsSync } from 'fs';
import pool from './db.mjs';

// Language detection function (inline to avoid ES6 import issues)
function detectLanguage(text) {
  const thaiChars = text.match(/[\u0E00-\u0E7F]/g);
  const totalChars = text.replace(/\s/g, '').length;
  
  if (totalChars === 0) return 'unknown';
  
  const thaiRatio = thaiChars ? thaiChars.length / totalChars : 0;
  
  if (thaiRatio > 0.6) return 'thai';
  if (thaiRatio > 0.05) return 'mixed';
  return 'thai'; // Default to Thai for LINE conversations
}

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_VISION_MODEL_PRIMARY = process.env.GEMINI_VISION_MODEL_PRIMARY || 'gemma-4-31b-it';
const GEMINI_VISION_MODEL_FALLBACK = process.env.GEMINI_VISION_MODEL_FALLBACK || 'gemma-4-26b-a4b-it';
const MEDIA_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/yomi/media';
const JOB_ID = process.env.JOB_ID;
const CONTEXT_MESSAGES_BEFORE = parseInt(process.env.CONTEXT_MESSAGES_BEFORE || '3', 10);
const CONTEXT_MESSAGES_AFTER = parseInt(process.env.CONTEXT_MESSAGES_AFTER || '3', 10);

console.log('analyze-media.mjs environment check:', {
  GEMINI_API_KEY: GEMINI_API_KEY ? 'SET' : 'NOT SET',
  GEMINI_VISION_MODEL_PRIMARY,
  GEMINI_VISION_MODEL_FALLBACK,
  JOB_ID,
  CONTEXT_MESSAGES_BEFORE,
  CONTEXT_MESSAGES_AFTER,
  POSTGRES_USER: process.env.POSTGRES_USER,
  POSTGRES_DB: process.env.POSTGRES_DB
});

// Override db.mjs environment variables if not set
if (!process.env.POSTGRES_USER) {
  process.env.POSTGRES_USER = process.env.POSTGRES_USER || 'chaba';
  process.env.POSTGRES_PASSWORD = process.env.POSTGRES_PASSWORD || 'chabapass';
  process.env.POSTGRES_DB = process.env.POSTGRES_DB || 'chaba';
  process.env.POSTGRES_HOST = process.env.POSTGRES_HOST || '127.0.0.1';
  process.env.POSTGRES_PORT = process.env.POSTGRES_PORT || '5432';
}

if (!JOB_ID) {
  console.error('JOB_ID environment variable required');
  process.exit(1);
}

async function analyzeMedia() {
  const client = await pool.connect();
  
  try {
    // Load job
    const { rows: jobRows } = await client.query(
      'SELECT * FROM media_analysis_jobs WHERE id = $1',
      [parseInt(JOB_ID, 10)]
    );
    
    if (jobRows.length === 0) {
      throw new Error(`Job ${JOB_ID} not found`);
    }
    
    const job = jobRows[0];
    
    // Update status to running
    await client.query(
      `UPDATE media_analysis_jobs 
       SET status = 'running', started_at = NOW(), updated_at = NOW()
       WHERE id = $1`,
      [job.id]
    );
    
    console.log(`Starting media analysis job ${job.id} for message ${job.message_id}`);
    
    // Get the target message's timestamp first
    const { rows: targetMsgRows } = await client.query(
      'SELECT delivered_time, created_at FROM messages WHERE message_id = $1',
      [job.message_id]
    );
    
    if (targetMsgRows.length === 0) {
      throw new Error(`Target message ${job.message_id} not found`);
    }
    
    const targetTimestamp = targetMsgRows[0].delivered_time || targetMsgRows[0].created_at || 0;
    console.log(`Target message timestamp: ${targetTimestamp}`);
    
    // Fetch context messages around the media message (chronological)
    // Get messages before and after the target timestamp
    const { rows: contextRows } = await client.query(
      `SELECT message_id, from_name, text, delivered_time, created_at
       FROM messages 
       WHERE chat_id = $1 
         AND message_id != $2
         AND text IS NOT NULL 
         AND text != ''
       ORDER BY delivered_time DESC, created_at DESC
       LIMIT $3`,
      [job.chat_id, job.message_id, 6] // Get 6 messages total (3 before, 3 after)
    );
    
    // Build context string from surrounding messages
    let contextText = '';
    if (contextRows.length > 0) {
      // Sort chronologically
      const sortedContext = contextRows
        .sort((a, b) => (a.delivered_time || a.created_at || 0) - (b.delivered_time || b.created_at || 0));
      
      // Filter to get 3 before and 3 after the target message
      // Exclude messages posted at the exact same time as the target message
      const beforeMessages = sortedContext.filter(msg => 
        (msg.delivered_time || msg.created_at || 0) < targetTimestamp
      ).slice(-3); // Last 3 before target
      
      const afterMessages = sortedContext.filter(msg => 
        (msg.delivered_time || msg.created_at || 0) > targetTimestamp
      ).slice(0, 3); // First 3 after target
      
      const allContextMessages = [...beforeMessages, ...afterMessages];
      
      contextText = allContextMessages
        .map(msg => {
          const sender = msg.from_name || 'Unknown';
          const text = (msg.text || '').substring(0, 100); // Limit text length
          return `${sender}: ${text}`;
        })
        .join('\n');
      
      console.log(`Fetched ${contextRows.length} context messages, using ${allContextMessages.length} (before: ${beforeMessages.length}, after: ${afterMessages.length})`);
    }
    
    // Get message details
    const { rows: msgRows } = await client.query(
      'SELECT media_path, text FROM messages WHERE message_id = $1',
      [job.message_id]
    );
    
    if (msgRows.length === 0) {
      throw new Error(`Message ${job.message_id} not found`);
    }
    
    const message = msgRows[0];
    const mediaPath = message.media_path;
    
    if (!mediaPath) {
      throw new Error(`Message ${job.message_id} has no media path`);
    }
    
    // Detect language from context and message text
    const allText = contextText + ' ' + (message.text || '');
    const detectedLanguage = detectLanguage(allText);
    console.log(`Detected language: ${detectedLanguage}`);
    
    // Language-specific prompts
    const languagePrompts = {
      thai: 'วิเคราะห์สื่อนี้จากข้อความ LINE',
      english: 'Analyze this media file from a LINE message',
      mixed: 'วิเคราะห์สื่อนี้จากข้อความ LINE',
      unknown: 'วิเคราะห์สื่อนี้จากข้อความ LINE' // Default to Thai for unknown language
    };
    
    const languageInstructions = {
      thai: 'ตอบสั้นๆ (ไม่เกิน 20 คำ) ว่าสื่อแสดงอะไร พิจารณาบริบทเรื่องด้วย ใส่คำตอบสุดท้ายในย่อหน้าสุดท้าย และใส่การวิเคราะห์ทั้งหมดในย่อหน้าก่อนหน้า',
      english: 'Answer briefly (max 20 words) what the media shows, considering conversation context. Put your final clean answer in the last paragraph, and include all your analysis in the paragraphs before it',
      mixed: 'ตอบสั้นๆ (ไม่เกิน 20 คำ) ว่าสื่อแสดงอะไร พิจารณาบริบทเรื่องด้วย ใส่คำตอบสุดท้ายในย่อหน้าสุดท้าย และใส่การวิเคราะห์ทั้งหมดในย่อหน้าก่อนหน้า',
      unknown: 'ตอบสั้นๆ (ไม่เกิน 20 คำ) ว่าสื่อแสดงอะไร พิจารณาบริบทเรื่องด้วย ใส่คำตอบสุดท้ายในย่อหน้าสุดท้าย และใส่การวิเคราะห์ทั้งหมดในย่อหน้าก่อนหน้า' // Default to Thai for unknown language
    };
    
    // Load media file
    const fullMediaPath = `${MEDIA_DIR}/${job.chat_id}/${mediaPath}`;
    
    if (!existsSync(fullMediaPath)) {
      throw new Error(`Media file not found: ${fullMediaPath}`);
    }
    
    const mediaData = readFileSync(fullMediaPath);
    const base64Data = Buffer.from(mediaData).toString('base64');
    
    // Determine MIME type from file extension
    const ext = mediaPath.split('.').pop().toLowerCase();
    const mimeTypes = {
      'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
      'gif': 'image/gif', 'webp': 'image/webp', 'heic': 'image/heic',
      'heif': 'image/heif', 'mp4': 'video/mp4', 'webm': 'video/webm',
      'mov': 'video/quicktime', '3gp': 'video/3gpp'
    };
    const mimeType = mimeTypes[ext] || 'image/jpeg';
    
    // Initialize Gemini
    if (!GEMINI_API_KEY) {
      throw new Error('GEMINI_API_KEY environment variable not set');
    }
    
    const genAI = new GoogleGenerativeAI(GEMINI_API_KEY);
    
    // Try primary model first, fall back to secondary on rate limits
    let analysisResult = null;
    let modelUsed = GEMINI_VISION_MODEL_PRIMARY;
    let tokensUsed = null;
    
    for (const modelToTry of [GEMINI_VISION_MODEL_PRIMARY, GEMINI_VISION_MODEL_FALLBACK]) {
      try {
        console.log(`Attempting analysis with model: ${modelToTry}`);
        const model = genAI.getGenerativeModel({ model: modelToTry });
        
        // Prepare prompt with context and language
        const messageText = message.text || '';
        const textContext = messageText ? `The message also contains this text: "${messageText}"` : 'The message has no accompanying text.';
        
        let contextPrompt = '';
        if (contextText) {
          contextPrompt = `
        
Here are the surrounding messages for context:
${contextText}`;
        }
        
        const languageIntro = languagePrompts[detectedLanguage] || languagePrompts.english;
        const languageInstruction = languageInstructions[detectedLanguage] || languageInstructions.english;
        
        const prompt = `${languageIntro}. ${textContext}${contextPrompt}

${languageInstruction}`;
        
        // Prepare image data for Gemini
        const imagePart = {
          inlineData: {
            data: base64Data,
            mimeType: mimeType
          }
        };
        
        console.log(`Sending media to Gemini (${mediaData.length} bytes, ${mimeType})`);
        
        // Call Gemini API
        const result = await model.generateContent([prompt, imagePart]);
        const response = await result.response;
        analysisResult = response.text();
        modelUsed = modelToTry;
        
        // Extract token usage if available
        try {
          if (response.usageMetadata) {
            tokensUsed = response.usageMetadata.totalTokenCount;
          }
        } catch (e) {
          // Token usage not available in this API version
          tokensUsed = null;
        }
        
        console.log(`Analysis successful with model ${modelToTry}, tokens: ${tokensUsed}`);
        break; // Success, exit the retry loop
        
      } catch (error) {
        console.error(`Failed with model ${modelToTry}:`, error.message);
        
        // Check if this is a rate limit error and we have a fallback
        if (error.message.includes('429') || error.message.includes('quota') || error.message.includes('Too Many Requests')) {
          if (modelToTry === GEMINI_VISION_MODEL_PRIMARY) {
            console.log(`Rate limit hit on ${modelToTry}, trying fallback model ${GEMINI_VISION_MODEL_FALLBACK}`);
            continue; // Try the next model
          } else {
            // Fallback also hit rate limit
            throw new Error(`Rate limit exceeded on both models. Please try again later.`);
          }
        } else {
          // Non-rate-limit error, throw immediately
          throw error;
        }
      }
    }
    
    if (!analysisResult) {
      throw new Error('Failed to analyze media with both primary and fallback models');
    }
    
    console.log(`Gemini analysis result: ${analysisResult.substring(0, 100)}...`);
    
    // Update job with success
    await client.query(
      `UPDATE media_analysis_jobs 
       SET status = 'completed', 
           analysis_result = $1,
           model_used = $2,
           tokens_used = $3,
           completed_at = NOW(),
           updated_at = NOW()
       WHERE id = $4`,
      [analysisResult, modelUsed, tokensUsed, job.id]
    );
    
    // Update messages table with analysis result
    await client.query(
      `UPDATE messages 
       SET media_analysis = $1 
       WHERE message_id = $2`,
      [analysisResult, job.message_id]
    );
    
    console.log(`Media analysis job ${job.id} completed successfully`);
    
  } catch (error) {
    console.error(`Media analysis job ${JOB_ID} failed:`, error.message);
    
    // Update job with error
    await client.query(
      `UPDATE media_analysis_jobs 
       SET status = 'failed', 
           error_message = $1,
           completed_at = NOW(),
           updated_at = NOW()
       WHERE id = $2`,
      [error.message, JOB_ID]
    ).catch(err => {
      console.error('Failed to update job status:', err.message);
    });
    
    throw error;
  } finally {
    client.release();
    await pool.end();
  }
}

analyzeMedia()
  .then(() => {
    console.log('Media analysis worker completed');
    process.exit(0);
  })
  .catch(error => {
    console.error('Media analysis worker failed:', error);
    process.exit(1);
  });