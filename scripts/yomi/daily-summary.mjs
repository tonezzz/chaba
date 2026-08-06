/**
 * Daily summarization utilities for Yomi processing
 * Handles grouping messages by date and daily summary generation
 */

/**
 * Group messages by date for daily summarization
 * @param {Array} messages - Array of message objects
 * @returns {Map} - Map of date string to array of messages
 */
export function groupMessagesByDate(messages) {
  const byDate = new Map();
  for (const m of messages) {
    if (!m.deliveredTime) continue;
    try {
      // Convert string timestamp to number
      let timestamp = parseInt(m.deliveredTime, 10);
      if (isNaN(timestamp)) {
        console.warn(`Invalid deliveredTime (not a number): ${m.deliveredTime}, skipping`);
        continue;
      }
      
      // Handle both millisecond and microsecond timestamps
      if (timestamp > 2500000000000) {
        // If timestamp is in microseconds, convert to milliseconds
        timestamp = Math.floor(timestamp / 1000);
      }
      
      const date = new Date(timestamp).toISOString().split('T')[0];
      if (!byDate.has(date)) byDate.set(date, []);
      byDate.get(date).push(m);
    } catch (err) {
      console.warn(`Invalid deliveredTime for message: ${m.deliveredTime}, skipping`);
    }
  }
  return byDate;
}

/**
 * Filter dates to only include those within the last N days
 * @param {Map} byDate - Map of date to messages
 * @param {number} days - Number of days to include (default: 30)
 * @returns {Map} - Filtered map
 */
export function filterRecentDates(byDate, days = 30) {
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - days);
  const cutoffDateStr = cutoffDate.toISOString().split('T')[0];
  
  const filteredDates = new Map();
  for (const [date, msgs] of byDate) {
    if (date >= cutoffDateStr) {
      filteredDates.set(date, msgs);
    }
  }
  
  console.log(`Filtered to ${filteredDates.size} dates within last ${days} days (skipped ${byDate.size - filteredDates.size} older dates)`);
  return filteredDates;
}

/**
 * Save daily summary to database
 * @param {Object} pool - Database connection pool
 * @param {string} chatId - Chat ID
 * @param {string} date - Date string
 * @param {Array} events - Events array
 * @param {Array} actions - Actions array
 * @param {Array} topics - Topics array
 * @param {number} messageCount - Message count
 */
export async function saveDailySummary(pool, chatId, date, events, actions, topics, messageCount) {
  await pool.query(`
    INSERT INTO daily_summaries (chat_id, date, events, actions, topics, message_count)
    VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (chat_id, date) DO UPDATE SET
      events = EXCLUDED.events,
      actions = EXCLUDED.actions,
      topics = EXCLUDED.topics,
      message_count = EXCLUDED.message_count,
      updated_at = NOW()
  `, [chatId, date, events, actions, topics, messageCount]);
}

/**
 * Parse JSON response from LLM
 * @param {string} response - LLM response text
 * @returns {Object} - Parsed JSON object
 */
export function parseDailyResponse(response) {
  try {
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('No JSON found in response');
    }
    return JSON.parse(jsonMatch[0]);
  } catch (err) {
    console.error('Failed to parse daily summary JSON:', err.message);
    throw new Error('invalid json in response');
  }
}

/**
 * Parse batch JSON response from LLM
 * @param {string} response - LLM response text
 * @returns {Object} - Parsed JSON object with date keys
 */
export function parseBatchDailyResponse(response) {
  try {
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('No JSON found in response');
    }
    return JSON.parse(jsonMatch[0]);
  } catch (err) {
    console.error('Failed to parse batch daily summary JSON:', err.message);
    throw new Error('invalid json in response');
  }
}
