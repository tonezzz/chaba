#!/usr/bin/env node

import { readFileSync, existsSync } from 'fs';

const SSOT_PATH = '/home/tony/CascadeProjects/chaba/docs/overview/ssot.improvements.yml';

console.log('Analyzing dependency resolution suggestions...\n');

// Load SSOT file
if (!existsSync(SSOT_PATH)) {
  console.error('SSOT improvements file not found');
  process.exit(1);
}

const ssotContent = readFileSync(SSOT_PATH, 'utf8');

// Parse improvements
const improvements = parseImprovements(ssotContent);

console.log(`Found ${improvements.length} improvements\n`);

// Generate suggestions
const suggestions = generateSuggestions(improvements);

// Display suggestions
if (suggestions.readyToStart.length > 0) {
  console.log('=== 🚀 Ready to Start (Dependencies Met) ===\n');
  suggestions.readyToStart.forEach(imp => {
    console.log(`✅ ${imp.label} (${imp.priority})`);
    console.log(`   Category: ${imp.category || 'general'}`);
    console.log(`   Effort: ${imp.effort || 'TBD'}`);
    console.log(`   Suggested action: Start implementation\n`);
  });
}

if (suggestions.blocked.length > 0) {
  console.log('\n=== 🔒 Blocked (Dependencies Not Met) ===\n');
  suggestions.blocked.forEach(imp => {
    console.log(`🔒 ${imp.label} (${imp.priority})`);
    console.log(`   Blocked by: ${imp.blockedBy.join(', ')}`);
    console.log(`   Suggested action: Complete dependencies first\n`);
  });
}

if (suggestions.missingDependencies.length > 0) {
  console.log('\n=== 💡 Suggested Dependencies to Add ===\n');
  suggestions.missingDependencies.forEach(suggestion => {
    console.log(`💡 ${suggestion.improvement} should depend on ${suggestion.suggestedDependency}`);
    console.log(`   Reason: ${suggestion.reason}\n`);
  });
}

if (suggestions.priorityConflicts.length > 0) {
  console.log('\n=== ⚠️ Priority Conflicts ===\n');
  suggestions.priorityConflicts.forEach(conflict => {
    console.log(`⚠️ ${conflict.improvement} (${conflict.currentPriority}) depends on ${conflict.dependency} (${conflict.depPriority})`);
    console.log(`   Suggested action: Consider adjusting priorities\n`);
  });
}

if (suggestions.orphanImprovements.length > 0) {
  console.log('\n=== 🔄 Orphan Improvements (No Dependencies/Dependents) ===\n');
  suggestions.orphanImprovements.forEach(imp => {
    console.log(`🔄 ${imp.label} (${imp.priority})`);
    console.log(`   Suggested action: Consider if this should depend on or block other improvements\n`);
  });
}

// Summary
console.log('\n=== 📊 Summary ===\n');
console.log(`Ready to start: ${suggestions.readyToStart.length}`);
console.log(`Blocked: ${suggestions.blocked.length}`);
console.log(`Suggested dependencies: ${suggestions.missingDependencies.length}`);
console.log(`Priority conflicts: ${suggestions.priorityConflicts.length}`);
console.log(`Orphan improvements: ${suggestions.orphanImprovements.length}`);

if (suggestions.readyToStart.length > 0) {
  console.log('\n=== 🎯 Recommended Next Actions ===\n');
  suggestions.readyToStart.slice(0, 3).forEach(imp => {
    console.log(`1. Start: ${imp.label} (${imp.effort || 'TBD'})`);
  });
}

function parseImprovements(ssotContent) {
  const improvements = [];
  const lines = ssotContent.split('\n');
  let currentImprovement = null;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    
    if (line.startsWith('- label:')) {
      if (currentImprovement) {
        improvements.push(currentImprovement);
      }
      currentImprovement = { 
        label: line.split('label:')[1].trim(),
        depends_on: [],
        blocks: [],
        priority: 'medium',
        status: 'pending',
        category: 'general',
        effort: 'TBD'
      };
    } else if (currentImprovement) {
      if (line.startsWith('depends_on:')) {
        const deps = line.split('depends_on:')[1].trim();
        if (deps.startsWith('[') && deps.endsWith(']')) {
          currentImprovement.depends_on = deps.slice(1, -1).split(',').map(d => d.trim()).filter(d => d);
        } else if (deps) {
          currentImprovement.depends_on = [deps];
        }
      } else if (line.startsWith('blocks:')) {
        const blocks = line.split('blocks:')[1].trim();
        if (blocks.startsWith('[') && blocks.endsWith(']')) {
          currentImprovement.blocks = blocks.slice(1, -1).split(',').map(d => d.trim()).filter(d => d);
        } else if (blocks) {
          currentImprovement.blocks = [blocks];
        }
      } else if (line.startsWith('priority:')) {
        currentImprovement.priority = line.split('priority:')[1].trim();
      } else if (line.startsWith('status:')) {
        currentImprovement.status = line.split('status:')[1].trim();
      } else if (line.startsWith('category:')) {
        currentImprovement.category = line.split('category:')[1].trim();
      } else if (line.startsWith('effort:')) {
        currentImprovement.effort = line.split('effort:')[1].trim();
      } else if (line.startsWith('- label:') && currentImprovement.label) {
        improvements.push(currentImprovement);
        currentImprovement = { 
          label: line.split('label:')[1].trim(),
          depends_on: [],
          blocks: [],
          priority: 'medium',
          status: 'pending',
          category: 'general',
          effort: 'TBD'
        };
      }
    }
  }
  
  if (currentImprovement) {
    improvements.push(currentImprovement);
  }
  
  return improvements;
}

function generateSuggestions(improvements) {
  const suggestions = {
    readyToStart: [],
    blocked: [],
    missingDependencies: [],
    priorityConflicts: [],
    orphanImprovements: []
  };
  
  const improvementMap = new Map(improvements.map(imp => [imp.label, imp]));
  const priorityOrder = { 'high': 3, 'medium': 2, 'low': 1 };
  
  // Analyze each improvement
  for (const improvement of improvements) {
    // Skip completed improvements
    if (improvement.status === 'completed') continue;
    
    // Skip guide/documentation improvements
    if (improvement.label.includes('Guide') || improvement.label.includes('Rules') || 
        improvement.label.includes('Best Practices') || improvement.label.includes('Example')) {
      continue;
    }
    
    // Check if ready to start
    if (improvement.depends_on && improvement.depends_on.length > 0) {
      const incompleteDeps = improvement.depends_on.filter(dep => {
        const depImprovement = improvementMap.get(dep);
        return !depImprovement || depImprovement.status !== 'completed';
      });
      
      if (incompleteDeps.length === 0) {
        suggestions.readyToStart.push(improvement);
      } else {
        suggestions.blocked.push({
          label: improvement.label,
          priority: improvement.priority,
          blockedBy: incompleteDeps
        });
      }
    } else {
      suggestions.readyToStart.push(improvement);
    }
    
    // Check for priority conflicts
    if (improvement.depends_on && improvement.depends_on.length > 0) {
      for (const dep of improvement.depends_on) {
        const depImprovement = improvementMap.get(dep);
        if (depImprovement && depImprovement.priority) {
          const currentPriority = priorityOrder[improvement.priority] || 0;
          const depPriority = priorityOrder[depImprovement.priority] || 0;
          
          if (currentPriority > depPriority) {
            suggestions.priorityConflicts.push({
              improvement: improvement.label,
              currentPriority: improvement.priority,
              dependency: dep,
              depPriority: depImprovement.priority
            });
          }
        }
      }
    }
    
    // Check for orphan improvements (no dependencies and nothing depends on it)
    const hasDependencies = improvement.depends_on && improvement.depends_on.length > 0;
    const hasDependents = improvements.some(imp => 
      imp.depends_on && imp.depends_on.includes(improvement.label)
    );
    
    if (!hasDependencies && !hasDependents && improvement.status !== 'completed') {
      suggestions.orphanImprovements.push(improvement);
    }
  }
  
  // Suggest missing dependencies based on categories
  const categoryBasedSuggestions = suggestCategoryDependencies(improvements);
  suggestions.missingDependencies.push(...categoryBasedSuggestions);
  
  // Sort readyToStart by priority
  suggestions.readyToStart.sort((a, b) => {
    return priorityOrder[b.priority] - priorityOrder[a.priority];
  });
  
  return suggestions;
}

function suggestCategoryDependencies(improvements) {
  const suggestions = [];
  
  // Define logical category dependencies
  const categoryRules = [
    {
      category: 'gpu',
      shouldDependOn: ['performance'],
      reason: 'GPU work should be optimized after general performance analysis'
    },
    {
      category: 'monitoring',
      shouldDependOn: ['configuration'],
      reason: 'Monitoring systems require stable configuration'
    },
    {
      category: 'yomi',
      shouldDependOn: ['configuration'],
      reason: 'Yomi services depend on system configuration'
    },
    {
      category: 'performance',
      shouldDependOn: ['gpu'],
      reason: 'Performance analysis should include GPU metrics'
    }
  ];
  
  for (const improvement of improvements) {
    if (improvement.status === 'completed') continue;
    
    for (const rule of categoryRules) {
      if (improvement.category === rule.category) {
        // Find potential dependencies in the suggested category
        const potentialDeps = improvements.filter(imp => 
          imp.category === rule.shouldDependOn[0] && 
          imp.label !== improvement.label &&
          !improvement.depends_on.includes(imp.label)
        );
        
        if (potentialDeps.length > 0 && improvement.depends_on.length === 0) {
          suggestions.push({
            improvement: improvement.label,
            suggestedDependency: potentialDeps[0].label,
            reason: rule.reason
          });
        }
      }
    }
  }
  
  return suggestions;
}