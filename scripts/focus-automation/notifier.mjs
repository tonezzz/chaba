#!/usr/bin/env node

/**
 * Notification System for Strategic Focus Automation
 * Handles focus transition alerts, dependency notifications, and activity summaries
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync, unlinkSync } from 'fs';
import { join } from 'path';

const ACTIVITY_DB = join(process.cwd(), 'data/focus-activity.json');
const FOCUS_FILE = join(process.cwd(), 'docs/ssot/ssot.focus.yml');
const NOTIFICATION_DIR = join(process.cwd(), 'data/notifications');

// Ensure notification directory exists
if (!existsSync(NOTIFICATION_DIR)) mkdirSync(NOTIFICATION_DIR, { recursive: true });

// Configuration
const CONFIG = {
  notification_retention_days: 30,
  summary_frequency_hours: 24,
  dependency_check_interval_hours: 1
};

/**
 * Load activity database
 */
function loadActivityDB() {
  if (!existsSync(ACTIVITY_DB)) {
    return null;
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
 * Load SSOT focus data
 */
function loadFocusData() {
  if (!existsSync(FOCUS_FILE)) {
    return null;
  }
  
  try {
    const content = readFileSync(FOCUS_FILE, 'utf8');
    const lines = content.split('\n');
    
    const focusData = {
      shared: [],
      branch: []
    };
    
    let currentSection = null;
    let currentItem = null;
    let inDependencies = false;
    
    for (const line of lines) {
      const trimmed = line.trim();
      const indent = line.search(/\S|$/);
      
      // Section headers
      if (indent === 2 && trimmed.startsWith('- title:')) {
        // Save previous item
        if (currentItem && currentSection) {
          if (currentSection === 'shared') {
            focusData.shared.push(currentItem);
          } else if (currentSection === 'branch') {
            focusData.branch.push(currentItem);
          }
        }
        
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
      
      // Parse item labels
      if (currentSection && indent === 6 && trimmed.startsWith('- label:')) {
        // Save previous item
        if (currentItem) {
          if (currentSection === 'shared') {
            focusData.shared.push(currentItem);
          } else if (currentSection === 'branch') {
            focusData.branch.push(currentItem);
          }
        }
        
        currentItem = {
          label: trimmed.substring(9).trim(),
          status: 'pending',
          priority: 'medium',
          dependencies: []
        };
        inDependencies = false;
        continue;
      }
      
      // Parse item properties
      if (currentItem && currentSection && indent === 8) {
        inDependencies = false;
        if (trimmed.startsWith('status:')) {
          currentItem.status = trimmed.substring(7).trim();
        } else if (trimmed.startsWith('priority:')) {
          currentItem.priority = trimmed.substring(9).trim();
        } else if (trimmed.startsWith('dependencies:')) {
          inDependencies = true;
        }
        continue;
      }
      
      // Parse dependency items
      if (currentItem && currentSection && inDependencies && indent === 10 && trimmed.startsWith('- ')) {
        currentItem.dependencies.push(trimmed.substring(2).trim());
        continue;
      }
    }
    
    // Don't forget the last item
    if (currentItem && currentSection) {
      if (currentSection === 'shared') {
        focusData.shared.push(currentItem);
      } else if (currentSection === 'branch') {
        focusData.branch.push(currentItem);
      }
    }
    
    return focusData;
  } catch (error) {
    console.error(`Error loading focus data: ${error.message}`);
    return null;
  }
}

/**
 * Create notification
 */
function createNotification(type, title, message, data = {}) {
  const notification = {
    id: `notif-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
    type: type,
    title: title,
    message: message,
    data: data,
    created: new Date().toISOString(),
    read: false
  };
  
  return notification;
}

/**
 * Save notification
 */
function saveNotification(notification) {
  const filename = join(NOTIFICATION_DIR, `${notification.id}.json`);
  try {
    writeFileSync(filename, JSON.stringify(notification, null, 2));
    return true;
  } catch (error) {
    console.error(`Error saving notification: ${error.message}`);
    return false;
  }
}

/**
 * Load all notifications
 */
function loadNotifications() {
  if (!existsSync(NOTIFICATION_DIR)) {
    return [];
  }
  
  try {
    const files = readdirSync(NOTIFICATION_DIR);
    
    const notifications = [];
    for (const file of files) {
      if (file.endsWith('.json')) {
        try {
          const content = readFileSync(join(NOTIFICATION_DIR, file), 'utf8');
          notifications.push(JSON.parse(content));
        } catch (error) {
          console.error(`Error loading notification ${file}: ${error.message}`);
        }
      }
    }
    
    return notifications.sort((a, b) => new Date(b.created) - new Date(a.created));
  } catch (error) {
    console.error(`Error loading notifications: ${error.message}`);
    return [];
  }
}

/**
 * Check for dependency completions
 */
function checkDependencyCompletions() {
  console.log('🎯 Checking Dependency Completions\n');
  
  const focusData = loadFocusData();
  if (!focusData) return;
  
  const allFocuses = [...focusData.shared, ...focusData.branch];
  const notifications = [];
  
  // Check each focus for newly satisfied dependencies
  allFocuses.forEach(focus => {
    if (focus.status === 'completed' || !focus.dependencies || focus.dependencies.length === 0) {
      return;
    }
    
    const satisfiedDeps = focus.dependencies.filter(dep => {
      const depFocus = allFocuses.find(f => f.label === dep);
      return depFocus && depFocus.status === 'completed';
    });
    
    const unsatisfiedDeps = focus.dependencies.filter(dep => {
      const depFocus = allFocuses.find(f => f.label === dep);
      return !depFocus || depFocus.status !== 'completed';
    });
    
    // If all dependencies are now satisfied
    if (satisfiedDeps.length === focus.dependencies.length && focus.dependencies.length > 0) {
      const notification = createNotification(
        'dependency_ready',
        `Focus Ready to Activate: ${focus.label}`,
        `All dependencies for "${focus.label}" are now satisfied. You can activate this focus.`,
        {
          focus: focus.label,
          priority: focus.priority,
          dependencies_met: satisfiedDeps,
          section: focusData.shared.includes(focus) ? 'shared' : 'branch'
        }
      );
      notifications.push(notification);
    }
    // If some dependencies are satisfied
    else if (satisfiedDeps.length > 0 && unsatisfiedDeps.length > 0) {
      const notification = createNotification(
        'dependency_progress',
        `Dependency Progress: ${focus.label}`,
        `${satisfiedDeps.length}/${focus.dependencies.length} dependencies satisfied for "${focus.label}". Still waiting for: ${unsatisfiedDeps.join(', ')}`,
        {
          focus: focus.label,
          satisfied: satisfiedDeps,
          unsatisfied: unsatisfiedDeps,
          section: focusData.shared.includes(focus) ? 'shared' : 'branch'
        }
      );
      notifications.push(notification);
    }
  });
  
  if (notifications.length === 0) {
    console.log('✅ No new dependency completions detected');
    return;
  }
  
  console.log(`📢 ${notifications.length} dependency notifications:\n`);
  
  notifications.forEach(notif => {
    console.log(`${notif.type === 'dependency_ready' ? '✅' : '⏳'} ${notif.title}`);
    console.log(`   ${notif.message}`);
    console.log();
    saveNotification(notif);
  });
}

/**
 * Generate activity summary
 */
function generateActivitySummary() {
  console.log('🎯 Generating Activity Summary\n');
  
  const db = loadActivityDB();
  if (!db) {
    console.log('❌ No activity data available');
    return;
  }
  
  const cutoff = new Date(Date.now() - CONFIG.summary_frequency_hours * 60 * 60 * 1000);
  const recentActivities = db.activities.filter(a => new Date(a.timestamp) > cutoff);
  
  if (recentActivities.length === 0) {
    console.log('ℹ️  No recent activity to summarize');
    return;
  }
  
  // Generate summary statistics
  const summary = {
    total_activities: recentActivities.length,
    by_type: {},
    by_project: {},
    by_focus: {},
    time_range: {
      from: new Date(Math.min(...recentActivities.map(a => new Date(a.timestamp)))).toISOString(),
      to: new Date(Math.max(...recentActivities.map(a => new Date(a.timestamp)))).toISOString()
    }
  };
  
  recentActivities.forEach(a => {
    summary.by_type[a.activity_type] = (summary.by_type[a.activity_type] || 0) + 1;
    summary.by_project[a.project] = (summary.by_project[a.project] || 0) + 1;
    if (a.focus_area) {
      summary.by_focus[a.focus_area] = (summary.by_focus[a.focus_area] || 0) + 1;
    }
  });
  
  const notification = createNotification(
    'activity_summary',
    `Activity Summary: ${summary.total_activities} activities`,
    `Activity summary for the past ${CONFIG.summary_frequency_hours}h: ${summary.total_activities} total activities across ${Object.keys(summary.by_project).length} projects.`,
    summary
  );
  
  console.log('📊 Activity Summary:');
  console.log(`   Total Activities: ${summary.total_activities}`);
  console.log(`   Time Range: ${summary.time_range.from} to ${summary.time_range.to}`);
  console.log(`   By Type: ${JSON.stringify(summary.by_type)}`);
  console.log(`   By Project: ${JSON.stringify(summary.by_project)}`);
  console.log(`   By Focus: ${JSON.stringify(summary.by_focus)}`);
  
  saveNotification(notification);
  console.log('\n✅ Activity summary notification saved');
}

/**
 * Show notifications
 */
function showNotifications() {
  console.log('🎯 Notifications\n');
  
  const notifications = loadNotifications();
  
  if (notifications.length === 0) {
    console.log('📭 No notifications');
    return;
  }
  
  const unread = notifications.filter(n => !n.read);
  const read = notifications.filter(n => n.read);
  
  console.log(`📬 ${unread.length} unread, ${read.length} read notifications\n`);
  
  if (unread.length > 0) {
    console.log('🔔 Unread Notifications:');
    unread.forEach(notif => {
      const icon = notif.type === 'dependency_ready' ? '✅' : 
                   notif.type === 'dependency_progress' ? '⏳' : 
                   notif.type === 'activity_summary' ? '📊' : '📢';
      console.log(`${icon} ${notif.title}`);
      console.log(`   ${notif.message}`);
      console.log(`   ${notif.created}`);
      console.log();
    });
  }
  
  if (read.length > 0) {
    console.log('📖 Read Notifications:');
    read.slice(0, 5).forEach(notif => {
      console.log(`✓ ${notif.title} (${notif.created})`);
    });
    
    if (read.length > 5) {
      console.log(`   ... and ${read.length - 5} more`);
    }
  }
}

/**
 * Mark notification as read
 */
function markAsRead(notificationId) {
  const filename = join(NOTIFICATION_DIR, `${notificationId}.json`);
  if (!existsSync(filename)) {
    console.log(`❌ Notification not found: ${notificationId}`);
    return false;
  }
  
  try {
    const content = readFileSync(filename, 'utf8');
    const notification = JSON.parse(content);
    notification.read = true;
    writeFileSync(filename, JSON.stringify(notification, null, 2));
    console.log(`✅ Marked as read: ${notification.title}`);
    return true;
  } catch (error) {
    console.error(`Error marking notification as read: ${error.message}`);
    return false;
  }
}

/**
 * Clear old notifications
 */
function clearOldNotifications() {
  console.log('🎯 Clearing Old Notifications\n');
  
  const notifications = loadNotifications();
  const cutoff = new Date(Date.now() - CONFIG.notification_retention_days * 24 * 60 * 60 * 1000);
  
  const oldNotifications = notifications.filter(n => new Date(n.created) < cutoff);
  
  if (oldNotifications.length === 0) {
    console.log('✅ No old notifications to clear');
    return;
  }
  
  let deletedCount = 0;
  oldNotifications.forEach(notif => {
    const filename = join(NOTIFICATION_DIR, `${notif.id}.json`);
    try {
      unlinkSync(filename);
      deletedCount++;
    } catch (error) {
      console.error(`Error deleting notification ${notif.id}: ${error.message}`);
    }
  });
  
  console.log(`🗑️  Cleared ${deletedCount} old notifications`);
}

/**
 * Main command handler
 */
function main() {
  const command = process.argv[2] || 'show';
  
  switch (command) {
    case 'check':
      checkDependencyCompletions();
      break;
    case 'summary':
      generateActivitySummary();
      break;
    case 'show':
      showNotifications();
      break;
    case 'read':
      const notificationId = process.argv[3];
      if (!notificationId) {
        console.log('Usage: node notifier.mjs read <notification-id>');
        process.exit(1);
      }
      markAsRead(notificationId);
      break;
    case 'clear':
      clearOldNotifications();
      break;
    default:
      console.log('Usage: node notifier.mjs [check|summary|show|read|clear]');
      console.log('  check    - Check for dependency completions');
      console.log('  summary  - Generate activity summary');
      console.log('  show     - Show all notifications');
      console.log('  read     - Mark notification as read');
      console.log('  clear    - Clear old notifications');
      process.exit(1);
  }
}

main();
