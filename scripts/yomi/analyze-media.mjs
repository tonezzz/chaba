/**
 * Media analysis worker for Yomi
 * Analyzes media files (images, videos) using multimodal Gemini
 * Runs as background job triggered by API
 */

import { GoogleGenerativeAI } from '@google/generative-ai';
import { readFileSync, existsSync } from 'fs';
import pool from './db.mjs';

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_VISION_MODEL = process.env.GEMINI_VISION_MODEL || 'gemini-2.0-flash';
const MEDIA_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/media';
const JOB_ID = process.env.JOB_ID;

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
    const model = genAI.getGenerativeModel({ model: GEMINI_VISION_MODEL });
    
    // Prepare prompt with context
    const textContext = message.text ? `The message also contains this text: "${message.text}"` : 'The message has no accompanying text.';
    const prompt = `Analyze this media file from a LINE message. ${textContext}

Provide a concise description (1-2 sentences) of what the media shows. Focus on:
- Main subject/content
- Any text visible in the image
- Context or setting if relevant
- Any notable details

Keep the description factual and brief. If the media is unclear or inappropriate, say so.`;
    
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
    const analysisText = response.text();
    
    // Extract token usage if available
    let tokensUsed = null;
    try {
      if (response.usageMetadata) {
        tokensUsed = response.usageMetadata.totalTokenCount;
      }
    } catch (e) {
      // Token usage not available in this API version
    }
    
    console.log(`Gemini analysis result: ${analysisText.substring(0, 100)}...`);
    
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
      [analysisText, GEMINI_VISION_MODEL, tokensUsed, job.id]
    );
    
    // Update messages table with analysis result
    await client.query(
      `UPDATE messages 
       SET media_analysis = $1 
       WHERE message_id = $2`,
      [analysisText, job.message_id]
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