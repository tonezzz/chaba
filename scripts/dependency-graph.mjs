#!/usr/bin/env node

import { readFileSync, existsSync, writeFileSync } from 'fs';
import { execSync } from 'child_process';

const SSOT_PATH = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/ssot.improvements.yml';
const OUTPUT_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/reports';

// Parse command line arguments
const args = process.argv.slice(2);
const format = args[0] || 'text'; // text, mermaid, dot

console.log(`Generating dependency graph in ${format} format...`);

// Load SSOT file
if (!existsSync(SSOT_PATH)) {
  console.error('SSOT improvements file not found');
  process.exit(1);
}

const ssotContent = readFileSync(SSOT_PATH, 'utf8');

// Parse improvements
const improvements = parseImprovements(ssotContent);

console.log(`Found ${improvements.length} improvements`);

// Generate graph based on format
let graph = '';

switch (format) {
  case 'mermaid':
    graph = generateMermaidGraph(improvements);
    break;
  case 'dot':
    graph = generateDotGraph(improvements);
    break;
  case 'text':
  default:
    graph = generateTextGraph(improvements);
    break;
}

// Output graph
if (format === 'text') {
  console.log('\n' + graph);
} else {
  const outputFile = `${OUTPUT_DIR}/dependency-graph-${format}-${new Date().toISOString().split('T')[0]}.${format === 'mermaid' ? 'mmd' : 'dot'}`;
  writeFileSync(outputFile, graph);
  console.log(`Graph saved to: ${outputFile}`);
  
  if (format === 'dot') {
    try {
      // Try to generate PNG if graphviz is available
      const pngFile = outputFile.replace('.dot', '.png');
      execSync(`dot -Tpng ${outputFile} -o ${pngFile}`, { encoding: 'utf8' });
      console.log(`PNG generated: ${pngFile}`);
    } catch (e) {
      console.log('Graphviz not available, skipping PNG generation');
    }
  }
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
        status: 'pending'
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
      } else if (line.startsWith('- label:') && currentImprovement.label) {
        improvements.push(currentImprovement);
        currentImprovement = { 
          label: line.split('label:')[1].trim(),
          depends_on: [],
          blocks: [],
          priority: 'medium',
          status: 'pending'
        };
      }
    }
  }
  
  if (currentImprovement) {
    improvements.push(currentImprovement);
  }
  
  return improvements;
}

function generateTextGraph(improvements) {
  let graph = '=== Dependency Graph ===\n\n';
  
  // Group by status
  const byStatus = {
    'pending': improvements.filter(imp => imp.status === 'pending'),
    'planned': improvements.filter(imp => imp.status === 'planned'),
    'completed': improvements.filter(imp => imp.status === 'completed')
  };
  
  // Show completed improvements first
  if (byStatus.completed.length > 0) {
    graph += '## Completed Improvements\n\n';
    byStatus.completed.forEach(imp => {
      graph += `✅ ${imp.label}\n`;
      if (imp.blocks && imp.blocks.length > 0) {
        graph += `   ↳ Unblocks: ${imp.blocks.join(', ')}\n`;
      }
    });
    graph += '\n';
  }
  
  // Show pending improvements with dependencies
  if (byStatus.pending.length > 0) {
    graph += '## Pending Improvements\n\n';
    byStatus.pending.forEach(imp => {
      const statusIcon = imp.depends_on.length > 0 ? '🔒' : '🚀';
      graph += `${statusIcon} ${imp.label} (${imp.priority})\n`;
      
      if (imp.depends_on.length > 0) {
        graph += `   ↳ Depends on: ${imp.depends_on.join(', ')}\n`;
      }
      
      if (imp.blocks && imp.blocks.length > 0) {
        graph += `   ↳ Blocks: ${imp.blocks.join(', ')}\n`;
      }
    });
    graph += '\n';
  }
  
  // Show planned improvements
  if (byStatus.planned.length > 0) {
    graph += '## Planned Improvements\n\n';
    byStatus.planned.forEach(imp => {
      const statusIcon = imp.depends_on.length > 0 ? '🔒' : '📋';
      graph += `${statusIcon} ${imp.label} (${imp.priority})\n`;
      
      if (imp.depends_on.length > 0) {
        graph += `   ↳ Depends on: ${imp.depends_on.join(', ')}\n`;
      }
      
      if (imp.blocks && imp.blocks.length > 0) {
        graph += `   ↳ Blocks: ${imp.blocks.join(', ')}\n`;
      }
    });
    graph += '\n';
  }
  
  // Show critical path
  graph += '## Critical Path Analysis\n\n';
  const criticalPath = findCriticalPath(improvements);
  if (criticalPath.length > 0) {
    graph += 'Critical path (longest dependency chain):\n';
    criticalPath.forEach((item, index) => {
      graph += `${index + 1}. ${item.label} (${item.status})\n`;
    });
  } else {
    graph += 'No critical path identified (no dependencies)\n';
  }
  
  return graph;
}

function generateMermaidGraph(improvements) {
  let graph = 'graph TD\n';
  graph += '    %% Dependency Graph for Chaba Improvements\n';
  graph += '    %% Generated: ' + new Date().toISOString() + '\n\n';
  
  // Define nodes
  improvements.forEach(imp => {
    const nodeId = imp.label.replace(/[^a-zA-Z0-9]/g, '_');
    const statusColor = imp.status === 'completed' ? '#90EE90' : 
                       imp.status === 'pending' ? '#FFD700' : '#87CEEB';
    const priorityShape = imp.priority === 'high' ? 'diamond' : 
                        imp.priority === 'medium' ? 'rect' : 'circle';
    
    graph += `    ${nodeId}[${imp.label}]\n`;
    graph += `    style ${nodeId} fill:${statusColor},stroke:#333,stroke-width:2px\n`;
    graph += `    click ${nodeId} "#${nodeId}" "Tooltip"\n\n`;
  });
  
  // Define edges (dependencies)
  improvements.forEach(imp => {
    const nodeId = imp.label.replace(/[^a-zA-Z0-9]/g, '_');
    
    if (imp.depends_on && imp.depends_on.length > 0) {
      imp.depends_on.forEach(dep => {
        const depId = dep.replace(/[^a-zA-Z0-9]/g, '_');
        graph += `    ${depId} -->|depends on| ${nodeId}\n`;
      });
    }
  });
  
  // Add legend
  graph += '\n    %% Legend\n';
  graph += '    subgraph Legend\n';
  graph += '        L1[Completed]\n';
  graph += '        style L1 fill:#90EE90,stroke:#333,stroke-width:2px\n';
  graph += '        L2[Pending]\n';
  graph += '        style L2 fill:#FFD700,stroke:#333,stroke-width:2px\n';
  graph += '        L3[Planned]\n';
  graph += '        style L3 fill:#87CEEB,stroke:#333,stroke-width:2px\n';
  graph += '    end\n';
  
  return graph;
}

function generateDotGraph(improvements) {
  let graph = 'digraph DependencyGraph {\n';
  graph += '    rankdir=TB;\n';
  graph += '    node [shape=box, style=rounded];\n';
  graph += '    edge [dir=back];\n\n';
  
  // Define nodes with colors based on status
  improvements.forEach(imp => {
    const nodeId = imp.label.replace(/[^a-zA-Z0-9]/g, '_');
    const statusColor = imp.status === 'completed' ? 'lightgreen' : 
                       imp.status === 'pending' ? 'gold' : 'lightblue';
    const priorityStyle = imp.priority === 'high' ? 'shape=diamond' : '';
    
    graph += `    "${nodeId}" [label="${imp.label}", fillcolor="${statusColor}", style="filled,rounded", ${priorityStyle}];\n`;
  });
  
  // Define edges
  improvements.forEach(imp => {
    const nodeId = imp.label.replace(/[^a-zA-Z0-9]/g, '_');
    
    if (imp.depends_on && imp.depends_on.length > 0) {
      imp.depends_on.forEach(dep => {
        const depId = dep.replace(/[^a-zA-Z0-9]/g, '_');
        graph += `    "${depId}" -> "${nodeId}" [label="depends on"];\n`;
      });
    }
  });
  
  graph += '\n    // Legend\n';
  graph += '    subgraph cluster_legend {\n';
  graph += '        label = "Legend";\n';
  graph += '        node [shape=box];\n';
  graph += '        completed [label="Completed", fillcolor="lightgreen", style="filled"];\n';
  graph += '        pending [label="Pending", fillcolor="gold", style="filled"];\n';
  graph += '        planned [label="Planned", fillcolor="lightblue", style="filled"];\n';
  graph += '    }\n';
  graph += '}';
  
  return graph;
}

function findCriticalPath(improvements) {
  // Build dependency graph
  const graph = new Map();
  const inDegree = new Map();
  
  improvements.forEach(imp => {
    graph.set(imp.label, {
      improvement: imp,
      dependencies: imp.depends_on || []
    });
    inDegree.set(imp.label, (imp.depends_on || []).length);
  });
  
  // Find nodes with no dependencies (starting points)
  const queue = [];
  inDegree.forEach((degree, label) => {
    if (degree === 0) {
      queue.push({ label, path: [label] });
    }
  });
  
  // BFS to find longest path
  let longestPath = [];
  
  while (queue.length > 0) {
    const { label, path } = queue.shift();
    
    if (path.length > longestPath.length) {
      longestPath = path;
    }
    
    const node = graph.get(label);
    if (node && node.dependencies) {
      node.dependencies.forEach(dep => {
        const depNode = graph.get(dep);
        if (depNode) {
          queue.push({ label: dep, path: [...path, dep] });
        }
      });
    }
  }
  
  return longestPath.map(label => {
    const imp = improvements.find(i => i.label === label);
    return { label, status: imp ? imp.status : 'unknown' };
  });
}