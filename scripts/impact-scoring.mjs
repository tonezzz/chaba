#!/usr/bin/env node

import { readFileSync, existsSync } from 'fs';

const SSOT_PATH = '/home/tony/CascadeProjects/chaba/docs/ssot/ssot.improvements.yml';

// Impact weights
const WEIGHTS = {
  business: 0.3,
  technical: 0.3,
  user_experience: 0.2,
  cost_savings: 0.2
};

// Priority thresholds
const PRIORITY_THRESHOLDS = {
  HIGH: 8,
  MEDIUM_LOW: 5
};

/**
 * Parse improvements from SSOT YAML content
 * Reference: overnight-assessment.mjs parseImprovements function
 */
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
        effort: 'TBD',
        business_impact: null,
        technical_impact: null,
        user_experience_impact: null,
        cost_savings_impact: null
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
      } else if (line.startsWith('business_impact:')) {
        const value = line.split('business_impact:')[1].trim();
        currentImprovement.business_impact = parseInt(value) || 5;
      } else if (line.startsWith('technical_impact:')) {
        const value = line.split('technical_impact:')[1].trim();
        currentImprovement.technical_impact = parseInt(value) || 5;
      } else if (line.startsWith('user_experience_impact:')) {
        const value = line.split('user_experience_impact:')[1].trim();
        currentImprovement.user_experience_impact = parseInt(value) || 5;
      } else if (line.startsWith('cost_savings_impact:')) {
        const value = line.split('cost_savings_impact:')[1].trim();
        currentImprovement.cost_savings_impact = parseInt(value) || 5;
      } else if (line.startsWith('impact_summary:')) {
        currentImprovement.impact_summary = line.split('impact_summary:')[1].trim();
      } else if (line.startsWith('- label:') && currentImprovement.label) {
        improvements.push(currentImprovement);
        currentImprovement = {
          label: line.split('label:')[1].trim(),
          depends_on: [],
          blocks: [],
          priority: 'medium',
          status: 'pending',
          category: 'general',
          effort: 'TBD',
          business_impact: null,
          technical_impact: null,
          user_experience_impact: null,
          cost_savings_impact: null
        };
      }
    }
  }

  if (currentImprovement) {
    improvements.push(currentImprovement);
  }

  return improvements;
}

/**
 * Calculate overall impact score using weighted average
 * Formula: (business * 0.3) + (technical * 0.3) + (user_experience * 0.2) + (cost_savings * 0.2)
 */
function calculateOverallImpact(improvement) {
  const business = improvement.business_impact !== null ? improvement.business_impact : 5;
  const technical = improvement.technical_impact !== null ? improvement.technical_impact : 5;
  const user_experience = improvement.user_experience_impact !== null ? improvement.user_experience_impact : 5;
  const cost_savings = improvement.cost_savings_impact !== null ? improvement.cost_savings_impact : 5;

  const overall = (
    (business * WEIGHTS.business) +
    (technical * WEIGHTS.technical) +
    (user_experience * WEIGHTS.user_experience) +
    (cost_savings * WEIGHTS.cost_savings)
  );

  return Math.round(overall * 10) / 10; // Round to 1 decimal place
}

export { parseImprovements, calculateOverallImpact };

/**
 * Determine priority based on impact score
 */
function getPriorityFromImpact(impact) {
  if (impact >= PRIORITY_THRESHOLDS.HIGH) return 'HIGH';
  if (impact >= PRIORITY_THRESHOLDS.MEDIUM_LOW) return 'MEDIUM';
  return 'LOW';
}

/**
 * Get impact category label
 */
function getImpactCategory(impact) {
  if (impact >= PRIORITY_THRESHOLDS.HIGH) return 'High';
  if (impact >= PRIORITY_THRESHOLDS.MEDIUM_LOW) return 'Medium';
  return 'Low';
}

/**
 * Analyze mode: Detailed impact analysis by category
 */
function analyzeMode(improvements) {
  console.log('\n📊 IMPACT ANALYSIS\n');

  // Calculate category averages
  const categorySums = {
    business: { total: 0, count: 0 },
    technical: { total: 0, count: 0 },
    user_experience: { total: 0, count: 0 },
    cost_savings: { total: 0, count: 0 }
  };

  const impactDistribution = {
    high: [],
    medium: [],
    low: []
  };

  improvements.forEach(imp => {
    const business = imp.business_impact !== null ? imp.business_impact : 5;
    const technical = imp.technical_impact !== null ? imp.technical_impact : 5;
    const user_experience = imp.user_experience_impact !== null ? imp.user_experience_impact : 5;
    const cost_savings = imp.cost_savings_impact !== null ? imp.cost_savings_impact : 5;

    categorySums.business.total += business;
    categorySums.business.count++;
    categorySums.technical.total += technical;
    categorySums.technical.count++;
    categorySums.user_experience.total += user_experience;
    categorySums.user_experience.count++;
    categorySums.cost_savings.total += cost_savings;
    categorySums.cost_savings.count++;

    const overall = calculateOverallImpact(imp);
    const category = getImpactCategory(overall).toLowerCase();
    impactDistribution[category].push({
      label: imp.label,
      overall: overall,
      business: business,
      technical: technical,
      user_experience: user_experience,
      cost_savings: cost_savings,
      summary: imp.impact_summary || 'No summary'
    });
  });

  // Display category averages
  console.log('📈 Category Impact Averages:\n');
  const categories = [
    { name: 'Business', key: 'business' },
    { name: 'Technical', key: 'technical' },
    { name: 'User Experience', key: 'user_experience' },
    { name: 'Cost Savings', key: 'cost_savings' }
  ];

  categories.forEach(cat => {
    const avg = categorySums[cat.key].count > 0
      ? (categorySums[cat.key].total / categorySums[cat.key].count).toFixed(1)
      : 'N/A';
    console.log(`  ${cat.name}: ${avg}/10`);
  });

  // Display impact distribution
  console.log('\n📊 Impact Distribution:\n');
  console.log(`  High (≥8): ${impactDistribution.high.length} improvements`);
  console.log(`  Medium (5-7): ${impactDistribution.medium.length} improvements`);
  console.log(`  Low (<5): ${impactDistribution.low.length} improvements`);

  // Display impact summaries for each improvement
  console.log('\n📋 Impact Summaries:\n');
  improvements.forEach(imp => {
    const overall = calculateOverallImpact(imp);
    const category = getImpactCategory(overall);
    const emoji = category === 'High' ? '🔴' : category === 'Medium' ? '🟡' : '🟢';
    const business = imp.business_impact !== null ? imp.business_impact : 5;
    const technical = imp.technical_impact !== null ? imp.technical_impact : 5;
    const user_experience = imp.user_experience_impact !== null ? imp.user_experience_impact : 5;
    const cost_savings = imp.cost_savings_impact !== null ? imp.cost_savings_impact : 5;

    console.log(`${emoji} ${category} ${overall}/10 - ${imp.label}`);
    console.log(`   Business: ${business}, Technical: ${technical}, ` +
                `UX: ${user_experience}, Cost: ${cost_savings}`);
    if (imp.impact_summary) {
      console.log(`   Summary: ${imp.impact_summary}`);
    }
    console.log('');
  });
}

/**
 * Score mode: Calculate impact scores and suggest priorities
 */
function scoreMode(improvements) {
  console.log('\n🎯 IMPACT SCORING\n');

  const scoredImprovements = improvements.map(imp => {
    const overall = calculateOverallImpact(imp);
    const suggestedPriority = getPriorityFromImpact(overall);
    const manualPriority = imp.priority.toUpperCase();
    const business = imp.business_impact !== null ? imp.business_impact : 5;
    const technical = imp.technical_impact !== null ? imp.technical_impact : 5;
    const user_experience = imp.user_experience_impact !== null ? imp.user_experience_impact : 5;
    const cost_savings = imp.cost_savings_impact !== null ? imp.cost_savings_impact : 5;

    return {
      label: imp.label,
      overall: overall,
      suggestedPriority: suggestedPriority,
      manualPriority: manualPriority,
      priorityMatch: suggestedPriority === manualPriority,
      business: business,
      technical: technical,
      user_experience: user_experience,
      cost_savings: cost_savings,
      status: imp.status,
      effort: imp.effort
    };
  });

  // Sort by overall impact (descending)
  scoredImprovements.sort((a, b) => b.overall - a.overall);

  // Display scored improvements
  console.log('📊 Impact Scores (sorted by overall impact):\n');
  scoredImprovements.forEach(imp => {
    const emoji = imp.priorityMatch ? '✅' : '⚠️';
    const priorityEmoji = imp.suggestedPriority === 'HIGH' ? '🔴' :
                         imp.suggestedPriority === 'MEDIUM' ? '🟡' : '🟢';

    console.log(`${emoji} ${priorityEmoji} ${imp.suggestedPriority} ${imp.overall}/10 - ${imp.label}`);
    console.log(`   Business: ${imp.business}, Technical: ${imp.technical}, ` +
                `UX: ${imp.user_experience}, Cost: ${imp.cost_savings}`);
    console.log(`   Manual priority: ${imp.manualPriority}, Status: ${imp.status}, Effort: ${imp.effort}`);
    console.log('');
  });

  // Identify priority mismatches
  const mismatches = scoredImprovements.filter(imp => !imp.priorityMatch);
  if (mismatches.length > 0) {
    console.log('⚠️ Priority Mismatches (manual vs impact-based):\n');
    mismatches.forEach(imp => {
      console.log(`  ${imp.label}`);
      console.log(`    Manual: ${imp.manualPriority} → Impact-based: ${imp.suggestedPriority} (${imp.overall}/10)`);
      console.log('');
    });
  } else {
    console.log('✅ No priority mismatches found\n');
  }

  // Summary statistics
  const highCount = scoredImprovements.filter(imp => imp.suggestedPriority === 'HIGH').length;
  const mediumCount = scoredImprovements.filter(imp => imp.suggestedPriority === 'MEDIUM').length;
  const lowCount = scoredImprovements.filter(imp => imp.suggestedPriority === 'LOW').length;

  console.log('📈 Priority Distribution:\n');
  console.log(`  HIGH (≥8): ${highCount}`);
  console.log(`  MEDIUM (5-7): ${mediumCount}`);
  console.log(`  LOW (<5): ${lowCount}`);
}

/**
 * Prioritize mode: Sort by impact and show top improvements
 */
function prioritizeMode(improvements) {
  console.log('\n🚀 PRIORITIZATION\n');

  const scoredImprovements = improvements.map(imp => {
    const overall = calculateOverallImpact(imp);
    const suggestedPriority = getPriorityFromImpact(overall);
    const manualPriority = imp.priority.toUpperCase();
    const business = imp.business_impact !== null ? imp.business_impact : 5;
    const technical = imp.technical_impact !== null ? imp.technical_impact : 5;
    const user_experience = imp.user_experience_impact !== null ? imp.user_experience_impact : 5;
    const cost_savings = imp.cost_savings_impact !== null ? imp.cost_savings_impact : 5;

    return {
      label: imp.label,
      overall: overall,
      suggestedPriority: suggestedPriority,
      manualPriority: manualPriority,
      priorityMatch: suggestedPriority === manualPriority,
      business: business,
      technical: technical,
      user_experience: user_experience,
      cost_savings: cost_savings,
      status: imp.status,
      effort: imp.effort,
      category: imp.category
    };
  });

  // Sort by overall impact (descending)
  scoredImprovements.sort((a, b) => b.overall - a.overall);

  // Show top 10 highest impact improvements
  console.log('🏆 Top 10 Highest Impact Improvements:\n');
  const top10 = scoredImprovements.slice(0, 10);
  top10.forEach((imp, index) => {
    const emoji = imp.priorityMatch ? '✅' : '⚠️';
    const priorityEmoji = imp.suggestedPriority === 'HIGH' ? '🔴' :
                         imp.suggestedPriority === 'MEDIUM' ? '🟡' : '🟢';

    console.log(`${index + 1}. ${emoji} ${priorityEmoji} ${imp.suggestedPriority} ${imp.overall}/10 - ${imp.label}`);
    console.log(`   Business: ${imp.business}, Technical: ${imp.technical}, ` +
                `UX: ${imp.user_experience}, Cost: ${imp.cost_savings}`);
    console.log(`   Manual priority: ${imp.manualPriority}, Status: ${imp.status}, Effort: ${imp.effort}, Category: ${imp.category}`);
    console.log('');
  });

  // Display priority mismatches
  const mismatches = scoredImprovements.filter(imp => !imp.priorityMatch);
  if (mismatches.length > 0) {
    console.log('⚠️ Priority Mismatches:\n');
    mismatches.forEach(imp => {
      console.log(`  ${imp.label}`);
      console.log(`    Manual: ${imp.manualPriority} → Impact-based: ${imp.suggestedPriority} (${imp.overall}/10)`);
      console.log(`    Status: ${imp.status}, Effort: ${imp.effort}`);
      console.log('');
    });
  } else {
    console.log('✅ No priority mismatches found\n');
  }

  // Effort vs Impact analysis
  console.log('📊 Effort vs Impact Analysis:\n');
  const highImpactLowEffort = scoredImprovements.filter(imp =>
    imp.overall >= PRIORITY_THRESHOLDS.HIGH &&
    (imp.effort === 'TBD' || imp.effort.toLowerCase().includes('minute') ||
     imp.effort.toLowerCase().includes('hour') && !imp.effort.includes('2') && !imp.effort.includes('3'))
  );

  if (highImpactLowEffort.length > 0) {
    console.log('🎯 Quick Wins (High Impact, Low Effort):\n');
    highImpactLowEffort.forEach(imp => {
      console.log(`  ${imp.overall}/10 - ${imp.label} (${imp.effort})`);
    });
    console.log('');
  }

  const lowImpactHighEffort = scoredImprovements.filter(imp =>
    imp.overall < PRIORITY_THRESHOLDS.MEDIUM_LOW &&
    imp.effort !== 'TBD' &&
    (imp.effort.toLowerCase().includes('day') || imp.effort.includes('week'))
  );

  if (lowImpactHighEffort.length > 0) {
    console.log('⚠️ Low Impact, High Effort (Consider Deprioritizing):\n');
    lowImpactHighEffort.forEach(imp => {
      console.log(`  ${imp.overall}/10 - ${imp.label} (${imp.effort})`);
    });
    console.log('');
  }

  // Summary
  console.log('📈 Summary:\n');
  console.log(`  Total improvements: ${scoredImprovements.length}`);
  console.log(`  High impact (≥8): ${scoredImprovements.filter(imp => imp.overall >= PRIORITY_THRESHOLDS.HIGH).length}`);
  console.log(`  Medium impact (5-7): ${scoredImprovements.filter(imp => imp.overall >= PRIORITY_THRESHOLDS.MEDIUM_LOW && imp.overall < PRIORITY_THRESHOLDS.HIGH).length}`);
  console.log(`  Low impact (<5): ${scoredImprovements.filter(imp => imp.overall < PRIORITY_THRESHOLDS.MEDIUM_LOW).length}`);
  console.log(`  Priority mismatches: ${mismatches.length}`);
}

/**
 * Main function
 */
function main() {
  const args = process.argv.slice(2);
  const mode = args[0];

  if (!mode || !['analyze', 'score', 'prioritize'].includes(mode)) {
    console.log('Usage: node scripts/impact-scoring.mjs <mode>');
    console.log('');
    console.log('Modes:');
    console.log('  analyze    - Detailed impact analysis by category');
    console.log('  score      - Calculate impact scores and suggest priorities');
    console.log('  prioritize - Sort by impact and show top improvements');
    console.log('');
    console.log('Examples:');
    console.log('  node scripts/impact-scoring.mjs analyze');
    console.log('  node scripts/impact-scoring.mjs score');
    console.log('  node scripts/impact-scoring.mjs prioritize');
    process.exit(1);
  }

  // Check if SSOT file exists
  if (!existsSync(SSOT_PATH)) {
    console.error(`Error: SSOT file not found at ${SSOT_PATH}`);
    process.exit(1);
  }

  // Read and parse SSOT file
  let ssotContent;
  try {
    ssotContent = readFileSync(SSOT_PATH, 'utf8');
  } catch (error) {
    console.error(`Error reading SSOT file: ${error.message}`);
    process.exit(1);
  }

  // Parse improvements
  let improvements;
  try {
    improvements = parseImprovements(ssotContent);
    console.log(`✅ Parsed ${improvements.length} improvements from SSOT`);
  } catch (error) {
    console.error(`Error parsing improvements: ${error.message}`);
    process.exit(1);
  }

  if (improvements.length === 0) {
    console.log('⚠️ No improvements found in SSOT');
    process.exit(0);
  }

  // Execute selected mode
  try {
    switch (mode) {
      case 'analyze':
        analyzeMode(improvements);
        break;
      case 'score':
        scoreMode(improvements);
        break;
      case 'prioritize':
        prioritizeMode(improvements);
        break;
    }
  } catch (error) {
    console.error(`Error executing ${mode} mode: ${error.message}`);
    process.exit(1);
  }
}

// Only run main() if this file is executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
