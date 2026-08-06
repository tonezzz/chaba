/**
 * Language detection utilities for Yomi processing
 * Handles detection of Thai, English, and mixed language content
 */

/**
 * Detect language of text content
 * @param {string} text - Text content to analyze
 * @returns {string} - Language: 'thai', 'english', 'mixed', or 'unknown'
 */
export function detectLanguage(text) {
  // Thai character ranges: U+0E00-U+0E7F
  const thaiChars = text.match(/[\u0E00-\u0E7F]/g);
  const totalChars = text.replace(/\s/g, '').length;
  
  if (totalChars === 0) return 'unknown';
  
  const thaiRatio = thaiChars ? thaiChars.length / totalChars : 0;
  
  // Adjusted thresholds for better mixed detection
  // Thai dominant: > 60% Thai characters
  // Mixed: 5-60% Thai characters
  // English: < 5% Thai characters
  if (thaiRatio > 0.6) return 'thai';
  if (thaiRatio > 0.05) return 'mixed';
  return 'english';
}

/**
 * Detect language of a conversation from multiple messages
 * @param {Array} messages - Array of message objects
 * @returns {string} - Language: 'thai', 'english', 'mixed', or 'unknown'
 */
export function detectConversationLanguage(messages) {
  const textContent = messages
    .map(m => {
      const text = m.text || '';
      // Filter out null strings and actual "null" text values
      if (text === 'null' || text === 'undefined' || !text.trim()) return '';
      return text;
    })
    .filter(Boolean)
    .join(' ');
  
  if (!textContent) return 'english';
  
  return detectLanguage(textContent);
}

/**
 * Get language-specific prompt for main conversation summarization
 * @param {string} language - Detected language
 * @param {string} name - Conversation name
 * @param {Array} lines - Message lines
 * @returns {string} - Language-specific prompt
 */
export function getLanguageSpecificPrompt(language, name, lines) {
  const baseContent = lines.join('\n');
  
  switch (language) {
    case 'thai':
      return `สรุปการสนทนา LINE กับ ${name} เป็นประโยคเดียวสั้นๆ (ไม่เกิน 20 คำ) เน้นหัวข้อหลัก คำถาม หรือการตัดสินใจ\n\n${baseContent}\n\nสรุป:`;
    
    case 'mixed':
      return `Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Use the same language as the messages (Thai/English mix). Focus on the main topic, question, or decision.\n\n${baseContent}\n\nSummary:`;
    
    case 'english':
    default:
      return `Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Focus on the main topic, question, or decision.\n\n${baseContent}\n\nSummary:`;
  }
}

/**
 * Get language-specific prompt for daily summarization (single date)
 * @param {string} language - Detected language
 * @param {string} date - Date string
 * @param {string} name - Conversation name
 * @param {Array} lines - Message lines
 * @returns {string} - Language-specific daily prompt
 */
export function getLanguageSpecificDailyPrompt(language, date, name, lines) {
  const baseContent = lines.join('\n');
  
  switch (language) {
    case 'thai':
      return `สกัดข้อมูลจากข้อความ LINE วันที่ ${date} ในการสนทนากับ ${name}:
- เหตุการณ์ (สิ่งที่เกิดขึ้น)
- การกระทำ (สิ่งที่คนทำหรือวางแผนจะทำ)
- หัวข้อ (เรื่องหลักที่พูดคุย)

รูปแบบ JSON:
{
  "events": ["เหตุการณ์1", "เหตุการณ์2"],
  "actions": ["การกระทำ1", "การกระทำ2"],
  "topics": ["หัวข้อ1", "หัวข้อ2"]
}

ข้อความ:
${baseContent}`;

    case 'mixed':
      return `Extract from these LINE messages for ${date} in conversation with ${name}:
- Events (things that happened)
- Actions (things people did or plan to do)
- Topics (main subjects discussed)

Format as JSON:
{
  "events": ["event1", "event2"],
  "actions": ["action1", "action2"],
  "topics": ["topic1", "topic2"]
}

Messages:
${baseContent}`;

    case 'english':
    default:
      return `Extract from these LINE messages for ${date} in conversation with ${name}:
- Events (things that happened)
- Actions (things people did or plan to do)
- Topics (main subjects discussed)

Format as JSON:
{
  "events": ["event1", "event2"],
  "actions": ["action1", "action2"],
  "topics": ["topic1", "topic2"]
}

Messages:
${baseContent}`;
  }
}

/**
 * Get language-specific prompt for batch daily summarization
 * @param {string} language - Detected language
 * @param {string} name - Conversation name
 * @param {string} dates - Date string
 * @param {string} dateSections - Formatted date sections
 * @returns {string} - Language-specific batch daily prompt
 */
export function getLanguageSpecificBatchDailyPrompt(language, name, dates, dateSections) {
  const baseContent = dateSections.join('\n\n');
  
  switch (language) {
    case 'thai':
      return `สกัดข้อมูลจากข้อความ LINE หลายวัน (${dates}) ในการสนทนากับ ${name}:
- เหตุการณ์ (สิ่งที่เกิดขึ้น)
- การกระทำ (สิ่งที่คนทำหรือวางแผนจะทำ)
- หัวข้อ (เรื่องหลักที่พูดคุย)

รูปแบบ JSON (โดยวันที่):
{
  "YYYY-MM-DD": {
    "events": ["เหตุการณ์1", "เหตุการณ์2"],
    "actions": ["การกระทำ1", "การกระทำ2"],
    "topics": ["หัวข้อ1", "หัวข้อ2"]
  }
}

ข้อความ:
${baseContent}`;

    case 'mixed':
      return `Extract structured information from these LINE messages for conversation with ${name} across multiple dates (${dates}):
- Events (things that happened)
- Actions (things people did or plan to do)
- Topics (main subjects discussed)

Format as JSON (by date):
{
  "YYYY-MM-DD": {
    "events": ["event1", "event2"],
    "actions": ["action1", "action2"],
    "topics": ["topic1", "topic2"]
  }
}

Messages:
${baseContent}`;

    case 'english':
    default:
      return `Extract structured information from these LINE messages for conversation with ${name} across multiple dates (${dates}):
- Events (things that happened)
- Actions (things people did or plan to do)
- Topics (main subjects discussed)

Format as JSON (by date):
{
  "YYYY-MM-DD": {
    "events": ["event1", "event2"],
    "actions": ["action1", "action2"],
    "topics": ["topic1", "topic2"]
  }
}

Messages:
${baseContent}`;
  }
}
