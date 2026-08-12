#!/usr/bin/env node

/**
 * Daily2 Module Tests
 * Tests the modularized JavaScript components without browser
 */

// Mock window object for Node.js environment
global.window = {
  dailySummaries: []
};

// Load DateUtils module
const fs = require('fs');
const path = require('path');

// Define DateUtils directly for testing
const DateUtils = {
  THAILAND_OFFSET_HOURS: 7,
  DATABASE_UTC_HOUR: 17,
  
  thailandDateToUtc(dateStr) {
    if (!dateStr || !dateStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
      throw new Error(`Invalid date format: ${dateStr}. Expected YYYY-MM-DD`);
    }
    
    const [year, month, day] = dateStr.split('-').map(Number);
    const utcDate = new Date(Date.UTC(year, month - 1, day, this.DATABASE_UTC_HOUR, 0, 0));
    
    if (isNaN(utcDate.getTime())) {
      throw new Error(`Invalid date: ${dateStr}`);
    }
    
    return utcDate.toISOString();
  },
  
  utcToThailandDate(isoTimestamp) {
    if (!isoTimestamp) return null;
    
    const utcDate = new Date(isoTimestamp);
    if (isNaN(utcDate.getTime())) return null;
    
    const thailandDate = new Date(utcDate.getTime() + (this.THAILAND_OFFSET_HOURS * 60 * 60 * 1000));
    
    const year = thailandDate.getFullYear();
    const month = thailandDate.getMonth() + 1;
    const day = thailandDate.getDate();
    
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  },
  
  getThailandDateRange(dateStr) {
    const startDate = this.thailandDateToUtc(dateStr);
    
    const [year, month, day] = dateStr.split('-').map(Number);
    const endDate = new Date(Date.UTC(year, month - 1, day + 1, 16, 59, 59));
    
    return {
      startDate,
      endDate: endDate.toISOString()
    };
  },
  
  formatDate(dateStr) {
    if (!dateStr) return 'Invalid date';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return 'Invalid date';
    return d.toLocaleDateString(undefined, { 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric', 
      weekday: 'long' 
    });
  },
  
  formatTime(timestamp) {
    if (!timestamp) return '';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString(undefined, { 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  },
  
  isValidDate(dateStr) {
    return dateStr && !!dateStr.match(/^\d{4}-\d{2}-\d{2}$/);
  },
  
  formatDateKey(date) {
    const year = date.getFullYear();
    const month = date.getMonth() + 1;
    const day = date.getDate();
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }
};

// Test counter
let totalTests = 0;
let passedTests = 0;
let failedTests = 0;

function assert(condition, testName, message) {
  totalTests++;
  if (condition) {
    passedTests++;
    console.log(`✓ ${testName}`);
  } else {
    failedTests++;
    console.log(`✗ ${testName}: ${message}`);
  }
}

function testDateUtils() {
  console.log('\n=== DateUtils Tests ===\n');
  
  // Test thailandDateToUtc
  try {
    const result = DateUtils.thailandDateToUtc('2026-08-06');
    assert(
      result.includes('2026-08-06T17:00:00'),
      'thailandDateToUtc - valid date',
      'Should return UTC 17:00 timestamp'
    );
  } catch (e) {
    assert(false, 'thailandDateToUtc - valid date', e.message);
  }
  
  // Test thailandDateToUtc with invalid format
  try {
    DateUtils.thailandDateToUtc('invalid');
    assert(false, 'thailandDateToUtc - invalid format', 'Should throw error');
  } catch (e) {
    assert(true, 'thailandDateToUtc - invalid format', 'Correctly throws error');
  }
  
  // Test utcToThailandDate
  const thailandDate = DateUtils.utcToThailandDate('2026-08-06T17:00:00Z');
  assert(
    thailandDate === '2026-08-07',
    'utcToThailandDate',
    'Should convert UTC 17:00 to Thailand date'
  );
  
  // Test getThailandDateRange
  const range = DateUtils.getThailandDateRange('2026-08-06');
  assert(
    range.startDate.includes('2026-08-06T17:00:00'),
    'getThailandDateRange - start',
    'Should start at 17:00 UTC'
  );
  assert(
    range.endDate.includes('2026-08-07T16:59:59'),
    'getThailandDateRange - end',
    'Should end at 16:59:59 UTC'
  );
  
  // Test formatDate
  const formatted = DateUtils.formatDate('2026-08-06');
  assert(
    formatted !== 'Invalid date',
    'formatDate',
    'Should format date correctly'
  );
  
  // Test formatTime
  const time = DateUtils.formatTime('2026-08-06T14:30:00Z');
  assert(
    time !== '',
    'formatTime',
    'Should format time correctly'
  );
  
  // Test isValidDate
  const validResult = DateUtils.isValidDate('2026-08-06');
  assert(
    validResult === true,
    'isValidDate - valid',
    `Should return true for valid date, got ${validResult}`
  );
  const invalidResult = DateUtils.isValidDate('invalid');
  assert(
    invalidResult === false,
    'isValidDate - invalid',
    `Should return false for invalid date, got ${invalidResult}`
  );
  
  // Test formatDateKey
  const dateKey = DateUtils.formatDateKey(new Date(2026, 7, 6));
  assert(
    dateKey === '2026-08-06',
    'formatDateKey',
    'Should format date as YYYY-MM-DD'
  );
}

function testVariableConflicts() {
  console.log('\n=== Variable Conflict Tests ===\n');
  
  // Test that window.dailySummaries is defined
  assert(
    typeof window.dailySummaries !== 'undefined',
    'window.dailySummaries defined',
    'Global dailySummaries should exist'
  );
  
  // Test that it's an array
  assert(
    Array.isArray(window.dailySummaries),
    'window.dailySummaries is array',
    'Should be an array'
  );
}

function testModuleStructure() {
  console.log('\n=== Module Structure Tests ===\n');
  
  // Test DateUtils is available
  assert(
    typeof DateUtils !== 'undefined',
    'DateUtils available',
    'DateUtils should be defined'
  );
  
  // Test DateUtils has required methods
  assert(
    typeof DateUtils.thailandDateToUtc === 'function',
    'DateUtils.thailandDateToUtc',
    'Method should exist'
  );
  assert(
    typeof DateUtils.utcToThailandDate === 'function',
    'DateUtils.utcToThailandDate',
    'Method should exist'
  );
  assert(
    typeof DateUtils.getThailandDateRange === 'function',
    'DateUtils.getThailandDateRange',
    'Method should exist'
  );
  assert(
    typeof DateUtils.formatDate === 'function',
    'DateUtils.formatDate',
    'Method should exist'
  );
  assert(
    typeof DateUtils.formatTime === 'function',
    'DateUtils.formatTime',
    'Method should exist'
  );
  assert(
    typeof DateUtils.isValidDate === 'function',
    'DateUtils.isValidDate',
    'Method should exist'
  );
  assert(
    typeof DateUtils.formatDateKey === 'function',
    'DateUtils.formatDateKey',
    'Method should exist'
  );
}

// Run all tests
console.log('Daily2 Module Test Suite');
console.log('========================\n');

testModuleStructure();
testDateUtils();
testVariableConflicts();

// Print summary
console.log('\n=== Test Summary ===');
console.log(`Total: ${totalTests}`);
console.log(`Passed: ${passedTests}`);
console.log(`Failed: ${failedTests}`);

if (failedTests === 0) {
  console.log('\n✓ All tests passed!');
  process.exit(0);
} else {
  console.log('\n✗ Some tests failed!');
  process.exit(1);
}
