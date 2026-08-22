#!/usr/bin/env node

/**
 * SSOT Focus Validation Script
 * Validates strategic focus management rules in ssot.focus.current.yml
 */

import { readFileSync, existsSync } from 'fs';
import { execSync } from 'child_process';
import { join } from 'path';

const FOCUS_FILE = join(process.cwd(), 'docs/ssot/ssot.focus.current.yml');

function parseSimpleYAML(content) {
  // Simple YAML parser for focus file structure
  const lines = content.split('\n');
  const result = {
    validation: {},
    sections: []
  };
  
  let inValidation = false;
  let inSections = false;
  let currentSection = null;
  let currentItem = null;
  let inDependencies = false;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const indent = line.search(/\S|$/);
    
    // Skip comments and empty lines
    if (trimmed.startsWith('#') || trimmed === '') continue;
    
    // Parse validation section
    if (trimmed === 'validation:') {
      inValidation = true;
      inSections = false;
      continue;
    }
    
    if (inValidation && indent === 0) {
      inValidation = false;
    }
    
    if (inValidation && indent > 0) {
      const colonIndex = trimmed.indexOf(':');
      if (colonIndex > 0) {
        const key = trimmed.substring(0, colonIndex).trim();
        const value = trimmed.substring(colonIndex + 1).trim();
        if (key && value) {
          if (value === 'true') result.validation[key] = true;
          else if (value === 'false') result.validation[key] = false;
          else if (!isNaN(value)) result.validation[key] = parseInt(value);
          else result.validation[key] = value;
        }
      }
      continue;
    }
    
    // Parse sections
    if (trimmed === 'sections:') {
      inSections = true;
      inValidation = false;
      continue;
    }
    
    if (inSections && indent === 0 && !trimmed.startsWith('-')) {
      inSections = false;
    }
    
    if (inSections) {
      // Parse section title
      if (indent === 2 && trimmed.startsWith('- title:')) {
        // Save previous section and item
        if (currentSection) {
          if (currentItem) {
            currentSection.items.push(currentItem);
            currentItem = null;
          }
          result.sections.push(currentSection);
        }
        
        const title = trimmed.substring(9).trim();
        currentSection = {
          title: title,
          icon: '',
          layout: '',
          items: []
        };
        currentItem = null;
        inDependencies = false;
        continue;
      }
      
      // Parse section properties (icon, layout)
      if (currentSection && !currentItem && indent === 4) {
        if (trimmed.startsWith('icon:')) {
          currentSection.icon = trimmed.substring(6).trim();
        } else if (trimmed.startsWith('layout:')) {
          currentSection.layout = trimmed.substring(7).trim();
        } else if (trimmed.startsWith('items:')) {
          // Start parsing items
          continue;
        }
        continue;
      }
      
      // Parse items
      if (currentSection && indent === 6 && trimmed.startsWith('- label:')) {
        // Save previous item
        if (currentItem) {
          currentSection.items.push(currentItem);
        }
        
        const label = trimmed.substring(9).trim();
        currentItem = {
          label: label,
          text: '',
          status: '',
          priority: '',
          tags: [],
          dependencies: []
        };
        inDependencies = false;
        continue;
      }
      
      // Parse item properties (at indent 8 in the actual file)
      if (currentItem && indent === 8) {
        inDependencies = false;
        if (trimmed.startsWith('text:')) {
          currentItem.text = trimmed.substring(6).trim();
        } else if (trimmed.startsWith('status:')) {
          currentItem.status = trimmed.substring(7).trim();
        } else if (trimmed.startsWith('priority:')) {
          currentItem.priority = trimmed.substring(9).trim();
        } else if (trimmed.startsWith('tags:')) {
          const tagsStr = trimmed.substring(6).trim();
          if (tagsStr.startsWith('[')) {
            currentItem.tags = tagsStr.slice(1, -1).split(',').map(t => t.trim().replace(/'/g, ''));
          }
        } else if (trimmed.startsWith('dependencies:')) {
          inDependencies = true;
        } else if (trimmed.startsWith('strategic_value:') || trimmed.startsWith('estimated_duration:') || 
                   trimmed.startsWith('projects:') || trimmed.startsWith('branch:')) {
          // Skip other fields we don't need for validation
          continue;
        }
        continue;
      }
      
      // Parse dependency items
      if (currentItem && inDependencies && indent === 10 && trimmed.startsWith('- ')) {
        currentItem.dependencies.push(trimmed.substring(2).trim());
        continue;
      }
    }
  }
  
  // Don't forget the last section and item
  if (currentSection) {
    if (currentItem) {
      currentSection.items.push(currentItem);
    }
    result.sections.push(currentSection);
  }
  
  
  return result;
}

function loadFocusData() {
  if (!existsSync(FOCUS_FILE)) {
    console.error(`❌ Focus file not found: ${FOCUS_FILE}`);
    process.exit(1);
  }

  try {
    const content = readFileSync(FOCUS_FILE, 'utf8');
    const output = execSync(
      'python3 -c "import yaml,json,sys; print(json.dumps(yaml.safe_load(sys.stdin)))"',
      { input: content, encoding: 'utf8' }
    );
    return JSON.parse(output);
  } catch (error) {
    console.error(`❌ Error parsing focus file: ${error.message}`);
    process.exit(1);
  }
}

function countActiveFocuses(items, statusFilter = 'active') {
  if (!items) return 0;
  return items.filter(item => item.status === statusFilter).length;
}

function extractFocusNames(items, statusFilter = 'active') {
  if (!items) return [];
  return items
    .filter(item => item.status === statusFilter)
    .map(item => item.label);
}

function validateFocusRules(data) {
  const errors = [];
  const warnings = [];
  
  if (!data.validation) {
    errors.push('Missing validation section in focus file');
    return { errors, warnings };
  }

  const rules = data.validation;
  const sections = data.sections || [];
  
  let sharedFocusSection = sections.find(s => s.title === 'Active Shared Focus');
  let branchFocusSection = sections.find(s => s.title === 'Active Branch Focus');
  
  if (!sharedFocusSection) {
    errors.push('Missing "Active Shared Focus" section');
  }
  
  if (!branchFocusSection) {
    errors.push('Missing "Active Branch Focus" section');
  }

  if (sharedFocusSection && branchFocusSection) {
    const sharedItems = sharedFocusSection.items || [];
    const branchItems = branchFocusSection.items || [];
    
    // Count active focuses
    const activeSharedCount = countActiveFocuses(sharedItems);
    const activeBranchCount = countActiveFocuses(branchItems);
    
    // Validate max active shared focus
    if (rules.max_active_shared_focus && activeSharedCount > rules.max_active_shared_focus) {
      errors.push(
        `Too many active shared focuses: ${activeSharedCount} active (max: ${rules.max_active_shared_focus})`
      );
      const activeShared = extractFocusNames(sharedItems);
      errors.push(`  Active shared focuses: ${activeShared.join(', ')}`);
    }
    
    // Validate max active branch focus
    if (rules.max_active_branch_focus && activeBranchCount > rules.max_active_branch_focus) {
      errors.push(
        `Too many active branch focuses: ${activeBranchCount} active (max: ${rules.max_active_branch_focus})`
      );
      const activeBranch = extractFocusNames(branchItems);
      errors.push(`  Active branch focuses: ${activeBranch.join(', ')}`);
    }
    
    // Validate focus overlap
    if (rules.allow_focus_overlap === false) {
      const sharedNames = extractFocusNames(sharedItems).map(n => n.toLowerCase());
      const branchNames = extractFocusNames(branchItems).map(n => n.toLowerCase());
      
      const overlaps = sharedNames.filter(name => branchNames.includes(name));
      if (overlaps.length > 0) {
        errors.push(`Focus overlap detected between shared and branch: ${overlaps.join(', ')}`);
      }
    }
    
    // Validate required priority
    if (rules.require_priority) {
      const allItems = [...sharedItems, ...branchItems];
      const missingPriority = allItems.filter(item => !item.priority);
      if (missingPriority.length > 0) {
        errors.push(`Missing priority field for: ${missingPriority.map(i => i.label).join(', ')}`);
      }
    }
    
    // Validate required tags
    if (rules.require_tags) {
      const allItems = [...sharedItems, ...branchItems];
      const missingTags = allItems.filter(item => !item.tags || item.tags.length === 0);
      if (missingTags.length > 0) {
        errors.push(`Missing tags field for: ${missingTags.map(i => i.label).join(', ')}`);
      }
    }
    
    // Validate dependencies exist
    const allItems = [...sharedItems, ...branchItems];
    const allLabels = allItems.map(i => i.label);
    
    allItems.forEach(item => {
      if (item.dependencies && Array.isArray(item.dependencies)) {
        item.dependencies.forEach(dep => {
          if (!allLabels.includes(dep)) {
            warnings.push(`Dependency "${dep}" not found in focus areas for "${item.label}"`);
          }
        });
      }
    });
    
    // Check for circular dependencies
    const buildDependencyGraph = (items) => {
      const graph = {};
      items.forEach(item => {
        graph[item.label] = item.dependencies || [];
      });
      return graph;
    };
    
    const detectCircular = (graph, node, visited = new Set(), recStack = new Set()) => {
      if (recStack.has(node)) return true;
      if (visited.has(node)) return false;
      
      visited.add(node);
      recStack.add(node);
      
      const neighbors = graph[node] || [];
      for (const neighbor of neighbors) {
        if (detectCircular(graph, neighbor, visited, recStack)) {
          return true;
        }
      }
      
      recStack.delete(node);
      return false;
    };
    
    const depGraph = buildDependencyGraph(allItems);
    for (const node of Object.keys(depGraph)) {
      if (detectCircular(depGraph, node)) {
        errors.push(`Circular dependency detected involving "${node}"`);
        break;
      }
    }
  }

  return { errors, warnings };
}

function main() {
  console.log('🎯 Validating Strategic Focus Management\n');
  
  const data = loadFocusData();
  const { errors, warnings } = validateFocusRules(data);
  
  if (errors.length === 0 && warnings.length === 0) {
    console.log('✅ All focus validation rules passed');
    console.log(`\n📊 Current Focus Status:`);
    
    const sections = data.sections || [];
    const sharedSection = sections.find(s => s.title === 'Active Shared Focus');
    const branchSection = sections.find(s => s.title === 'Active Branch Focus');
    
    if (sharedSection) {
      const activeShared = countActiveFocuses(sharedSection.items);
      const activeSharedNames = extractFocusNames(sharedSection.items);
      console.log(`   Shared: ${activeShared} active focus(es) - ${activeSharedNames.join(', ') || 'None'}`);
    }
    
    if (branchSection) {
      const activeBranch = countActiveFocuses(branchSection.items);
      const activeBranchNames = extractFocusNames(branchSection.items);
      console.log(`   Branch: ${activeBranch} active focus(es) - ${activeBranchNames.join(', ') || 'None'}`);
    }
    
    process.exit(0);
  }
  
  if (warnings.length > 0) {
    console.log('⚠️  Warnings:');
    warnings.forEach(warning => console.log(`   ${warning}`));
    console.log();
  }
  
  if (errors.length > 0) {
    console.log('❌ Validation errors:');
    errors.forEach(error => console.log(`   ${error}`));
    console.log();
    process.exit(1);
  }
}

main();
