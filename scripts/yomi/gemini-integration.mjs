/**
 * Gemini API integration for Yomi summarization
 * Provides Gemini-based summarization as an alternative to Llama Router
 */

import { GoogleGenerativeAI } from '@google/generative-ai';

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemma-4-31b-it';

// Initialize Gemini client
let genAI = null;
let model = null;

// Simple rate limiter for Gemini API (Gemma 4 models: higher limits on free tier)
let requestTimes = [];
const RATE_LIMIT = 15; // requests per minute (conservative default)
const RATE_WINDOW = 60000; // 1 minute in ms

async function waitForRateLimit() {
  const now = Date.now();
  // Remove requests older than the rate window
  requestTimes = requestTimes.filter(time => now - time < RATE_WINDOW);
  
  if (requestTimes.length >= RATE_LIMIT) {
    const oldestRequest = requestTimes[0];
    const waitTime = RATE_WINDOW - (now - oldestRequest);
    if (waitTime > 0) {
      console.log(`Rate limit reached, waiting ${waitTime}ms...`);
      await new Promise(resolve => setTimeout(resolve, waitTime));
    }
  }
  
  requestTimes.push(now);
}

function initializeGemini() {
  if (!genAI) {
    genAI = new GoogleGenerativeAI(GEMINI_API_KEY);
    model = genAI.getGenerativeModel({ model: GEMINI_MODEL });
  }
  return model;
}

/**
 * Generate summary using Gemini API
 * @param {string} prompt - The prompt to send to Gemini
 * @param {Object} options - Generation options
 * @returns {Promise<string>} - Generated summary text
 */
export async function geminiSummary(prompt, options = {}) {
  const {
    temperature = 0.3,
    maxTokens = 300,
    systemPrompt = 'You extract structured information from chat conversations and return valid JSON.'
  } = options;

  try {
    await waitForRateLimit();
    initializeGemini();
    
    const fullPrompt = `${systemPrompt}\n\n${prompt}`;
    
    const result = await model.generateContent(fullPrompt);
    const response = await result.response;
    const text = response.text();
    
    console.log(`Gemini summary generated (${text.length} chars)`);
    return text;
  } catch (error) {
    console.error('Gemini API error:', error.message);
    throw new Error(`Gemini API failed: ${error.message}`);
  }
}

/**
 * Generate conversation summary using Gemini
 * @param {string} chatId - Chat ID
 * @param {string} prompt - Formatted prompt with conversation text
 * @returns {Promise<string>} - Generated summary
 */
export async function geminiConversationSummary(chatId, prompt) {
  return geminiSummary(prompt, {
    temperature: 0.3,
    maxTokens: 50,
    systemPrompt: 'You summarize LINE conversations concisely in one sentence (under 20 words). Focus on the main topic, question, or decision.'
  });
}

/**
 * Generate daily summary using Gemini
 * @param {string} chatId - Chat ID
 * @param {string} date - Date string
 * @param {string} prompt - Formatted prompt with daily messages
 * @param {string} language - Detected language ('thai', 'english', 'mixed')
 * @returns {Promise<string>} - Generated daily summary JSON
 */
export async function geminiDailySummary(chatId, date, prompt, language = 'english') {
  const systemPrompt = (language === 'thai' || language === 'mixed')
    ? 'คุณแยกข้อมูลที่มีโครงสร้างจากข้อความ LINE และคืนค่า JSON ที่ถูกต้องที่มี events, actions, และ topics arrays เป็นภาษาไทย'
    : 'You extract structured information from LINE messages and return valid JSON with events, actions, and topics arrays.';
  
  return geminiSummary(prompt, {
    temperature: 0.3,
    maxTokens: 300,
    systemPrompt
  });
}

/**
 * Generate batch daily summary using Gemini
 * @param {string} chatId - Chat ID
 * @param {Array} dates - Array of date strings
 * @param {string} prompt - Formatted prompt with multiple dates
 * @param {string} language - Detected language ('thai', 'english', 'mixed')
 * @returns {Promise<string>} - Generated batch daily summary JSON
 */
export async function geminiBatchDailySummary(chatId, dates, prompt, language = 'english') {
  const systemPrompt = (language === 'thai' || language === 'mixed')
    ? 'คุณแยกข้อมูลที่มีโครงสร้างจากข้อความ LINE หลายวันและคืนค่า JSON ที่ถูกต้องที่มี date keys และ events, actions, และ topics arrays เป็นภาษาไทย'
    : 'You extract structured information from LINE messages across multiple dates and return valid JSON with date keys containing events, actions, and topics arrays.';
  
  return geminiSummary(prompt, {
    temperature: 0.3,
    maxTokens: 600,
    systemPrompt
  });
}

/**
 * Test Gemini API connectivity
 * @returns {Promise<boolean>} - True if API is working
 */
export async function testGeminiConnection() {
  try {
    await waitForRateLimit();
    initializeGemini();
    console.log(`Testing with model: ${GEMINI_MODEL}`);
    console.log(`API Key: ${GEMINI_API_KEY.substring(0, 10)}...`);
    
    const result = await model.generateContent('Test connection. Respond with "OK".');
    const response = await result.response;
    const text = response.text();
    console.log('Gemini connection test successful:', text);
    return true;
  } catch (error) {
    console.error('Gemini connection test failed:', error.message);
    console.error('Full error:', error);
    return false;
  }
}
