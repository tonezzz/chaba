/**
 * Test script for Gemini summarization integration
 * Tests with sample conversation data
 */

import { readFileSync } from 'node:fs';
import { buildPrompt, buildDailyPrompt } from './prompt-builder.mjs';
import { groupMessagesByDate } from './daily-summary.mjs';
import { geminiConversationSummary, geminiDailySummary, testGeminiConnection as testGeminiAPIConnection } from './gemini-integration.mjs';
import { detectConversationLanguage } from './language-detection.mjs';

const TEST_CHAT_ID = 'u494a728e423a3d45182ad44bd1003cf6';
const FETCH_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/fetch-data';

async function loadTestData(chatId) {
  const filePath = `${FETCH_DIR}/${chatId}.json`;
  const data = readFileSync(filePath, 'utf-8');
  return JSON.parse(data);
}

async function testConnection() {
  console.log('Testing Gemini API connection...');
  
  try {
    const connected = await testGeminiAPIConnection();
    if (connected) {
      console.log('✓ Gemini API connection successful');
    } else {
      console.log('✗ Gemini API connection failed');
    }
    return connected;
  } catch (error) {
    console.error('✗ Gemini connection test error:', error.message);
    return false;
  }
}

async function testConversationSummary() {
  console.log('\n=== Testing Conversation Summary ===');
  
  try {
    const data = await loadTestData(TEST_CHAT_ID);
    const messages = data.messages;
    const name = 'KKGT @DAY';
    
    console.log(`Loaded ${messages.length} messages from conversation with ${name}`);
    
    // Detect language
    const language = detectConversationLanguage(messages);
    console.log(`Detected language: ${language}`);
    
    // Build prompt
    const prompt = buildPrompt(name, messages);
    if (!prompt) {
      console.log('✗ Failed to build prompt (insufficient content)');
      return false;
    }
    
    console.log(`Generated prompt (${prompt.length} chars)`);
    console.log('Prompt preview:', prompt.substring(0, 200) + '...');
    
    // Generate summary using Gemini
    console.log('Generating summary with Gemini...');
    const summary = await geminiConversationSummary(TEST_CHAT_ID, prompt);
    
    console.log('✓ Summary generated successfully');
    console.log('Summary:', summary);
    console.log(`Summary length: ${summary.length} chars`);
    
    return true;
  } catch (error) {
    console.error('✗ Conversation summary test failed:', error.message);
    return false;
  }
}

async function testDailySummary() {
  console.log('\n=== Testing Daily Summary ===');
  
  try {
    const data = await loadTestData(TEST_CHAT_ID);
    const messages = data.messages;
    const name = 'KKGT @DAY';
    
    // Group messages by date
    const dateGroups = groupMessagesByDate(messages);
    console.log(`Grouped messages into ${dateGroups.size} dates`);
    
    // Get the most recent date with sufficient messages
    let targetDate = null;
    let targetMessages = null;
    
    for (const [date, msgs] of dateGroups) {
      if (msgs.length >= 2) {
        targetDate = date;
        targetMessages = msgs;
        break;
      }
    }
    
    if (!targetDate) {
      console.log('✗ No date with sufficient messages found');
      return false;
    }
    
    console.log(`Testing with date ${targetDate} (${targetMessages.length} messages)`);
    
    // Build daily prompt
    const prompt = buildDailyPrompt(targetDate, targetMessages, name);
    if (!prompt) {
      console.log('✗ Failed to build daily prompt');
      return false;
    }
    
    console.log(`Generated daily prompt (${prompt.length} chars)`);
    
    // Generate daily summary using Gemini
    console.log('Generating daily summary with Gemini...');
    const response = await geminiDailySummary(TEST_CHAT_ID, targetDate, prompt);
    
    console.log('✓ Daily summary generated successfully');
    console.log('Response:', response);
    
    // Parse JSON response
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      console.log('Parsed JSON:', JSON.stringify(parsed, null, 2));
    } else {
      console.log('Warning: No JSON found in response');
    }
    
    return true;
  } catch (error) {
    console.error('✗ Daily summary test failed:', error.message);
    return false;
  }
}

async function main() {
  console.log('Gemini Integration Test');
  console.log('=======================\n');
  
  // Test connection first
  const connected = await testConnection();
  if (!connected) {
    console.log('\nAborting tests due to connection failure');
    process.exit(1);
  }
  
  // Test conversation summary
  const summarySuccess = await testConversationSummary();
  
  // Test daily summary
  const dailySuccess = await testDailySummary();
  
  // Summary
  console.log('\n=== Test Results ===');
  console.log(`Connection: ${connected ? '✓' : '✗'}`);
  console.log(`Conversation Summary: ${summarySuccess ? '✓' : '✗'}`);
  console.log(`Daily Summary: ${dailySuccess ? '✓' : '✗'}`);
  
  if (summarySuccess && dailySuccess) {
    console.log('\n✓ All tests passed');
    process.exit(0);
  } else {
    console.log('\n✗ Some tests failed');
    process.exit(1);
  }
}

main().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});
