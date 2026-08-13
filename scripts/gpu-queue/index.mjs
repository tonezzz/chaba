import http from 'http';
import * as db from './db.mjs';
import * as queue from './queue.mjs';
import * as monitoring from './monitoring.mjs';
import * as orchestrator from './orchestrator.mjs';
import * as scheduler from './scheduler.mjs';
import { getGPUMemoryStats } from './gpu-memory-aware.mjs';
import { getPredictionAccuracy, setPredictionModel } from './job-duration-prediction.mjs';
import { getPriorityAdjustmentStats, adjustPendingJobPriorities } from './dynamic-priority.mjs';
import * as intelligentMonitoring from './intelligent-monitoring.mjs';

const PORT = process.env.GPU_QUEUE_PORT || 3001;
const HOST = process.env.GPU_QUEUE_HOST || '0.0.0.0';

// Helper: send JSON response
function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

// Helper: parse JSON body
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

// Helper: parse URL path
function parsePath(url) {
  const pathname = new URL(url, `http://${HOST}`).pathname;
  const parts = pathname.split('/').filter(Boolean);
  return parts;
}

// Request handler
async function handleRequest(req, res) {
  const path = parsePath(req.url);
  const method = req.method;

  console.log(`${method} ${req.url}`);

  try {
    // POST /api/gpu-queue/jobs - Submit a job
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'jobs' && method === 'POST') {
      const body = await parseBody(req);
      const { type, params } = body;

      if (!type || !params) {
        return sendJson(res, 400, { error: 'Missing type or params' });
      }

      const validTypes = ['llama', 'imagen2', 'txt2vid', 'embedding', 'yomi_summary', 'yomi_daily', 'yomi_daily_batch'];
      if (!validTypes.includes(type)) {
        return sendJson(res, 400, { error: `Invalid type. Must be one of: ${validTypes.join(', ')}` });
      }

      const job = await queue.submitJob(type, params);
      sendJson(res, 201, job);
      return;
    }

    // GET /api/gpu-queue/jobs - List all jobs
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'jobs' && method === 'GET') {
      const status = new URL(req.url, `http://${HOST}`).searchParams.get('status');
      const jobs = await db.listJobs(status);
      sendJson(res, 200, jobs);
      return;
    }

    // GET /api/gpu-queue/jobs/:id - Get job status
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'jobs' && path[3] && method === 'GET') {
      const jobId = parseInt(path[3], 10);
      if (isNaN(jobId)) {
        return sendJson(res, 400, { error: 'Invalid job ID' });
      }

      const job = await db.getJob(jobId);
      if (!job) {
        return sendJson(res, 404, { error: 'Job not found' });
      }

      sendJson(res, 200, job);
      return;
    }

    // DELETE /api/gpu-queue/jobs/:id - Cancel a job
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'jobs' && path[3] && method === 'DELETE') {
      const jobId = parseInt(path[3], 10);
      if (isNaN(jobId)) {
        return sendJson(res, 400, { error: 'Invalid job ID' });
      }

      try {
        const job = await queue.cancelJob(jobId);
        sendJson(res, 200, job);
      } catch (error) {
        sendJson(res, 400, { error: error.message });
      }
      return;
    }

    // GET /api/gpu-queue/status - Get queue status
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'status' && method === 'GET') {
      const statusCounts = await db.getQueueStatus();
      const runningJob = await db.getRunningJob();
      const jobTypeBreakdown = await db.getJobTypeBreakdown();
      const recentJobs = await db.getRecentJobs(5);
      const priorityDistribution = await db.getPriorityDistribution();

      sendJson(res, 200, {
        status: statusCounts,
        running: runningJob || null,
        jobTypeBreakdown,
        recentJobs,
        priorityDistribution
      });
      return;
    }

    // GET /api/gpu-queue/monitoring/health - Detailed health check
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'monitoring' && path[3] === 'health' && method === 'GET') {
      const health = await monitoring.getQueueHealth();
      sendJson(res, 200, health);
      return;
    }

    // GET /api/gpu-queue/monitoring/performance - Performance metrics
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'monitoring' && path[3] === 'performance' && method === 'GET') {
      const performance = await monitoring.getPerformanceMetrics();
      sendJson(res, 200, performance);
      return;
    }

    // GET /api/gpu-queue/monitoring/activity - Recent activity
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'monitoring' && path[3] === 'activity' && method === 'GET') {
      const limit = parseInt(new URL(req.url, `http://${HOST}`).searchParams.get('limit')) || 20;
      const activity = await monitoring.getRecentActivity(limit);
      sendJson(res, 200, activity);
      return;
    }

    // GET /api/gpu-queue/monitoring/overview - System overview
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'monitoring' && path[3] === 'overview' && method === 'GET') {
      const overview = await monitoring.getSystemOverview();
      sendJson(res, 200, overview);
      return;
    }

    // GET /api/gpu-queue/stats - Job statistics
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'stats' && method === 'GET') {
      const hours = parseInt(new URL(req.url, `http://${HOST}`).searchParams.get('hours')) || 24;
      const stats = await db.getJobStats(hours);
      sendJson(res, 200, stats);
      return;
    }

    // GET /api/gpu-queue/cancellation-rate - Cancellation rate monitoring
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'cancellation-rate' && method === 'GET') {
      const hours = parseInt(new URL(req.url, `http://${HOST}`).searchParams.get('hours')) || 24;
      const cancellationRate = await db.getCancellationRate(hours);
      sendJson(res, 200, cancellationRate);
      return;
    }

    // GET /api/gpu-queue/recent-failures - Recent job failures
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'recent-failures' && method === 'GET') {
      const limit = parseInt(new URL(req.url, `http://${HOST}`).searchParams.get('limit')) || 10;
      const failures = await db.getRecentFailures(limit);
      sendJson(res, 200, failures);
      return;
    }

    // GET /api/gpu-queue/gpu-memory - GPU memory statistics
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'gpu-memory' && method === 'GET') {
      const memoryStats = await getGPUMemoryStats();
      sendJson(res, 200, memoryStats);
      return;
    }

    // GET /api/gpu-queue/prediction-accuracy - Prediction model accuracy
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'prediction-accuracy' && method === 'GET') {
      const accuracy = await getPredictionAccuracy();
      sendJson(res, 200, accuracy);
      return;
    }

    // GET /api/gpu-queue/priority-stats - Priority adjustment statistics
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'priority-stats' && method === 'GET') {
      const stats = await getPriorityAdjustmentStats();
      sendJson(res, 200, stats);
      return;
    }

    // POST /api/gpu-queue/adjust-priorities - Manually trigger priority adjustment
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'adjust-priorities' && method === 'POST') {
      const result = await adjustPendingJobPriorities();
      sendJson(res, 200, result);
      return;
    }

    // GET /api/gpu-queue/scheduler - Get current scheduler
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'scheduler' && method === 'GET') {
      sendJson(res, 200, { scheduler: scheduler.getScheduler() });
      return;
    }

    // PUT /api/gpu-queue/scheduler - Set scheduler
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'scheduler' && method === 'PUT') {
      const body = await parseBody(req);
      const { scheduler: newScheduler } = body;
      try {
        scheduler.setScheduler(newScheduler);
        sendJson(res, 200, { scheduler: newScheduler });
      } catch (error) {
        sendJson(res, 400, { error: error.message });
      }
      return;
    }

    // GET /api/gpu-queue/intelligent-metrics - Comprehensive intelligent scheduling metrics
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'intelligent-metrics' && method === 'GET') {
      const metrics = await intelligentMonitoring.getIntelligentSchedulingMetrics();
      sendJson(res, 200, metrics);
      return;
    }

    // GET /api/gpu-queue/scheduling-performance - Scheduling performance comparison
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'scheduling-performance' && method === 'GET') {
      const performance = await intelligentMonitoring.getSchedulingPerformanceComparison();
      sendJson(res, 200, performance);
      return;
    }

    // GET /api/gpu-queue/memory-trends - Memory utilization trends
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'memory-trends' && method === 'GET') {
      const hours = parseInt(new URL(req.url, `http://${HOST}`).searchParams.get('hours')) || 24;
      const trends = await intelligentMonitoring.getMemoryUtilizationTrends(hours);
      sendJson(res, 200, trends);
      return;
    }

    // GET /api/gpu-queue/prediction-performance - Prediction model performance
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'prediction-performance' && method === 'GET') {
      const hours = parseInt(new URL(req.url, `http://${HOST}`).searchParams.get('hours')) || 24;
      const performance = await intelligentMonitoring.getPredictionModelPerformance(hours);
      sendJson(res, 200, performance);
      return;
    }

    // GET /api/gpu-queue/priority-effectiveness - Priority adjustment effectiveness
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'priority-effectiveness' && method === 'GET') {
      const effectiveness = await intelligentMonitoring.getPriorityAdjustmentEffectiveness();
      sendJson(res, 200, effectiveness);
      return;
    }

    // GET /api/gpu-queue/monitoring-dashboard - Comprehensive monitoring dashboard
    if (path[0] === 'api' && path[1] === 'gpu-queue' && path[2] === 'monitoring-dashboard' && method === 'GET') {
      const dashboard = await intelligentMonitoring.getMonitoringDashboard();
      sendJson(res, 200, dashboard);
      return;
    }

    // GET /health - Health check
    if (path[0] === 'health' && method === 'GET') {
      const health = await monitoring.getQueueHealth();
      sendJson(res, 200, health);
      return;
    }

    // 404 for unknown paths
    sendJson(res, 404, { error: 'Not found' });
  } catch (error) {
    console.error('Request error:', error);
    sendJson(res, 500, { error: error.message });
  }
}

// Create server
const server = http.createServer(handleRequest);

// Start server
server.listen(PORT, HOST, () => {
  console.log(`GPU Queue API listening on http://${HOST}:${PORT}`);
  console.log('Endpoints:');
  console.log('  POST   /api/gpu-queue/jobs                      - Submit job');
  console.log('  GET    /api/gpu-queue/jobs                      - List jobs');
  console.log('  GET    /api/gpu-queue/jobs/:id                  - Get job status');
  console.log('  DELETE /api/gpu-queue/jobs/:id                  - Cancel job');
  console.log('  GET    /api/gpu-queue/status                    - Queue status');
  console.log('  GET    /api/gpu-queue/monitoring/health         - Monitoring health');
  console.log('  GET    /api/gpu-queue/monitoring/performance     - Monitoring performance');
  console.log('  GET    /api/gpu-queue/monitoring/activity        - Monitoring activity');
  console.log('  GET    /api/gpu-queue/monitoring/overview       - Monitoring overview');
  console.log('  GET    /api/gpu-queue/stats                       - Job statistics');
  console.log('  GET    /api/gpu-queue/cancellation-rate          - Cancellation rate monitoring');
  console.log('  GET    /api/gpu-queue/recent-failures           - Recent job failures');
  console.log('  GET    /api/gpu-queue/gpu-memory                 - GPU memory statistics');
  console.log('  GET    /api/gpu-queue/prediction-accuracy        - Prediction model accuracy');
  console.log('  GET    /api/gpu-queue/priority-stats              - Priority adjustment statistics');
  console.log('  POST   /api/gpu-queue/adjust-priorities          - Manual priority adjustment');
  console.log('  GET    /api/gpu-queue/scheduler                   - Get current scheduler');
  console.log('  PUT    /api/gpu-queue/scheduler                   - Set scheduler');
  console.log('  GET    /api/gpu-queue/intelligent-metrics         - Comprehensive intelligent metrics');
  console.log('  GET    /api/gpu-queue/scheduling-performance       - Scheduling performance comparison');
  console.log('  GET    /api/gpu-queue/memory-trends               - Memory utilization trends');
  console.log('  GET    /api/gpu-queue/prediction-performance      - Prediction model performance');
  console.log('  GET    /api/gpu-queue/priority-effectiveness       - Priority adjustment effectiveness');
  console.log('  GET    /api/gpu-queue/monitoring-dashboard         - Comprehensive monitoring dashboard');
  console.log('  GET    /health                                    - Health check');
  console.log('');
  console.log('Queue processor enabled with intelligent scheduling.');
  console.log(`Current scheduler: ${scheduler.getScheduler()}`);
});

// GPU-aware queue processor with backpressure
let isProcessing = false;
let consecutiveFailures = 0;
const MAX_CONSECUTIVE_FAILURES = 5;
const BACKPRESSURE_DELAY = 30000; // 30 seconds on backpressure

// Job-specific rate limiting
const jobLimits = {
  yomi_summary: { maxConcurrent: 1, lastProcessed: 0 },
  yomi_daily: { maxConcurrent: 1, lastProcessed: 0 },
  yomi_daily_batch: { maxConcurrent: 1, lastProcessed: 0 },
  embedding: { maxConcurrent: 2, lastProcessed: 0 },
  imagen2: { maxConcurrent: 1, lastProcessed: 0 },
  txt2vid: { maxConcurrent: 1, lastProcessed: 0 },
  llama: { maxConcurrent: 1, lastProcessed: 0 }
};

// Check if job type can be processed based on rate limits
function canProcessJobType(jobType) {
  const limit = jobLimits[jobType];
  if (!limit) return true;
  
  const now = Date.now();
  const timeSinceLastProcess = now - limit.lastProcessed;
  
  // Allow processing if enough time has passed (minimum 3 seconds between same job types)
  return timeSinceLastProcess > 3000;
}

// Mark job type as processed
function markJobTypeProcessed(jobType) {
  const limit = jobLimits[jobType];
  if (limit) {
    limit.lastProcessed = Date.now();
  }
}

// GPU monitoring
async function checkGPUStatus() {
  try {
    const response = await fetch('http://host.docker.internal:19999/api/v1/gpu');
    if (!response.ok) return { available: true, memoryPercent: 0 };
    
    const data = await response.json();
    const gpu = data?.gpu?.[0];
    if (!gpu) return { available: true, memoryPercent: 0 };
    
    const memoryPercent = (gpu.memory_used_mb / gpu.memory_total_mb) * 100;
    return {
      available: memoryPercent < 80, // Only process if GPU < 80% utilized
      memoryPercent,
      memoryUsed: gpu.memory_used_mb,
      memoryTotal: gpu.memory_total_mb
    };
  } catch (error) {
    console.log('GPU monitoring failed, assuming available:', error.message);
    return { available: true, memoryPercent: 0 };
  }
}

// Start queue processor with direct API calls (no MCP required)
async function startQueueProcessor() {
  console.log('Starting GPU-aware queue processor...');
  
  while (true) {
    try {
      // Check GPU status before processing
      const gpuStatus = await checkGPUStatus();
      console.log(`GPU Status: ${gpuStatus.memoryPercent.toFixed(1)}% used, Available: ${gpuStatus.available}`);
      
      if (!gpuStatus.available) {
        console.log(`GPU under high load (${gpuStatus.memoryPercent.toFixed(1)}%), waiting...`);
        await new Promise(resolve => setTimeout(resolve, BACKPRESSURE_DELAY));
        continue;
      }
      
      const job = await db.getNextPendingJob();
      
      if (job) {
        // Check rate limits for job type
        if (!canProcessJobType(job.type)) {
          console.log(`Rate limit reached for ${job.type}, skipping`);
          await new Promise(resolve => setTimeout(resolve, 3000));
          continue;
        }
        
        console.log(`Processing job ${job.id}: ${job.type}`);
        await db.updateJobStatus(job.id, 'running');
        
        try {
          if (job.type === 'imagen2') {
            await orchestrator.processImagen2Job(job);
          } else if (job.type === 'txt2vid') {
            await orchestrator.processTxt2vidJob(job);
          } else if (job.type === 'embedding') {
            await orchestrator.processEmbeddingJob(job);
          } else if (job.type === 'llama') {
            await orchestrator.processLlamaJob(job);
          } else if (job.type === 'yomi_summary') {
            await orchestrator.processYomiSummaryJob(job);
          } else if (job.type === 'yomi_daily') {
            await orchestrator.processYomiDailyJob(job);
          } else if (job.type === 'yomi_daily_batch') {
            await orchestrator.processYomiDailyBatchJob(job);
          } else {
            console.log(`Unknown job type: ${job.type}`);
            await db.updateJobStatus(job.id, 'failed', `Unknown job type: ${job.type}`);
          }
          
          // Mark job type as processed
          markJobTypeProcessed(job.type);
          
          // Reset failure counter on success
          consecutiveFailures = 0;
        } catch (error) {
          consecutiveFailures++;
          console.error(`Job ${job.id} processing failed (attempt ${consecutiveFailures}/${MAX_CONSECUTIVE_FAILURES}):`, error);
          
          // Implement circuit breaker
          if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
            console.log(`Circuit breaker triggered after ${consecutiveFailures} failures, waiting ${BACKPRESSURE_DELAY/1000}s`);
            await new Promise(resolve => setTimeout(resolve, BACKPRESSURE_DELAY));
            consecutiveFailures = 0;
          }
          
          await db.updateJobStatus(job.id, 'failed', error.message);
        }
      }
      
      // Adaptive wait time based on GPU load
      const waitTime = gpuStatus.memoryPercent > 60 ? 10000 : 5000;
      await new Promise(resolve => setTimeout(resolve, waitTime));
    } catch (error) {
      console.error('Queue processor error:', error);
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
  }
}

// Start queue processor in background
startQueueProcessor().catch(error => {
  console.error('Queue processor failed:', error);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('Shutting down...');
  await db.closePool();
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});

process.on('SIGINT', async () => {
  console.log('Shutting down...');
  await db.closePool();
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});
