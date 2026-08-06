/**
 * Test script for Thai language detection and prompt generation
 * Tests language detection and Thai prompt generation without requiring API calls
 */

import { detectLanguage, detectConversationLanguage, getLanguageSpecificPrompt, getLanguageSpecificDailyPrompt } from './language-detection.mjs';

function testLanguageDetection() {
  console.log('=== Testing Language Detection ===\n');
  
  const testCases = [
    { text: 'Hello world', expected: 'english' },
    { text: 'สวัสดีชาวโลก', expected: 'thai' },
    { text: 'Hello สวัสดี world ชาวโลก', expected: 'mixed' },
    { text: 'Mostly English with some ไทย characters', expected: 'mixed' },
    { text: '', expected: 'unknown' },
    { text: 'สวัสดีครับ ผมชื่อ Tony ครับ', expected: 'thai' },
    { text: 'My name is Tony and I live in Thailand', expected: 'english' }
  ];
  
  let passed = 0;
  let failed = 0;
  
  for (const { text, expected } of testCases) {
    const result = detectLanguage(text);
    const status = result === expected ? '✓' : '✗';
    console.log(`${status} "${text.substring(0, 30)}${text.length > 30 ? '...' : ''}" -> ${result} (expected: ${expected})`);
    
    if (result === expected) {
      passed++;
    } else {
      failed++;
    }
  }
  
  console.log(`\nLanguage Detection: ${passed}/${testCases.length} passed`);
  return failed === 0;
}

function testConversationLanguageDetection() {
  console.log('\n=== Testing Conversation Language Detection ===\n');
  
  const testCases = [
    {
      messages: [
        { text: 'Hello' },
        { text: 'How are you?' },
        { text: 'I am fine' }
      ],
      expected: 'english'
    },
    {
      messages: [
        { text: 'สวัสดี' },
        { text: 'เป็นอย่างไรบ้าง' },
        { text: 'ผมสบายดีครับ' }
      ],
      expected: 'thai'
    },
    {
      messages: [
        { text: 'Hello' },
        { text: 'สวัสดี' },
        { text: 'How are you?' }
      ],
      expected: 'mixed'
    },
    {
      messages: [],
      expected: 'english'
    }
  ];
  
  let passed = 0;
  let failed = 0;
  
  for (const { messages, expected } of testCases) {
    const result = detectConversationLanguage(messages);
    const status = result === expected ? '✓' : '✗';
    console.log(`${status} ${messages.length} messages -> ${result} (expected: ${expected})`);
    
    if (result === expected) {
      passed++;
    } else {
      failed++;
    }
  }
  
  console.log(`\nConversation Language Detection: ${passed}/${testCases.length} passed`);
  return failed === 0;
}

function testThaiPrompts() {
  console.log('\n=== Testing Thai Prompt Generation ===\n');
  
  const name = 'Test Chat';
  const lines = ['Message 1', 'Message 2', 'Message 3'];
  const date = '2026-08-06';
  
  // Test Thai prompt
  const thaiPrompt = getLanguageSpecificPrompt('thai', name, lines);
  console.log('Thai prompt generated:', thaiPrompt.substring(0, 100) + '...');
  const hasThai = thaiPrompt.includes('สรุปการสนทนา');
  console.log(`${hasThai ? '✓' : '✗'} Contains Thai text`);
  
  // Test Thai daily prompt
  const thaiDailyPrompt = getLanguageSpecificDailyPrompt('thai', date, name, lines);
  console.log('\nThai daily prompt generated:', thaiDailyPrompt.substring(0, 100) + '...');
  const hasThaiDaily = thaiDailyPrompt.includes('สกัดข้อมูล');
  console.log(`${hasThaiDaily ? '✓' : '✗'} Contains Thai daily text`);
  
  // Test mixed language prompt
  const mixedPrompt = getLanguageSpecificPrompt('mixed', name, lines);
  console.log('\nMixed prompt generated:', mixedPrompt.substring(0, 100) + '...');
  const hasMixed = mixedPrompt.includes('Thai/English mix');
  console.log(`${hasMixed ? '✓' : '✗'} Contains mixed language instruction`);
  
  // Test mixed daily prompt
  const mixedDailyPrompt = getLanguageSpecificDailyPrompt('mixed', date, name, lines);
  console.log('\nMixed daily prompt generated:', mixedDailyPrompt.substring(0, 100) + '...');
  const hasMixedDaily = mixedDailyPrompt.includes('Extract from these LINE messages');
  console.log(`${hasMixedDaily ? '✓' : '✗'} Contains mixed daily instruction`);
  
  return hasThai && hasThaiDaily && hasMixed && hasMixedDaily;
}

async function testGeminiIntegration() {
  console.log('\n=== Testing Gemini Integration with Language ===\n');
  
  // Test that the functions accept language parameter
  const { geminiDailySummary, geminiBatchDailySummary } = await import('./gemini-integration.mjs');
  
  console.log('✓ geminiDailySummary function exists');
  console.log('✓ geminiBatchDailySummary function exists');
  
  // Check function signatures (they should accept language parameter)
  const dailySummaryStr = geminiDailySummary.toString();
  const batchSummaryStr = geminiBatchDailySummary.toString();
  
  const hasLanguageParam = dailySummaryStr.includes('language') && batchSummaryStr.includes('language');
  console.log(`${hasLanguageParam ? '✓' : '✗'} Functions accept language parameter`);
  
  // Check for Thai system prompts
  const hasThaiSystemPrompt = dailySummaryStr.includes('คุณแยกข้อมูลที่มีโครงสร้าง');
  console.log(`${hasThaiSystemPrompt ? '✓' : '✗'} Contains Thai system prompt`);
  
  const hasMixedSupport = dailySummaryStr.includes('language === \'thai\' || language === \'mixed\'');
  console.log(`${hasMixedSupport ? '✓' : '✗'} Supports mixed language`);
  
  return hasLanguageParam && hasThaiSystemPrompt && hasMixedSupport;
}

async function main() {
  console.log('Thai Language Processing Test');
  console.log('================================\n');
  
  const detectionPassed = testLanguageDetection();
  const conversationDetectionPassed = testConversationLanguageDetection();
  const promptsPassed = testThaiPrompts();
  const integrationPassed = await testGeminiIntegration();
  
  console.log('\n=== Test Results ===');
  console.log(`Language Detection: ${detectionPassed ? '✓' : '✗'}`);
  console.log(`Conversation Detection: ${conversationDetectionPassed ? '✓' : '✗'}`);
  console.log(`Thai Prompts: ${promptsPassed ? '✓' : '✗'}`);
  console.log(`Gemini Integration: ${integrationPassed ? '✓' : '✗'}`);
  
  const allPassed = detectionPassed && conversationDetectionPassed && promptsPassed && integrationPassed;
  
  if (allPassed) {
    console.log('\n✓ All Thai language processing tests passed');
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
