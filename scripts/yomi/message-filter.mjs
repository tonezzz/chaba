/**
 * Message filtering utilities for Yomi processing
 * Handles filtering of encrypted metadata and other non-meaningful content
 */

/**
 * Filter out messages that only contain encrypted keyMaterial/fileName data
 * These are media metadata without actual conversation content
 * @param {string} text - Message text content
 * @returns {boolean} - true if message should be filtered out
 */
export function shouldFilterMessage(text) {
  if (!text) return true;
  
  // Filter out messages that only contain encrypted keyMaterial/fileName data
  // These are media metadata without actual conversation content
  if (text.startsWith('{') && text.includes('keyMaterial')) {
    return true;
  }
  
  return false;
}

/**
 * Filter messages to remove encrypted metadata
 * @param {Array} messages - Array of message objects
 * @returns {Array} - Filtered messages
 */
export function filterMessages(messages) {
  return messages.filter(m => !shouldFilterMessage(m.text));
}

/**
 * Extract meaningful text from a message, filtering out metadata
 * @param {Object} message - Message object
 * @param {Function} mediaLabelFn - Function to generate media labels
 * @returns {string|null} - Filtered text or null
 */
export function extractMessageText(message, mediaLabelFn) {
  const text = message.text || (message.mediaType ? mediaLabelFn(message) : null);
  if (!text) return null;
  
  if (shouldFilterMessage(text)) {
    return null;
  }
  
  return text;
}
