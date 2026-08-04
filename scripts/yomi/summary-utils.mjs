/**
 * Summary quality validation and retry utilities
 */

// Generic error patterns that indicate failed summarization
const ERROR_PATTERNS = [
  /conversation unavailable/i,
  /no summary possible/i,
  /no available conversation/i,
  /unable to provide/i,
  /service unavailable/i,
  /unanswerable/i,
  /concoc/i, // From the True5G example
  /error/i,
  /failed/i
];

/**
 * Detect corruption patterns in summary text
 */
function detectCorruptionPatterns(summary) {
  if (!summary || typeof summary !== 'string') return false;
  
  const text = summary.trim();
  
  // Check for repeated character patterns (e.g., "ดดดดดดวดดกอดกงววมวม")
  const repeatedCharPattern = /(.)\1{4,}/;
  if (repeatedCharPattern.test(text)) return true;
  
  // Check for repeated word patterns (e.g., "discussing discussing Savannah Guthrie'ranews about Savannah Guthron")
  const words = text.split(/\s+/);
  const wordCounts = {};
  for (const word of words) {
    if (word.length > 3) { // Only check meaningful words
      wordCounts[word] = (wordCounts[word] || 0) + 1;
      if (wordCounts[word] >= 3) return true;
    }
  }
  
  // Check for garbled text patterns (mixed random characters)
  const garbledPattern = /[^\w\s\u0E00-\u0E7F.,!?;:'"()-]/g;
  const garbledCount = (text.match(garbledPattern) || []).length;
  if (garbledCount > text.length * 0.3) return true;
  
  // Check for specific corruption patterns found in investigation
  if (text.includes('Guthron') || text.includes('Guthrie\'ranews')) return true;
  
  return false;
}

/**
 * Evaluate summary quality (0-100 score)
 */
export function evaluateSummaryQuality(summary) {
  if (!summary || typeof summary !== 'string') return 0;
  
  const text = summary.trim();
  if (text === '') return 0;
  
  // Check for corruption patterns first
  if (detectCorruptionPatterns(text)) return 0;
  
  // Check for generic error messages
  for (const pattern of ERROR_PATTERNS) {
    if (pattern.test(text)) return 0;
  }
  
  // Quality scoring based on length and content
  const length = text.length;
  if (length < 10) return 10; // Very short
  if (length < 20) return 30; // Short
  if (length < 50) return 60; // Medium
  if (length < 100) return 80; // Good
  return 100; // Excellent
}

/**
 * Check if summary is meaningful (quality > 0 and not generic error)
 */
export function isMeaningfulSummary(summary) {
  return evaluateSummaryQuality(summary) > 0;
}

/**
 * Retry with exponential backoff
 */
export async function retryWithBackoff(fn, options = {}) {
  const {
    maxRetries = 3,
    baseDelay = 1000, // 1 second
    maxDelay = 10000, // 10 seconds
    onRetry = null
  } = options;
  
  let lastError;
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      
      // Don't retry on certain errors
      if (isNonRetryableError(error)) {
        throw error;
      }
      
      // Don't retry after max attempts
      if (attempt === maxRetries) {
        throw error;
      }
      
      // Calculate delay with exponential backoff
      const delay = Math.min(baseDelay * Math.pow(2, attempt), maxDelay);
      
      if (onRetry) {
        onRetry(attempt + 1, delay, error);
      } else {
        console.log(`Retry attempt ${attempt + 1}/${maxRetries} after ${delay}ms (error: ${error.message})`);
      }
      
      await sleep(delay);
    }
  }
  
  throw lastError;
}

/**
 * Check if error is non-retryable
 */
function isNonRetryableError(error) {
  const message = error.message?.toLowerCase() || '';
  
  // Network errors are retryable
  if (message.includes('fetch failed') || message.includes('econnrefused')) {
    return false;
  }
  
  // Validation errors are not retryable
  if (message.includes('invalid') || message.includes('validation')) {
    return true;
  }
  
  // Timeout errors are retryable
  if (message.includes('timeout')) {
    return false;
  }
  
  return false;
}

/**
 * Sleep utility
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Cache key generator with versioning
 */
export function generateCacheKey(chatId, version = 1) {
  return `${chatId}:v${version}`;
}

/**
 * Parse cache key to extract chat ID and version
 */
export function parseCacheKey(key) {
  const match = key.match(/^(.+):v(\d+)$/);
  if (!match) return { chatId: key, version: 1 };
  return { chatId: match[1], version: parseInt(match[2], 10) };
}