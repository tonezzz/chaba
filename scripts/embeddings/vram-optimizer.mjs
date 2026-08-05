#!/usr/bin/env node
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * GPU VRAM Performance Tuning Script
 * Implements recommendations from GPU sharing analysis for VRAM optimization
 */

class VRAMOptimizer {
  constructor() {
    this.embeddingServiceUrl = 'http://localhost:5000';
  }

  async getCurrentVRAMUsage() {
    try {
      const { stdout } = await execAsync('nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits');
      const [used, total] = stdout.trim().split(',').map(Number);
      return { used, total, available: total - used, utilization: (used / total) * 100 };
    } catch (error) {
      console.error('Failed to get VRAM usage:', error.message);
      return null;
    }
  }

  async getEmbeddingServiceVRAM() {
    try {
      const response = await fetch(`${this.embeddingServiceUrl}/health`);
      const health = await response.json();
      return {
        vram_usage_mb: health.vram_usage_mb || 0,
        model: health.model,
        device: health.device
      };
    } catch (error) {
      console.error('Failed to get embedding service VRAM:', error.message);
      return null;
    }
  }

  async analyzeVRAMEfficiency() {
    console.log('=== VRAM Efficiency Analysis ===\n');
    
    const systemVRAM = await this.getCurrentVRAMUsage();
    const embeddingVRAM = await this.getEmbeddingServiceVRAM();
    
    if (!systemVRAM || !embeddingVRAM) {
      console.error('Failed to gather VRAM data');
      return null;
    }
    
    console.log('System VRAM:');
    console.log(`  Total: ${systemVRAM.total} MB`);
    console.log(`  Used: ${systemVRAM.used} MB`);
    console.log(`  Available: ${systemVRAM.available} MB`);
    console.log(`  Utilization: ${systemVRAM.utilization.toFixed(1)}%`);
    
    console.log('\nEmbedding Service VRAM:');
    console.log(`  Usage: ${embeddingVRAM.vram_usage_mb} MB`);
    console.log(`  Model: ${embeddingVRAM.model}`);
    console.log(`  Device: ${embeddingVRAM.device}`);
    
    const embeddingPercentage = (embeddingVRAM.vram_usage_mb / systemVRAM.total) * 100;
    console.log(`  Percentage of Total: ${embeddingPercentage.toFixed(1)}%`);
    
    const efficiency = {
      systemUtilization: systemVRAM.utilization,
      embeddingPercentage,
      embeddingEfficiency: embeddingVRAM.vram_usage_mb / 384, // VRAM per dimension
      headroom: systemVRAM.available - 500, // Reserve 500MB for system
      canRunConcurrent: systemVRAM.available > 600 // Need ~600MB for imagen2
    };
    
    console.log('\nEfficiency Metrics:');
    console.log(`  System Utilization: ${efficiency.systemUtilization.toFixed(1)}%`);
    console.log(`  Embedding VRAM per Dimension: ${efficiency.embeddingEfficiency.toFixed(2)} MB`);
    console.log(`  Available Headroom: ${efficiency.headroom} MB`);
    console.log(`  Can Run Concurrent Jobs: ${efficiency.canRunConcurrent ? 'Yes' : 'No'}`);
    
    return efficiency;
  }

  async recommendOptimizations() {
    console.log('\n=== VRAM Optimization Recommendations ===\n');
    
    const efficiency = await this.analyzeVRAMEfficiency();
    if (!efficiency) return;
    
    const recommendations = [];
    
    // VRAM usage recommendations
    if (efficiency.systemUtilization > 80) {
      recommendations.push({
        priority: 'HIGH',
        category: 'VRAM Usage',
        recommendation: 'High VRAM utilization (>80%). Consider model optimization.',
        actions: [
          'Test quantized embedding models (INT8 vs FP16)',
          'Implement model offloading to CPU for inference',
          'Reduce batch size for embedding jobs',
          'Consider smaller embedding models for specific use cases'
        ]
      });
    }
    
    if (efficiency.embeddingPercentage > 70) {
      recommendations.push({
        priority: 'MEDIUM',
        category: 'Embedding Service',
        recommendation: 'Embedding service using significant VRAM (>70%).',
        actions: [
          'Profile GPU memory allocation patterns',
          'Test with smaller embedding models (e.g., all-MiniLM-L6-v2 vs larger models)',
          'Implement dynamic model loading/unloading',
          'Add model caching strategies to reduce reload overhead'
        ]
      });
    }
    
    if (!efficiency.canRunConcurrent) {
      recommendations.push({
        priority: 'HIGH',
        category: 'Concurrent Processing',
        recommendation: 'Insufficient VRAM for concurrent processing.',
        actions: [
          'Prioritize embedding jobs over image/video generation',
          'Implement preemptive queue for low-priority jobs',
          'Consider GPU upgrade to 8GB+ for concurrent workloads',
          'Add VRAM monitoring alerts to prevent OOM errors'
        ]
      });
    }
    
    // General optimization recommendations
    recommendations.push({
      priority: 'MEDIUM',
      category: 'Performance Monitoring',
      recommendation: 'Enhanced monitoring for VRAM optimization.',
      actions: [
        'Track VRAM usage patterns over time',
        'Monitor queue wait times vs VRAM availability',
        'Add alerts for VRAM threshold breaches',
        'Implement automatic job scaling based on VRAM availability'
      ]
    });
    
    // Display recommendations
    recommendations.forEach((rec, index) => {
      console.log(`${index + 1}. [${rec.priority}] ${rec.category}: ${rec.recommendation}`);
      rec.actions.forEach(action => {
        console.log(`   - ${action}`);
      });
      console.log();
    });
    
    return recommendations;
  }

  async testQuantizedModel() {
    console.log('=== Testing Quantized Model Performance ===\n');
    console.log('Note: This requires model retraining or conversion to quantized format.');
    console.log('Current recommendation: Test with existing model first, then consider quantization.');
    console.log('Benefits: 2-4x VRAM reduction with minimal accuracy loss for many use cases.');
    console.log('Trade-offs: Slightly reduced accuracy, conversion overhead.');
    
    return {
      status: 'recommendation',
      action: 'Consider INT8 quantization for embedding model',
      expectedVRAMReduction: '50-75%',
      expectedAccuracyLoss: '1-3%'
    };
  }
}

// Run optimizer if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  const optimizer = new VRAMOptimizer();
  optimizer.recommendOptimizations().catch(error => {
    console.error('VRAM optimization analysis failed:', error);
    process.exit(1);
  });
}

export { VRAMOptimizer };