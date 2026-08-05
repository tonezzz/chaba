#!/usr/bin/env node

/**
 * Activity Tracker for Strategic Focus Automation
 * Monitors git commits, file system changes, and time tracking for focus pattern analysis
 */

import { execSync } from 'child_process';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const DATA_DIR = join(process.cwd(), 'data');
const ACTIVITY_DB = join(DATA_DIR, 'focus-activity.json');
const SESSION_FILE = join(DATA_DIR, 'current-session.json');

// Ensure data directory exists
if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });

// Configuration
const CONFIG = {
  commit_window: '24h',
  file_change_threshold: 5,
  session_min_duration: 15,
  activity_decay_days: 7
};

/**
 * Load activity database
 */
function loadActivityDB() {
  if (!existsSync(ACTIVITY_DB)) {
    return {
      activities: [],
      focus_patterns: {},
      session_history: [],
      metadata: {
        created: new Date().toISOString(),
        last_updated: new Date().toISOString()
      }
    };
  }
  
  try {
    const content = readFileSync(ACTIVITY_DB, 'utf8');
    return JSON.parse(content);
  } catch (error) {
    console.error(`Error loading activity database: ${error.message}`);
    return null;
  }
}

/**
 * Save activity database
 */
function saveActivityDB(db) {
  try {
    db.metadata.last_updated = new Date().toISOString();
    writeFileSync(ACTIVITY_DB, JSON.stringify(db, null, 2));
    return true;
  } catch (error) {
    console.error(`Error saving activity database: ${error.message}`);
    return false;
  }
}

/**
 * Get current project and branch context
 */
function getProjectContext() {
  try {
    const cwd = process.cwd();
    const branch = execSync('git rev-parse --abbrev-ref HEAD', { cwd, encoding: 'utf8' }).trim();
    const project = cwd.split('/').pop();
    
    return {
      project,
      branch,
      cwd
    };
  } catch (error) {
    console.error(`Error getting project context: ${error.message}`);
    return {
      project: 'unknown',
      branch: 'unknown',
      cwd: process.cwd()
    };
  }
}

/**
 * Get recent git commits
 */
function getRecentCommits(hours = 24) {
  try {
    const since = `${hours} hours ago`;
    const commits = execSync(
      `git log --since="${since}" --pretty=format:"%H|%ai|%s"`,
      { encoding: 'utf8' }
    ).trim().split('\n');
    
    return commits.map(commit => {
      const [hash, date, message] = commit.split('|');
      return { hash, date, message };
    });
  } catch (error) {
    console.error(`Error getting recent commits: ${error.message}`);
    return [];
  }
}

/**
 * Get current focus from SSOT
 */
function getCurrentFocus() {
  const focusFile = join(process.cwd(), 'docs/ssot/ssot.focus.yml');
  if (!existsSync(focusFile)) {
    return { shared: null, branch: null };
  }
  
  try {
    const content = readFileSync(focusFile, 'utf8');
    const lines = content.split('\n');
    
    let sharedFocus = null;
    let branchFocus = null;
    let currentSection = null;
    let currentItem = null;
    let inDependencies = false;
    
    for (const line of lines) {
      const trimmed = line.trim();
      const indent = line.search(/\S|$/);
      
      // Section headers (at indent 2)
      if (indent === 2 && trimmed.startsWith('- title:')) {
        const title = trimmed.substring(9).trim();
        if (title.includes('Shared Strategic Focus Areas')) {
          currentSection = 'shared';
        } else if (title.includes('Per-Branch Strategic Focus Areas')) {
          currentSection = 'branch';
        } else {
          currentSection = null;
        }
        currentItem = null;
        inDependencies = false;
        continue;
      }
      
      // Parse item labels (at indent 6)
      if (currentSection && indent === 6 && trimmed.startsWith('- label:')) {
        currentItem = trimmed.substring(9).trim();
        inDependencies = false;
        continue;
      }
      
      // Parse status (at indent 8)
      if (currentItem && currentSection && indent === 8) {
        inDependencies = false;
        if (trimmed.startsWith('status:')) {
          const status = trimmed.substring(7).trim();
          if (status === 'active') {
            if (currentSection === 'shared') {
              sharedFocus = currentItem;
            } else if (currentSection === 'branch') {
              branchFocus = currentItem;
            }
          }
        } else if (trimmed.startsWith('dependencies:')) {
          inDependencies = true;
        }
        continue;
      }
      
      // Skip dependency items
      if (inDependencies && indent === 10 && trimmed.startsWith('- ')) {
        continue;
      }
    }
    
    return { shared: sharedFocus, branch: branchFocus };
  } catch (error) {
    console.error(`Error reading current focus: ${error.message}`);
    return { shared: null, branch: null };
  }
}

/**
 * Record activity
 */
function recordActivity(type, details = {}) {
  const db = loadActivityDB();
  if (!db) return false;
  
  const context = getProjectContext();
  const currentFocus = getCurrentFocus();
  
  const activity = {
    timestamp: new Date().toISOString(),
    project: context.project,
    branch: context.branch,
    focus_area: type === 'session_start' ? null : 
                (context.branch === 'tony-omen' ? currentFocus.branch : currentFocus.shared),
    activity_type: type,
    details: {
      ...details,
      impact_score: calculateImpactScore(type, details)
    },
    metadata: {
      session_id: getSessionId(),
      user_context: details.user_context || 'manual'
    }
  };
  
  db.activities.push(activity);
  return saveActivityDB(db);
}

/**
 * Calculate impact score for activity
 */
function calculateImpactScore(type, details) {
  let score = 5; // Base score
  
  switch (type) {
    case 'git_commit':
      score += details.files_changed ? Math.min(details.files_changed.length, 5) : 0;
      score += details.commit_message?.includes('fix') ? 2 : 0;
      score += details.commit_message?.includes('feat') ? 3 : 0;
      break;
    case 'file_change':
      score += Math.min(details.file_count || 0, 3);
      break;
    case 'session_start':
    case 'session_end':
      score = 3; // Lower impact for session management
      break;
  }
  
  return Math.min(score, 10);
}

/**
 * Get or create session ID
 */
function getSessionId() {
  if (existsSync(SESSION_FILE)) {
    try {
      const session = JSON.parse(readFileSync(SESSION_FILE, 'utf8'));
      return session.id;
    } catch (error) {
      // Generate new session ID if file is corrupted
    }
  }
  
  const sessionId = `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  const session = {
    id: sessionId,
    start_time: new Date().toISOString(),
    project_context: getProjectContext()
  };
  
  writeFileSync(SESSION_FILE, JSON.stringify(session, null, 2));
  return sessionId;
}

/**
 * Start activity tracking
 */
function startTracking() {
  console.log('🎯 Starting activity tracking for strategic focus automation\n');
  
  const context = getProjectContext();
  const currentFocus = getCurrentFocus();
  
  console.log(`📍 Project: ${context.project}`);
  console.log(`🔀 Branch: ${context.branch}`);
  console.log(`🎯 Current Focus:`);
  console.log(`   Shared: ${currentFocus.shared || 'None'}`);
  console.log(`   Branch: ${currentFocus.branch || 'None'}`);
  
  // Record session start
  recordActivity('session_start', {
    user_context: 'session_start',
    focus_state: currentFocus
  });
  
  // Get recent commits for context
  const recentCommits = getRecentCommits(CONFIG.commit_window);
  console.log(`\n📊 Recent Activity (${CONFIG.commit_window}):`);
  console.log(`   Commits: ${recentCommits.length}`);
  
  // Record recent commits as activity
  recentCommits.forEach(commit => {
    recordActivity('git_commit', {
      commit_message: commit.message,
      commit_hash: commit.hash,
      commit_date: commit.date,
      user_context: 'historical'
    });
  });
  
  console.log(`\n✅ Activity tracking started`);
  console.log(`📝 Session ID: ${getSessionId()}`);
  console.log(`💾 Activity database: ${ACTIVITY_DB}`);
}

/**
 * Stop activity tracking
 */
function stopTracking() {
  console.log('🎯 Stopping activity tracking\n');
  
  const sessionId = getSessionId();
  
  // Record session end
  recordActivity('session_end', {
    user_context: 'session_end',
    session_id: sessionId
  });
  
  // Clean up session file
  if (existsSync(SESSION_FILE)) {
    try {
      // Read session data for analysis
      const session = JSON.parse(readFileSync(SESSION_FILE, 'utf8'));
      const duration = Date.now() - new Date(session.start_time).getTime();
      const durationMinutes = Math.floor(duration / 60000);
      
      console.log(`📊 Session Duration: ${durationMinutes} minutes`);
      
      if (durationMinutes >= CONFIG.session_min_duration) {
        console.log(`✅ Session recorded (met minimum duration)`);
      } else {
        console.log(`⚠️  Session below minimum duration (${CONFIG.session_min_duration} min)`);
      }
    } catch (error) {
      console.error(`Error analyzing session: ${error.message}`);
    }
    
    try {
      // Remove session file
      execSync(`rm ${SESSION_FILE}`);
    } catch (error) {
      console.error(`Error cleaning up session file: ${error.message}`);
    }
  }
  
  console.log(`\n✅ Activity tracking stopped`);
  console.log(`💾 Activity database updated: ${ACTIVITY_DB}`);
}

/**
 * Show activity status
 */
function showStatus() {
  console.log('🎯 Activity Tracking Status\n');
  
  const db = loadActivityDB();
  if (!db) {
    console.log('❌ No activity database found');
    return;
  }
  
  const context = getProjectContext();
  const currentFocus = getCurrentFocus();
  
  console.log(`📍 Current Context:`);
  console.log(`   Project: ${context.project}`);
  console.log(`   Branch: ${context.branch}`);
  console.log(`   Shared Focus: ${currentFocus.shared || 'None'}`);
  console.log(`   Branch Focus: ${currentFocus.branch || 'None'}`);
  
  console.log(`\n📊 Activity Database:`);
  console.log(`   Total Activities: ${db.activities.length}`);
  console.log(`   Focus Patterns: ${Object.keys(db.focus_patterns).length}`);
  console.log(`   Session History: ${db.session_history.length}`);
  console.log(`   Last Updated: ${db.metadata.last_updated}`);
  
  // Recent activity summary
  const recentActivities = db.activities
    .filter(a => {
      const activityTime = new Date(a.timestamp);
      const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000);
      return activityTime > cutoff;
    });
  
  console.log(`\n📈 Recent Activity (24h): ${recentActivities.length}`);
  
  // Activity by type
  const byType = {};
  recentActivities.forEach(a => {
    byType[a.activity_type] = (byType[a.activity_type] || 0) + 1;
  });
  
  Object.entries(byType).forEach(([type, count]) => {
    console.log(`   ${type}: ${count}`);
  });
  
  // Session status
  if (existsSync(SESSION_FILE)) {
    try {
      const session = JSON.parse(readFileSync(SESSION_FILE, 'utf8'));
      const duration = Date.now() - new Date(session.start_time).getTime();
      const durationMinutes = Math.floor(duration / 60000);
      
      console.log(`\n🔄 Active Session:`);
      console.log(`   ID: ${session.id}`);
      console.log(`   Duration: ${durationMinutes} minutes`);
      console.log(`   Started: ${session.start_time}`);
    } catch (error) {
      console.log(`\n⚠️  Session file exists but could not be read`);
    }
  } else {
    console.log(`\n💤 No active session`);
  }
}

/**
 * Main command handler
 */
function main() {
  const command = process.argv[2] || 'status';
  
  switch (command) {
    case 'start':
      startTracking();
      break;
    case 'stop':
      stopTracking();
      break;
    case 'status':
      showStatus();
      break;
    default:
      console.log('Usage: node activity-tracker.mjs [start|stop|status]');
      console.log('  start  - Start activity tracking for current session');
      console.log('  stop   - Stop activity tracking and analyze session');
      console.log('  status - Show current activity tracking status');
      process.exit(1);
  }
}

main();
