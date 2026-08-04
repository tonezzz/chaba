#!/usr/bin/env node

import { readFileSync, existsSync } from 'fs';

const SSOT_PATH = '/home/tony/CascadeProjects/chaba/docs/overview/ssot.improvements.yml';

// Parse command line arguments
const args = process.argv.slice(2);
const mode = args[0] || 'analyze'; // analyze, score, prioritize

console.log(`Running impact scoring in ${mode} mode...\n`);

// Load SSOT file
if (!existsSync(SSOT_PATH)) {
  console.error('SSOT improvements file not found');
  process.exit(1);
}

const ssotContent = readFileSync(SSOT_PATH, 'utf8');

// Parse improvements
const improvements = parseImprovements(ssotContent);

console.log(`Found ${improvements.length} improvements\n`);

switch (mode) {
  case 'analyze':
    analyzeImpactScores(improvements);
    break;
  case 'score':
    calculateImpactScores(improvements);
    break;
  case 'prioritize':
    prioritizeByImpact(improvements);
    break;
  default:
    console.log('Available modes: analyze, score, prioritize');
    process.exit(1);
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
        business_impact: 5,
        technical_impact: 5,
        user_experience_impact: 5,
        cost_savings_impact: 5,
        priority: 'medium',
        status: 'pending',
        category: 'general',
        effort: 'TBD'
      };
    } else if (currentImprovement) {
      if (line.startsWith('business_impact:')) {
        currentImprovement.business_impact = parseInt(line.split('business_impact:')[1].trim()) || 5;
      } else if (line.startsWith('technical_impact:')) {
        currentImprovement.technical_impact = parseInt(line.split('technical_impact:')[1].trim()) || 5;
      } else if (line.startsWith('user_experience_impact:')) {
        currentImprovement.user_experience_impact = parseInt(line.split('user_experience_impact:')[1].trim()) || 5;
      } else if (line.startsWith('cost_savings_impact:')) {
        currentImprovement.cost_savings_impact = parseInt(line.split('cost_savings_impact:')[1].trim()) || 5;
      } else if (line.startsWith('impact_summary:')) {
        currentImprovement.impact_summary = line.split('impact_summary:')[1].trim();
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
          business_impact: 5,
          technical_impact: 5,
          user_experience_impact: 5,
          cost_savings_impact: 5,
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

function calculateOverallImpact(improvement) {
  // Weighted average: business 30%, technical 30%, user experience 20%, cost savings 20%
  const weights = {
    business: 0.3,
    technical: 0.3,
    user_experience: 0.2,
    cost_savings: 0.2
  };
  
  const overall = (
    (improvement.business_impact * weights.business) +
    (improvement.technical_impact * weights.technical) +
    (improvement.user_experience_impact * weights.user_experience) +
    (improvement.cost_savings_impact * weights.cost_savings)
  );
  
  return Math.round(overall);
}

function analyzeImpactScores(improvements) {
  console.log('=== Impact Score Analysis ===\n');
  
  const byStatus = {
    'pending': improvements.filter(imp => imp.status === 'pending'),
    'planned': improvements.filter(imp => imp.status === 'planned'),
    'completed': improvements.filter(imp => imp.status === 'completed')
  };
  
  // Analyze pending improvements
  if (byStatus.pending.length > 0) {
    console.log('## Pending Improvements Impact Analysis\n');
    
    byStatus.pending.forEach(imp => {
      const overall = calculateOverallImpact(imp);
      console.log(`**${imp.label}** (${imp.priority})`);
      console.log(`  Business: ${imp.business_impact}/10`);
      console.log(`  Technical: ${imp.technical_impact}/10`);
      console.log(`  User Experience: ${imp.user_experience_impact}/10`);
      console.log(`  Cost Savings: ${imp.cost_savings_impact}/10`);
      console.log(`  **Overall Impact: ${overall}/10**`);
      
      if (imp.impact_summary) {
        console.log(`  Summary: ${imp.impact_summary}`);
      }
      console.log();
    });
  }
  
  // Show impact distribution
  console.log('## Impact Distribution\n');
  
  const highImpact = improvements.filter(imp => calculateOverallImpact(imp) >= 8);
  const mediumImpact = improvements.filter(imp => calculateOverallImpact(imp) >= 5 && calculateOverallImpact(imp) < 8);
  const lowImpact = improvements.filter(imp => calculateOverallImpact(imp) < 5);
  
  console.log(`High Impact (≥8): ${highImpact.length}`);
  console.log(`Medium Impact (5-7): ${mediumImpact.length}`);
  console.log(`Low Impact (<5): ${lowImpact.length}`);
  
  // Show category impact averages
  console.log('\n## Average Impact by Category\n');
  
  const byCategory = {};
  improvements.forEach(imp => {
    if (!byCategory[imp.category]) {
      byCategory[imp.category] = [];
    }
    byCategory[imp.category].push(calculateOverallImpact(imp));
  });
  
  Object.entries(byCategory).forEach(([category, scores]) => {
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    console.log(`${category}: ${avg.toFixed(1)}/10 (${scores.length} improvements)`);
  });
}

function calculateImpactScores(improvements) {
  console.log('=== Calculating Impact Scores ===\n');
  
  let scoredCount = 0;
  
  improvements.forEach(imp => {
    if (imp.status === 'pending' || imp.status === 'planned') {
      const overall = calculateOverallImpact(imp);
      
      console.log(`${imp.label}: ${overall}/10`);
      
      // Suggest priority based on impact
      const suggestedPriority = overall >= 8 ? 'high' : overall >= 5 ? 'medium' : 'low';
      
      if (suggestedPriority !== imp.priority) {
        console.log(`  → Suggested priority: ${suggestedPriority} (current: ${imp.priority})`);
      }
      
      scoredCount++;
    }
  });
  
  console.log(`\nScored ${scoredCount} improvements`);
}

function prioritizeByImpact(improvements) {
  console.log('=== Impact-Based Prioritization ===\n');
  
  // Calculate overall impact for all pending improvements
  const withImpact = improvements.map(imp => ({
    ...imp,
    overall_impact: calculateOverallImpact(imp)
  }));
  
  // Filter pending improvements and sort by impact
  const pending = withImpact
    .filter(imp => imp.status === 'pending')
    .sort((a, b) => b.overall_impact - a.overall_impact);
  
  console.log('## Priority Order by Impact Score\n');
  
  pending.forEach((imp, index) => {
    const priorityLabel = imp.overall_impact >= 8 ? '🔴 HIGH' : 
                         imp.overall_impact >= 5 ? '🟡 MEDIUM' : '🟢 LOW';
    console.log(`${index + 1}. ${priorityLabel} ${imp.overall_impact}/10 - ${imp.label}`);
    console.log(`   Business: ${imp.business_impact}, Technical: ${imp.technical_impact}, UX: ${imp.user_experience_impact}, Cost: ${imp.cost_savings_impact}`);
    console.log(`   Current priority: ${imp.priority}, Effort: ${imp.effort}`);
    console.log();
  });
  
  // Show impact vs priority comparison
  console.log('## Impact vs Manual Priority Comparison\n');
  
  const priorityMismatch = pending.filter(imp => {
    const suggestedPriority = imp.overall_impact >= 8 ? 'high' : imp.overall_impact >= 5 ? 'medium' : 'low';
    return suggestedPriority !== imp.priority;
  });
  
  if (priorityMismatch.length > 0) {
    console.log('Priority Mismatches (impact vs manual):\n');
    
    priorityMismatch.forEach(imp => {
      const suggestedPriority = imp.overall_impact >= 8 ? 'high' : imp.overall_impact >= 5 ? 'medium' : 'low';
      console.log(`- ${imp.label}: manual=${imp.priority}, impact-based=${suggestedPriority} (${imp.overall_impact}/10)`);
    });
  } else {
    console.log('✅ No priority mismatches - manual priorities align with impact scores');
  }
}