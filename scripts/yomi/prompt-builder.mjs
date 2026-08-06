/**
 * Prompt building utilities for Yomi processing
 * Handles construction of prompts for LLM summarization
 */

import { extractMessageText } from './message-filter.mjs';
import { detectConversationLanguage, getLanguageSpecificPrompt, getLanguageSpecificDailyPrompt, getLanguageSpecificBatchDailyPrompt } from './language-detection.mjs';

/**
 * Generate media label for message
 * @param {Object} message - Message object
 * @returns {string} - Media label
 */
export function mediaLabel(message) {
  if (!message.mediaType) return '[unknown]';
  const t = String(message.mediaType).toLowerCase();
  if (t === 'image') return '[image]';
  if (t === 'video') return '[video]';
  if (t === 'audio') return '[audio]';
  if (t === 'file') return `[file: ${message.mediaFile || 'attachment'}]`;
  return `[${t}]`;
}

/**
 * Build prompt for main conversation summarization
 * @param {string} name - Conversation name
 * @param {Array} messages - Array of message objects
 * @param {Function} normalizeTimestampFn - Optional timestamp normalization function
 * @returns {string|null} - Prompt or null if insufficient content
 */
export function buildPrompt(name, messages, normalizeTimestampFn = null) {
  const sorted = [...messages].sort((a, b) => {
    const timeA = normalizeTimestampFn ? normalizeTimestampFn(a.deliveredTime) : (a.deliveredTime || 0);
    const timeB = normalizeTimestampFn ? normalizeTimestampFn(b.deliveredTime) : (b.deliveredTime || 0);
    return timeA - timeB;
  });
  
  const lines = sorted.slice(-40).map(m => {
    const from = m.fromName || m.from || 'Unknown';
    const text = extractMessageText(m, mediaLabel);
    if (!text) return null;
    return `${from}: ${String(text).replace(/\n/g, ' ')}`;
  }).filter(Boolean);
  
  if (lines.length === 0) {
    console.log(`No content available for summarization of ${name}`);
    return null;
  }
  
  if (lines.length < 2) {
    console.log(`Insufficient content for summarization: ${lines.length} items (need at least 2)`);
    return null;
  }
  
  const textOnlyLines = lines.filter(line => !line.includes('['));
  if (textOnlyLines.length === 0) {
    console.log(`No text content available for summarization, only media: ${name}`);
    return null;
  }
  
  // Detect language and use appropriate prompt
  const language = detectConversationLanguage(messages);
  console.log(`Detected language for summary ${name}: ${language}`);
  
  return getLanguageSpecificPrompt(language, name, lines);
}

/**
 * Build prompt for daily summarization (single date)
 * @param {string} date - Date string
 * @param {Array} messages - Array of message objects for the date
 * @param {string} name - Conversation name
 * @returns {string|null} - Prompt or null if insufficient content
 */
export function buildDailyPrompt(date, messages, name) {
  const lines = messages.map(m => {
    const from = m.fromName || m.from || 'Unknown';
    const text = extractMessageText(m, mediaLabel);
    if (!text) return null;
    return `${from}: ${String(text).replace(/\n/g, ' ')}`;
  }).filter(Boolean);
  
  if (lines.length === 0) return null;
  
  // Detect language and use appropriate prompt
  const language = detectConversationLanguage(messages);
  console.log(`Detected language for daily summary ${name} on ${date}: ${language}`);
  
  return getLanguageSpecificDailyPrompt(language, date, name, lines);
}

/**
 * Build prompt for batch daily summarization (multiple dates)
 * @param {Map} dateGroups - Map of date to messages
 * @param {string} name - Conversation name
 * @returns {string|null} - Prompt or null if insufficient content
 */
export function buildBatchDailyPrompt(dateGroups, name) {
  const dateSections = [];
  const allMessages = [];
  
  for (const [date, messages] of dateGroups) {
    const lines = messages.map(m => {
      const from = m.fromName || m.from || 'Unknown';
      const text = extractMessageText(m, mediaLabel);
      if (!text) return null;
      return `${from}: ${String(text).replace(/\n/g, ' ')}`;
    }).filter(Boolean);
    
    if (lines.length > 0) {
      dateSections.push(`=== ${date} ===\n${lines.join('\n')}`);
      allMessages.push(...messages);
    }
  }
  
  if (dateSections.length === 0) return null;
  
  const dates = Array.from(dateGroups.keys()).join(', ');
  
  // Detect language and use appropriate prompt
  const language = detectConversationLanguage(allMessages);
  console.log(`Detected language for batch daily summary ${name}: ${language}`);
  
  return getLanguageSpecificBatchDailyPrompt(language, name, dates, dateSections);
}
