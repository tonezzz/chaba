#!/usr/bin/env node

/**
 * SSOT Integration for Strategic Focus Automation
 * Integrates automation system with SSOT focus validation and management
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';

const FOCUS_FILE = join(process.cwd(), 'docs/ssot/ssot.focus.yml');
const VALIDATION_SCRIPT = join(process.cwd(), 'scripts/validate-focus.mjs');

/**
 * Run SSOT focus validation
 */
function runValidation() {
  console.log('🎯 Running SSOT Focus Validation\n');
  
  try {
    const output = execSync(`node ${VALIDATION_SCRIPT}`, { encoding: 'utf8' });
    console.log(output);
    return { success: true, output };
  } catch (error) {
    console.error(`❌ Validation failed: ${error.message}`);
    return { success: false, error: error.message };
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
 * Update focus status
 */
function updateFocusStatus(focusLabel, newStatus, section) {
  console.log(`🎯 Updating focus status: ${focusLabel} -> ${newStatus}\n`);
  
  if (!existsSync(FOCUS_FILE)) {
    console.log('❌ No focus file found.');
    return false;
  }
  
  try {
    const content = readFileSync(FOCUS_FILE, 'utf8');
    const lines = content.split('\n');
    
    let currentSection = null;
    let currentItem = null;
    let inDependencies = false;
    let focusFound = false;
    let statusLineIndex = -1;
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();
      const indent = line.search(/\S|$/);
      
      // Section headers
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
      
      // Parse item labels
      if (currentSection && indent === 6 && trimmed.startsWith('- label:')) {
        currentItem = trimmed.substring(9).trim();
        inDependencies = false;
        
        // Check if this is the focus we want to update
        if (currentItem === focusLabel && currentSection === section) {
          focusFound = true;
        }
        continue;
      }
      
      // Parse status
      if (focusFound && currentSection && indent === 8 && trimmed.startsWith('status:')) {
        statusLineIndex = i;
        lines[i] = line.replace(/status:.*/, `status: ${newStatus}`);
        focusFound = false;
        break;
      }
    }
    
    if (statusLineIndex === -1) {
      console.log(`❌ Focus not found: ${focusLabel} in section ${section}`);
      return false;
    }
    
    // Write updated content
    writeFileSync(FOCUS_FILE, lines.join('\n'));
    console.log(`✅ Focus status updated successfully`);
    
    // Run validation after update
    console.log('\n🔍 Validating updated focus file...');
    const validation = runValidation();
    
    return validation.success;
  } catch (error) {
    console.error(`Error updating focus status: ${error.message}`);
    return false;
  }
}

/**
 * Activate focus
 */
function activateFocus(focusLabel, section) {
  console.log(`🎯 Activating focus: ${focusLabel}\n`);
  
  const focusData = loadFocusData();
  if (!focusData) return false;
  
  const allFocuses = [...focusData.shared, ...focusData.branch];
  const focus = allFocuses.find(f => f.label === focusLabel);
  
  if (!focus) {
    console.log(`❌ Focus not found: ${focusLabel}`);
    return false;
  }
  
  // Check dependencies
  if (focus.dependencies && focus.dependencies.length > 0) {
    const unsatisfiedDeps = focus.dependencies.filter(dep => {
      const depFocus = allFocuses.find(f => f.label === dep);
      return !depFocus || depFocus.status !== 'completed';
    });
    
    if (unsatisfiedDeps.length > 0) {
      console.log(`⚠️  Cannot activate focus - unsatisfied dependencies:`);
      unsatisfiedDeps.forEach(dep => {
        console.log(`   - ${dep}`);
      });
      return false;
    }
  }
  
  // Deactivate current active focus in same section
  const currentActive = section === 'shared' ? 
    focusData.shared.find(f => f.status === 'active') :
    focusData.branch.find(f => f.status === 'active');
  
  if (currentActive && currentActive.label !== focusLabel) {
    console.log(`🔄 Deactivating current focus: ${currentActive.label}`);
    updateFocusStatus(currentActive.label, 'pending', section);
  }
  
  // Activate the new focus
  return updateFocusStatus(focusLabel, 'active', section);
}

/**
 * Complete focus
 */
function completeFocus(focusLabel, section) {
  console.log(`🎯 Completing focus: ${focusLabel}\n`);
  
  const result = updateFocusStatus(focusLabel, 'completed', section);
  
  if (result) {
    console.log(`✅ Focus marked as completed`);
    console.log(`💡 Check for dependent focuses that can now be activated`);
  }
  
  return result;
}

/**
 * Show integration status
 */
function showIntegrationStatus() {
  console.log('🎯 SSOT Integration Status\n');
  
  // Check if files exist
  console.log('📁 File Status:');
  console.log(`   Focus File: ${existsSync(FOCUS_FILE) ? '✅' : '❌'} ${FOCUS_FILE}`);
  console.log(`   Validation Script: ${existsSync(VALIDATION_SCRIPT) ? '✅' : '❌'} ${VALIDATION_SCRIPT}`);
  
  // Load current focus data
  const focusData = loadFocusData();
  if (focusData) {
    console.log('\n📊 Current Focus Status:');
    const activeShared = focusData.shared.filter(f => f.status === 'active');
    const activeBranch = focusData.branch.filter(f => f.status === 'active');
    
    console.log(`   Shared Active: ${activeShared.map(f => f.label).join(', ') || 'None'}`);
    console.log(`   Branch Active: ${activeBranch.map(f => f.label).join(', ') || 'None'}`);
    
    const totalShared = focusData.shared.length;
    const totalBranch = focusData.branch.length;
    const completedShared = focusData.shared.filter(f => f.status === 'completed').length;
    const completedBranch = focusData.branch.filter(f => f.status === 'completed').length;
    
    console.log(`\n   Progress: Shared ${completedShared}/${totalShared}, Branch ${completedBranch}/${totalBranch}`);
  }
  
  // Run validation
  console.log('\n🔍 Running validation...');
  const validation = runValidation();
  
  return validation.success;
}

/**
 * Sync automation data with SSOT
 */
function syncWithSSOT() {
  console.log('🎯 Syncing Automation Data with SSOT\n');
  
  const focusData = loadFocusData();
  if (!focusData) return false;
  
  // Load activity database
  const activityDB = loadActivityDB();
  if (!activityDB) {
    console.log('⚠️  No activity database found - automation data may be incomplete');
    return true;
  }
  
  // Update focus patterns based on activity
  const allFocuses = [...focusData.shared, ...focusData.branch];
  
  allFocuses.forEach(focus => {
    const focusActivities = activityDB.activities.filter(a => 
      a.focus_area === focus.label || 
      a.details?.focus_context === focus.label
    );
    
    if (focusActivities.length > 0) {
      console.log(`📊 ${focus.label}: ${focusActivities.length} activities recorded`);
    }
  });
  
  console.log('\n✅ Sync completed');
  return true;
}

/**
 * Load activity database
 */
function loadActivityDB() {
  const ACTIVITY_DB = join(process.cwd(), 'data/focus-activity.json');
  if (!existsSync(ACTIVITY_DB)) {
    return null;
  }
  
  try {
    const content = readFileSync(ACTIVITY_DB, 'utf8');
    return JSON.parse(content);
  } catch (error) {
    return null;
  }
}

/**
 * Main command handler
 */
function main() {
  const command = process.argv[2] || 'status';
  
  switch (command) {
    case 'status':
      showIntegrationStatus();
      break;
    case 'validate':
      runValidation();
      break;
    case 'activate':
      const focusLabel = process.argv[3];
      const section = process.argv[4];
      if (!focusLabel || !section) {
        console.log('Usage: node ssot-integrator.mjs activate <focus-label> <shared|branch>');
        process.exit(1);
      }
      activateFocus(focusLabel, section);
      break;
    case 'complete':
      const completeLabel = process.argv[3];
      const completeSection = process.argv[4];
      if (!completeLabel || !completeSection) {
        console.log('Usage: node ssot-integrator.mjs complete <focus-label> <shared|branch>');
        process.exit(1);
      }
      completeFocus(completeLabel, completeSection);
      break;
    case 'sync':
      syncWithSSOT();
      break;
    default:
      console.log('Usage: node ssot-integrator.mjs [status|validate|activate|complete|sync]');
      console.log('  status   - Show SSOT integration status');
      console.log('  validate - Run SSOT focus validation');
      console.log('  activate  - Activate a focus (deactivates current in section)');
      console.log('  complete - Mark a focus as completed');
      console.log('  sync     - Sync automation data with SSOT');
      process.exit(1);
  }
}

main();
