#!/usr/bin/env node

/**
 * Predictive Planner for Strategic Focus Automation
 * Calculates project velocity, estimates completion times, and generates strategic roadmaps
 */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const ACTIVITY_DB = join(process.cwd(), 'data/focus-activity.json');
const FOCUS_FILE = join(process.cwd(), 'docs/ssot/ssot.focus.yml');

// Configuration
const CONFIG = {
  velocity_window_days: 30,
  prediction_horizon_weeks: 4,
  min_activities_for_velocity: 10
};

/**
 * Load activity database
 */
function loadActivityDB() {
  if (!existsSync(ACTIVITY_DB)) {
    console.log('❌ No activity database found. Run activity-tracker.mjs start first.');
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
    console.log('❌ No focus file found.');
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
          dependencies: [],
          estimated_duration: 'Unknown'
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
        } else if (trimmed.startsWith('estimated_duration:')) {
          currentItem.estimated_duration = trimmed.substring(19).trim();
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
 * Calculate project velocity metrics
 */
function calculateVelocity(db) {
  const cutoff = new Date(Date.now() - CONFIG.velocity_window_days * 24 * 60 * 60 * 1000);
  const recentActivities = db.activities.filter(a => new Date(a.timestamp) > cutoff);
  
  if (recentActivities.length < CONFIG.min_activities_for_velocity) {
    console.log(`⚠️  Insufficient activity data for velocity calculation (${recentActivities.length} < ${CONFIG.min_activities_for_velocity})`);
    return null;
  }
  
  // Calculate velocity metrics
  const velocity = {
    total_activities: recentActivities.length,
    activities_per_day: recentActivities.length / CONFIG.velocity_window_days,
    by_project: {},
    by_focus: {},
    by_type: {},
    completion_rate: 0,
    average_impact: 0
  };
  
  // By project
  recentActivities.forEach(a => {
    velocity.by_project[a.project] = (velocity.by_project[a.project] || 0) + 1;
  });
  
  // By focus area
  recentActivities.forEach(a => {
    if (a.focus_area) {
      velocity.by_focus[a.focus_area] = (velocity.by_focus[a.focus_area] || 0) + 1;
    }
  });
  
  // By activity type
  recentActivities.forEach(a => {
    velocity.by_type[a.activity_type] = (velocity.by_type[a.activity_type] || 0) + 1;
  });
  
  // Calculate completion rate (session_end activities)
  const sessionEnds = recentActivities.filter(a => a.activity_type === 'session_end').length;
  const sessionStarts = recentActivities.filter(a => a.activity_type === 'session_start').length;
  velocity.completion_rate = sessionStarts > 0 ? sessionEnds / sessionStarts : 0;
  
  // Calculate average impact score
  const totalImpact = recentActivities.reduce((sum, a) => sum + (a.details?.impact_score || 0), 0);
  velocity.average_impact = totalImpact / recentActivities.length;
  
  return velocity;
}

/**
 * Parse duration string to days
 */
function parseDurationToDays(durationStr) {
  if (!durationStr || durationStr === 'Unknown' || durationStr === 'Ongoing') {
    return null;
  }
  
  // Handle various formats
  const lower = durationStr.toLowerCase();
  
  if (lower.includes('session')) {
    const sessions = parseInt(lower) || 1;
    return sessions * 0.5; // Assume 0.5 days per session
  }
  
  if (lower.includes('week')) {
    const weeks = parseInt(lower) || 1;
    return weeks * 7;
  }
  
  if (lower.includes('day')) {
    return parseInt(lower) || 1;
  }
  
  if (lower.includes('month')) {
    const months = parseInt(lower) || 1;
    return months * 30;
  }
  
  return null;
}

/**
 * Estimate focus completion timeline
 */
function estimateTimeline(focusData, velocity) {
  if (!velocity) {
    console.log('⚠️  Cannot estimate timeline without velocity data');
    return null;
  }
  
  const allFocuses = [...focusData.shared, ...focusData.branch];
  const timeline = [];
  
  allFocuses.forEach(focus => {
    if (focus.status === 'completed') return;
    
    const durationDays = parseDurationToDays(focus.estimated_duration);
    const dependencies = focus.dependencies || [];
    
    // Estimate completion date based on dependencies and duration
    let startDate = new Date();
    let estimatedDays = durationDays || 7; // Default to 1 week if unknown
    
    // Add dependency delays
    let dependencyDelay = 0;
    dependencies.forEach(dep => {
      const depFocus = allFocuses.find(f => f.label === dep);
      if (depFocus && depFocus.status !== 'completed') {
        const depDuration = parseDurationToDays(depFocus.estimated_duration);
        dependencyDelay += depDuration || 7;
      }
    });
    
    estimatedDays += dependencyDelay;
    
    // Adjust based on velocity
    const velocityFactor = velocity.activities_per_day > 0 ? 
      Math.log(velocity.activities_per_day + 1) : 1;
    estimatedDays = estimatedDays / velocityFactor;
    
    const completionDate = new Date(startDate.getTime() + estimatedDays * 24 * 60 * 60 * 1000);
    
    timeline.push({
      focus: focus.label,
      status: focus.status,
      priority: focus.priority,
      current_dependencies: dependencies,
      estimated_days: Math.round(estimatedDays),
      estimated_completion: completionDate.toISOString().split('T')[0],
      confidence: durationDays ? 'high' : 'low'
    });
  });
  
  // Sort by estimated completion date
  timeline.sort((a, b) => new Date(a.estimated_completion) - new Date(b.estimated_completion));
  
  return timeline;
}

/**
 * Identify potential bottlenecks
 */
function identifyBottlenecks(focusData, velocity) {
  const allFocuses = [...focusData.shared, ...focusData.branch];
  const bottlenecks = [];
  
  // Find focuses that block many others
  allFocuses.forEach(focus => {
    const blockingCount = allFocuses.filter(f => 
      f.dependencies && f.dependencies.includes(focus.label)
    ).length;
    
    if (blockingCount > 1) {
      bottlenecks.push({
        focus: focus.label,
        status: focus.status,
        blocking_count: blockingCount,
        blocked_focuses: allFocuses.filter(f => 
          f.dependencies && f.dependencies.includes(focus.label)
        ).map(f => f.label),
        severity: focus.status === 'pending' ? 'high' : 'medium'
      });
    }
  });
  
  // Sort by blocking count
  bottlenecks.sort((a, b) => b.blocking_count - a.blocking_count);
  
  return bottlenecks;
}

/**
 * Generate strategic roadmap
 */
function generateRoadmap(focusData, timeline) {
  if (!timeline) {
    console.log('⚠️  Cannot generate roadmap without timeline');
    return null;
  }
  
  const roadmap = {
    immediate: [],  // Next 1 week
    short_term: [],  // 1-2 weeks
    medium_term: [], // 2-4 weeks
    long_term: []    // 4+ weeks
  };
  
  const now = new Date();
  const oneWeek = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
  const twoWeeks = new Date(now.getTime() + 14 * 24 * 60 * 60 * 1000);
  const fourWeeks = new Date(now.getTime() + 28 * 24 * 60 * 60 * 1000);
  
  timeline.forEach(item => {
    const completionDate = new Date(item.estimated_completion);
    
    if (completionDate <= oneWeek) {
      roadmap.immediate.push(item);
    } else if (completionDate <= twoWeeks) {
      roadmap.short_term.push(item);
    } else if (completionDate <= fourWeeks) {
      roadmap.medium_term.push(item);
    } else {
      roadmap.long_term.push(item);
    }
  });
  
  return roadmap;
}

/**
 * Show velocity metrics
 */
function showVelocity() {
  console.log('🎯 Project Velocity Analysis\n');
  
  const db = loadActivityDB();
  if (!db) return;
  
  const velocity = calculateVelocity(db);
  if (!velocity) return;
  
  console.log('📊 Overall Velocity Metrics:');
  console.log(`   Total Activities: ${velocity.total_activities}`);
  console.log(`   Activities/Day: ${velocity.activities_per_day.toFixed(2)}`);
  console.log(`   Completion Rate: ${(velocity.completion_rate * 100).toFixed(0)}%`);
  console.log(`   Average Impact: ${velocity.average_impact.toFixed(1)}/10`);
  
  console.log('\n📁 Velocity by Project:');
  Object.entries(velocity.by_project)
    .sort(([,a], [,b]) => b - a)
    .forEach(([project, count]) => {
      const percentage = (count / velocity.total_activities * 100).toFixed(0);
      console.log(`   ${project}: ${count} (${percentage}%)`);
    });
  
  console.log('\n🎯 Velocity by Focus Area:');
  Object.entries(velocity.by_focus)
    .sort(([,a], [,b]) => b - a)
    .forEach(([focus, count]) => {
      const percentage = (count / velocity.total_activities * 100).toFixed(0);
      console.log(`   ${focus}: ${count} (${percentage}%)`);
    });
  
  console.log('\n🔧 Velocity by Activity Type:');
  Object.entries(velocity.by_type)
    .sort(([,a], [,b]) => b - a)
    .forEach(([type, count]) => {
      const percentage = (count / velocity.total_activities * 100).toFixed(0);
      console.log(`   ${type}: ${count} (${percentage}%)`);
    });
}

/**
 * Show timeline
 */
function showTimeline() {
  console.log('🎯 Predictive Focus Timeline\n');
  
  const db = loadActivityDB();
  const focusData = loadFocusData();
  if (!db || !focusData) return;
  
  const velocity = calculateVelocity(db);
  const timeline = estimateTimeline(focusData, velocity);
  
  if (!timeline) return;
  
  console.log(`📅 Estimated Completion Timeline (${CONFIG.prediction_horizon_weeks} weeks)\n`);
  
  timeline.forEach((item, index) => {
    const statusIcon = item.status === 'active' ? '🔄' : 
                     item.status === 'completed' ? '✅' : '⏳';
    console.log(`${index + 1}. ${statusIcon} ${item.focus}`);
    console.log(`   Status: ${item.status}`);
    console.log(`   Priority: ${item.priority}`);
    console.log(`   Est. Completion: ${item.estimated_completion}`);
    console.log(`   Est. Duration: ${item.estimated_days} days`);
    console.log(`   Confidence: ${item.confidence}`);
    
    if (item.current_dependencies.length > 0) {
      console.log(`   Dependencies: ${item.current_dependencies.join(', ')}`);
    }
    
    console.log();
  });
}

/**
 * Show bottlenecks
 */
function showBottlenecks() {
  console.log('🎯 Potential Bottlenecks\n');
  
  const focusData = loadFocusData();
  if (!focusData) return;
  
  const db = loadActivityDB();
  const velocity = db ? calculateVelocity(db) : null;
  
  const bottlenecks = identifyBottlenecks(focusData, velocity);
  
  if (bottlenecks.length === 0) {
    console.log('✅ No significant bottlenecks identified');
    return;
  }
  
  console.log(`⚠️  ${bottlenecks.length} potential bottlenecks found:\n`);
  
  bottlenecks.forEach((bottleneck, index) => {
    const severityIcon = bottleneck.severity === 'high' ? '🔴' : '🟡';
    console.log(`${index + 1}. ${severityIcon} ${bottleneck.focus}`);
    console.log(`   Status: ${bottleneck.status}`);
    console.log(`   Blocking: ${bottleneck.blocking_count} focuses`);
    console.log(`   Blocked Focuses: ${bottleneck.blocked_focuses.join(', ')}`);
    console.log();
  });
}

/**
 * Show roadmap
 */
function showRoadmap() {
  console.log('🎯 Strategic Roadmap\n');
  
  const db = loadActivityDB();
  const focusData = loadFocusData();
  if (!db || !focusData) return;
  
  const velocity = calculateVelocity(db);
  const timeline = estimateTimeline(focusData, velocity);
  const roadmap = generateRoadmap(focusData, timeline);
  
  if (!roadmap) return;
  
  console.log('🗓️  Strategic Focus Roadmap\n');
  
  console.log('🚀 Immediate (Next 1 Week):');
  if (roadmap.immediate.length === 0) {
    console.log('   No immediate focuses');
  } else {
    roadmap.immediate.forEach(item => {
      console.log(`   • ${item.focus} (${item.estimated_completion})`);
    });
  }
  
  console.log('\n📋 Short Term (1-2 Weeks):');
  if (roadmap.short_term.length === 0) {
    console.log('   No short-term focuses');
  } else {
    roadmap.short_term.forEach(item => {
      console.log(`   • ${item.focus} (${item.estimated_completion})`);
    });
  }
  
  console.log('\n🎯 Medium Term (2-4 Weeks):');
  if (roadmap.medium_term.length === 0) {
    console.log('   No medium-term focuses');
  } else {
    roadmap.medium_term.forEach(item => {
      console.log(`   • ${item.focus} (${item.estimated_completion})`);
    });
  }
  
  console.log('\n🔮 Long Term (4+ Weeks):');
  if (roadmap.long_term.length === 0) {
    console.log('   No long-term focuses');
  } else {
    roadmap.long_term.forEach(item => {
      console.log(`   • ${item.focus} (${item.estimated_completion})`);
    });
  }
}

/**
 * Main command handler
 */
function main() {
  const command = process.argv[2] || 'velocity';
  
  switch (command) {
    case 'velocity':
      showVelocity();
      break;
    case 'timeline':
      showTimeline();
      break;
    case 'bottlenecks':
      showBottlenecks();
      break;
    case 'roadmap':
      showRoadmap();
      break;
    default:
      console.log('Usage: node predictive-planner.mjs [velocity|timeline|bottlenecks|roadmap]');
      console.log('  velocity    - Calculate project velocity metrics');
      console.log('  timeline    - Generate predictive focus timeline');
      console.log('  bottlenecks - Identify potential bottlenecks');
      console.log('  roadmap     - Generate strategic roadmap');
      process.exit(1);
  }
}

main();
