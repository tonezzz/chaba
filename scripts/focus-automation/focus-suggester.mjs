#!/usr/bin/env node

/**
 * Focus Suggestion Engine
 * Analyzes activity patterns and suggests strategic focus changes based on behavior
 */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const ACTIVITY_DB = join(process.cwd(), 'data/focus-activity.json');
const FOCUS_FILE = join(process.cwd(), 'docs/ssot/ssot.focus.yml');

// Configuration
const CONFIG = {
  min_confidence: 0.6,
  max_suggestions: 3,
  activity_window_hours: 24,
  pattern_threshold: 0.3
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
 * Get recent activities within time window
 */
function getRecentActivities(db, hours = CONFIG.activity_window_hours) {
  const cutoff = new Date(Date.now() - hours * 60 * 60 * 1000);
  return db.activities.filter(a => new Date(a.timestamp) > cutoff);
}

/**
 * Calculate focus affinity based on activity patterns
 */
function calculateFocusAffinity(activities, focusName) {
  let affinityScore = 0;
  let evidence = {
    matching_activities: 0,
    total_activities: activities.length,
    project_matches: 0,
    branch_matches: 0
  };
  
  // Simple keyword matching for focus affinity
  const focusKeywords = focusName.toLowerCase().split(/[\s-]+/);
  
  activities.forEach(activity => {
    const activityText = `${activity.project} ${activity.branch} ${activity.focus_area || ''} ${JSON.stringify(activity.details)}`.toLowerCase();
    
    // Check for keyword matches
    const keywordMatches = focusKeywords.filter(keyword => activityText.includes(keyword));
    if (keywordMatches.length > 0) {
      affinityScore += (keywordMatches.length / focusKeywords.length) * 0.3;
      evidence.matching_activities++;
    }
    
    // Project/branch matching
    if (activity.project && focusName.toLowerCase().includes(activity.project.toLowerCase())) {
      affinityScore += 0.2;
      evidence.project_matches++;
    }
    
    if (activity.branch && focusName.toLowerCase().includes(activity.branch.toLowerCase())) {
      affinityScore += 0.2;
      evidence.branch_matches++;
    }
  });
  
  // Normalize score
  affinityScore = Math.min(affinityScore / evidence.total_activities, 1);
  
  return {
    score: affinityScore,
    evidence
  };
}

/**
 * Check dependency status for a focus
 */
function checkDependencyStatus(focus, allFocuses) {
  if (!focus.dependencies || focus.dependencies.length === 0) {
    return {
      ready: true,
      missing_dependencies: [],
      blocking_focuses: []
    };
  }
  
  const missing_dependencies = [];
  const blocking_focuses = [];
  
  focus.dependencies.forEach(dep => {
    const depFocus = allFocuses.find(f => f.label === dep);
    if (!depFocus) {
      missing_dependencies.push(dep);
    } else if (depFocus.status !== 'completed') {
      blocking_focuses.push({
        name: dep,
        status: depFocus.status
      });
    }
  });
  
  return {
    ready: missing_dependencies.length === 0 && blocking_focuses.length === 0,
    missing_dependencies,
    blocking_focuses
  };
}

/**
 * Calculate priority alignment score
 */
function calculatePriorityAlignment(focus) {
  const priorityScores = {
    high: 1.0,
    medium: 0.6,
    low: 0.3
  };
  
  return priorityScores[focus.priority] || 0.5;
}

/**
 * Generate focus suggestions
 */
function generateSuggestions() {
  console.log('🎯 Generating Focus Suggestions\n');
  
  const db = loadActivityDB();
  if (!db) return;
  
  const focusData = loadFocusData();
  if (!focusData) return;
  
  const recentActivities = getRecentActivities(db);
  console.log(`📊 Analyzing ${recentActivities.length} recent activities (${CONFIG.activity_window_hours}h)\n`);
  
  const allFocuses = [...focusData.shared, ...focusData.branch];
  const suggestions = [];
  
  // Generate suggestions for each non-active focus
  allFocuses.forEach(focus => {
    if (focus.status === 'active') return; // Skip active focuses
    
    const affinity = calculateFocusAffinity(recentActivities, focus.label);
    const dependencyStatus = checkDependencyStatus(focus, allFocuses);
    const priorityAlignment = calculatePriorityAlignment(focus);
    
    // Calculate overall confidence
    let confidence = (affinity.score * 0.4) + (priorityAlignment * 0.4);
    if (dependencyStatus.ready) {
      confidence += 0.2;
    } else {
      confidence *= 0.5; // Penalize if dependencies not ready
    }
    
    if (confidence >= CONFIG.min_confidence) {
      const reasons = [];
      
      if (affinity.score > CONFIG.pattern_threshold) {
        reasons.push(`Activity pattern match (${(affinity.score * 100).toFixed(0)}% affinity)`);
      }
      
      if (priorityAlignment > 0.7) {
        reasons.push(`High strategic priority (${focus.priority})`);
      }
      
      if (dependencyStatus.ready) {
        reasons.push('Dependencies satisfied');
      } else {
        reasons.push(`Dependencies pending: ${dependencyStatus.blocking_focuses.map(b => b.name).join(', ')}`);
      }
      
      suggestions.push({
        suggested_focus: focus.label,
        confidence: confidence,
        reasons: reasons,
        activity_evidence: affinity.evidence,
        dependency_status: dependencyStatus,
        priority_alignment: priorityAlignment,
        current_status: focus.status
      });
    }
  });
  
  // Sort by confidence
  suggestions.sort((a, b) => b.confidence - a.confidence);
  
  // Limit to max suggestions
  const topSuggestions = suggestions.slice(0, CONFIG.max_suggestions);
  
  if (topSuggestions.length === 0) {
    console.log('ℹ️  No focus suggestions meet confidence threshold');
    console.log(`   Current activity patterns don't strongly suggest focus changes`);
    return;
  }
  
  console.log(`🎯 Top ${topSuggestions.length} Focus Suggestions:\n`);
  
  topSuggestions.forEach((suggestion, index) => {
    console.log(`${index + 1}. ${suggestion.suggested_focus}`);
    console.log(`   Confidence: ${(suggestion.confidence * 100).toFixed(0)}%`);
    console.log(`   Current Status: ${suggestion.current_status}`);
    console.log(`   Priority Alignment: ${(suggestion.priority_alignment * 100).toFixed(0)}%`);
    console.log(`   Reasons:`);
    suggestion.reasons.forEach(reason => {
      console.log(`   • ${reason}`);
    });
    
    if (suggestion.dependency_status.blocking_focuses.length > 0) {
      console.log(`   ⚠️  Blocked by:`);
      suggestion.dependency_status.blocking_focuses.forEach(blocker => {
        console.log(`     - ${blocker.name} (${blocker.status})`);
      });
    }
    
    console.log();
  });
  
  console.log(`💡 To activate a suggested focus, update docs/ssot/ssot.focus.yml`);
}

/**
 * Show focus affinity analysis
 */
function showAffinity() {
  console.log('🎯 Focus Affinity Analysis\n');
  
  const db = loadActivityDB();
  if (!db) return;
  
  const focusData = loadFocusData();
  if (!focusData) return;
  
  const recentActivities = getRecentActivities(db);
  const allFocuses = [...focusData.shared, ...focusData.branch];
  
  console.log(`📊 Based on ${recentActivities.length} recent activities:\n`);
  
  allFocuses.forEach(focus => {
    const affinity = calculateFocusAffinity(recentActivities, focus.label);
    console.log(`${focus.label}`);
    console.log(`   Affinity: ${(affinity.score * 100).toFixed(0)}%`);
    console.log(`   Evidence: ${affinity.evidence.matching_activities}/${affinity.evidence.total_activities} matching activities`);
    console.log(`   Status: ${focus.status}`);
    console.log();
  });
}

/**
 * Show activity patterns
 */
function showPatterns() {
  console.log('🎯 Activity Pattern Analysis\n');
  
  const db = loadActivityDB();
  if (!db) return;
  
  const recentActivities = getRecentActivities(db, 168); // 7 days
  
  // Activity by type
  const byType = {};
  recentActivities.forEach(a => {
    byType[a.activity_type] = (byType[a.activity_type] || 0) + 1;
  });
  
  console.log('📈 Activity by Type (7 days):');
  Object.entries(byType).forEach(([type, count]) => {
    console.log(`   ${type}: ${count}`);
  });
  
  // Activity by project
  const byProject = {};
  recentActivities.forEach(a => {
    byProject[a.project] = (byProject[a.project] || 0) + 1;
  });
  
  console.log('\n📁 Activity by Project:');
  Object.entries(byProject).forEach(([project, count]) => {
    console.log(`   ${project}: ${count}`);
  });
  
  // Activity by focus area
  const byFocus = {};
  recentActivities.forEach(a => {
    if (a.focus_area) {
      byFocus[a.focus_area] = (byFocus[a.focus_area] || 0) + 1;
    }
  });
  
  console.log('\n🎯 Activity by Focus Area:');
  Object.entries(byFocus).forEach(([focus, count]) => {
    console.log(`   ${focus}: ${count}`);
  });
  
  // Temporal patterns
  const byHour = {};
  recentActivities.forEach(a => {
    const hour = new Date(a.timestamp).getHours();
    byHour[hour] = (byHour[hour] || 0) + 1;
  });
  
  console.log('\n⏰ Activity by Hour:');
  Object.entries(byHour)
    .sort(([a], [b]) => a - b)
    .forEach(([hour, count]) => {
      console.log(`   ${hour}:00 - ${count} activities`);
    });
}

/**
 * Main command handler
 */
function main() {
  const command = process.argv[2] || 'generate';
  
  switch (command) {
    case 'generate':
      generateSuggestions();
      break;
    case 'affinity':
      showAffinity();
      break;
    case 'patterns':
      showPatterns();
      break;
    default:
      console.log('Usage: node focus-suggester.mjs [generate|affinity|patterns]');
      console.log('  generate - Generate focus suggestions based on recent activity');
      console.log('  affinity - Show focus affinity scores for all focuses');
      console.log('  patterns - Show activity pattern analysis');
      process.exit(1);
  }
}

main();
