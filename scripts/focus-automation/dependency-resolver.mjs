#!/usr/bin/env node

/**
 * Dependency Resolver for Strategic Focus Automation
 * Manages focus dependency graphs, auto-activation, and critical path analysis
 */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const FOCUS_FILE = join(process.cwd(), 'docs/ssot/ssot.focus.yml');

// Configuration
const CONFIG = {
  auto_activate: false,
  notification_delay_hours: 1,
  parallel_activation: true
};

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
 * Build dependency graph
 */
function buildDependencyGraph(focusData) {
  const allFocuses = [...focusData.shared, ...focusData.branch];
  
  const nodes = {};
  const edges = [];
  
  // Build nodes
  allFocuses.forEach(focus => {
    nodes[focus.label] = {
      status: focus.status,
      priority: focus.priority,
      dependencies: focus.dependencies || [],
      dependents: [],
      section: focusData.shared.includes(focus) ? 'shared' : 'branch'
    };
  });
  
  // Build edges
  allFocuses.forEach(focus => {
    if (focus.dependencies) {
      focus.dependencies.forEach(dep => {
        if (nodes[dep]) {
          edges.push({
            from: dep,
            to: focus.label,
            type: 'hard',
            reason: `${focus.label} depends on ${dep}`
          });
          nodes[dep].dependents.push(focus.label);
        }
      });
    }
  });
  
  return { nodes, edges };
}

/**
 * Detect circular dependencies
 */
function detectCircularDependencies(graph) {
  const visited = new Set();
  const recStack = new Set();
  const cycles = [];
  
  function dfs(node, path = []) {
    if (recStack.has(node)) {
      const cycleStart = path.indexOf(node);
      cycles.push(path.slice(cycleStart).concat(node));
      return true;
    }
    
    if (visited.has(node)) return false;
    
    visited.add(node);
    recStack.add(node);
    path.push(node);
    
    const neighbors = graph.edges
      .filter(e => e.from === node)
      .map(e => e.to);
    
    for (const neighbor of neighbors) {
      if (dfs(neighbor, [...path])) {
        return true;
      }
    }
    
    recStack.delete(node);
    path.pop();
    return false;
  }
  
  for (const node of Object.keys(graph.nodes)) {
    if (!visited.has(node)) {
      dfs(node);
    }
  }
  
  return cycles;
}

/**
 * Find critical path
 */
function findCriticalPath(graph) {
  // Topological sort with longest path
  const visited = new Set();
  const distances = {};
  const predecessors = {};
  
  // Initialize distances
  Object.keys(graph.nodes).forEach(node => {
    distances[node] = 0;
    predecessors[node] = null;
  });
  
  function dfs(node) {
    if (visited.has(node)) return distances[node];
    
    visited.add(node);
    
    const incomingEdges = graph.edges.filter(e => e.to === node);
    
    if (incomingEdges.length === 0) {
      distances[node] = 1; // Base weight
      return distances[node];
    }
    
    let maxDist = 0;
    let bestPred = null;
    
    incomingEdges.forEach(edge => {
      const predDist = dfs(edge.from);
      if (predDist > maxDist) {
        maxDist = predDist;
        bestPred = edge.from;
      }
    });
    
    distances[node] = maxDist + 1;
    predecessors[node] = bestPred;
    
    return distances[node];
  }
  
  // Find longest path
  Object.keys(graph.nodes).forEach(node => {
    if (!visited.has(node)) {
      dfs(node);
    }
  });
  
  // Reconstruct critical path
  const maxNode = Object.keys(distances).reduce((a, b) => 
    distances[a] > distances[b] ? a : b
  );
  
  const criticalPath = [];
  let current = maxNode;
  
  while (current) {
    criticalPath.unshift(current);
    current = predecessors[current];
  }
  
  return criticalPath;
}

/**
 * Find parallelizable focuses
 */
function findParallelizable(graph) {
  const parallelGroups = [];
  const processed = new Set();
  
  Object.keys(graph.nodes).forEach(node => {
    if (processed.has(node)) return;
    
    if (graph.nodes[node].dependencies.length === 0) {
      // Can run independently
      processed.add(node);
      parallelGroups.push([node]);
    }
  });
  
  // Find focuses with same dependencies
  const depGroups = {};
  Object.keys(graph.nodes).forEach(node => {
    const deps = JSON.stringify(graph.nodes[node].dependencies.sort());
    if (!depGroups[deps]) depGroups[deps] = [];
    depGroups[deps].push(node);
  });
  
  Object.values(depGroups).forEach(group => {
    if (group.length > 1) {
      parallelGroups.push(group);
      group.forEach(n => processed.add(n));
    }
  });
  
  return parallelGroups;
}

/**
 * Check dependency status
 */
function showDependencyStatus() {
  console.log('🎯 Focus Dependency Status\n');
  
  const focusData = loadFocusData();
  if (!focusData) return;
  
  const graph = buildDependencyGraph(focusData);
  
  // Check for circular dependencies
  const cycles = detectCircularDependencies(graph);
  if (cycles.length > 0) {
    console.log('⚠️  Circular Dependencies Detected:');
    cycles.forEach((cycle, i) => {
      console.log(`   ${i + 1}. ${cycle.join(' → ')}`);
    });
    console.log();
  } else {
    console.log('✅ No circular dependencies detected\n');
  }
  
  // Show dependency status for each focus
  const allFocuses = [...focusData.shared, ...focusData.branch];
  
  console.log('📊 Dependency Status:\n');
  
  allFocuses.forEach(focus => {
    const status = focus.status;
    const deps = focus.dependencies || [];
    
    console.log(`${focus.label}`);
    console.log(`   Status: ${status}`);
    console.log(`   Priority: ${focus.priority}`);
    
    if (deps.length > 0) {
      console.log(`   Dependencies:`);
      deps.forEach(dep => {
        const depFocus = allFocuses.find(f => f.label === dep);
        const depStatus = depFocus ? depFocus.status : 'NOT FOUND';
        const ready = depStatus === 'completed';
        const icon = ready ? '✅' : '⏳';
        console.log(`     ${icon} ${dep} (${depStatus})`);
      });
    } else {
      console.log(`   Dependencies: None`);
    }
    
    // Check if this focus is blocking others
    const blocking = graph.nodes[focus.label]?.dependents || [];
    if (blocking.length > 0) {
      console.log(`   Blocking: ${blocking.join(', ')}`);
    }
    
    console.log();
  });
}

/**
 * Find next activatable focuses
 */
function findNextActivatable() {
  console.log('🎯 Next Activatable Focuses\n');
  
  const focusData = loadFocusData();
  if (!focusData) return;
  
  const graph = buildDependencyGraph(focusData);
  const allFocuses = [...focusData.shared, ...focusData.branch];
  
  const activatable = [];
  
  allFocuses.forEach(focus => {
    if (focus.status === 'active' || focus.status === 'completed') return;
    
    const deps = focus.dependencies || [];
    const allDepsMet = deps.every(dep => {
      const depFocus = allFocuses.find(f => f.label === dep);
      return depFocus && depFocus.status === 'completed';
    });
    
    if (allDepsMet && deps.length > 0) {
      activatable.push({
        focus: focus.label,
        priority: focus.priority,
        section: focusData.shared.includes(focus) ? 'shared' : 'branch',
        dependencies_met: deps
      });
    }
  });
  
  if (activatable.length === 0) {
    console.log('ℹ️  No focuses ready to activate (all have pending dependencies)');
    
    // Show focuses with no dependencies
    const noDeps = allFocuses.filter(f => 
      f.status !== 'active' && 
      f.status !== 'completed' && 
      (!f.dependencies || f.dependencies.length === 0)
    );
    
    if (noDeps.length > 0) {
      console.log('\n📋 Focuses with no dependencies (can activate anytime):');
      noDeps.forEach(focus => {
        console.log(`   • ${focus.label} (${focus.priority})`);
      });
    }
    
    return;
  }
  
  // Sort by priority
  const priorityOrder = { high: 1, medium: 2, low: 3 };
  activatable.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
  
  console.log(`🎯 ${activatable.length} focuses ready to activate:\n`);
  
  activatable.forEach((item, index) => {
    console.log(`${index + 1}. ${item.focus}`);
    console.log(`   Priority: ${item.priority}`);
    console.log(`   Section: ${item.section}`);
    console.log(`   Dependencies met: ${item.dependencies_met.join(', ')}`);
    console.log();
  });
}

/**
 * Visualize dependency graph
 */
function visualizeGraph() {
  console.log('🎯 Dependency Graph Visualization\n');
  
  const focusData = loadFocusData();
  if (!focusData) return;
  
  const graph = buildDependencyGraph(focusData);
  
  console.log('📊 Dependency Relationships:\n');
  
  Object.keys(graph.nodes).forEach(node => {
    const nodeData = graph.nodes[node];
    const deps = nodeData.dependencies;
    
    if (deps.length > 0) {
      console.log(`${node}`);
      deps.forEach(dep => {
        const depStatus = graph.nodes[dep]?.status || 'unknown';
        const icon = depStatus === 'completed' ? '✅' : 
                    depStatus === 'active' ? '🔄' : '⏳';
        console.log(`  └─ ${icon} ${dep} (${depStatus})`);
      });
    }
  });
  
  console.log('\n🔗 Critical Path:');
  const criticalPath = findCriticalPath(graph);
  console.log(`   ${criticalPath.join(' → ')}`);
  
  console.log('\n🔄 Parallelizable Groups:');
  const parallelGroups = findParallelizable(graph);
  parallelGroups.forEach((group, i) => {
    console.log(`   Group ${i + 1}: ${group.join(', ')}`);
  });
}

/**
 * Main command handler
 */
function main() {
  const command = process.argv[2] || 'status';
  
  switch (command) {
    case 'status':
      showDependencyStatus();
      break;
    case 'next':
      findNextActivatable();
      break;
    case 'graph':
      visualizeGraph();
      break;
    default:
      console.log('Usage: node dependency-resolver.mjs [status|next|graph]');
      console.log('  status - Show dependency status for all focuses');
      console.log('  next   - Find next activatable focuses');
      console.log('  graph  - Visualize dependency graph');
      process.exit(1);
  }
}

main();
