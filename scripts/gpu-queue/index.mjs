import http from 'http';
import * as db from './db.mjs';
import * as queue from './queue.mjs';
import * as monitoring from './monitoring.mjs';

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

      const validTypes = ['llama', 'imagen2', 'txt2vid', 'embedding'];
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
  console.log('  POST   /api/gpu-queue/jobs        - Submit job');
  console.log('  GET    /api/gpu-queue/jobs        - List jobs');
  console.log('  GET    /api/gpu-queue/jobs/:id    - Get job status');
  console.log('  DELETE /api/gpu-queue/jobs/:id    - Cancel job');
  console.log('  GET    /api/gpu-queue/status      - Queue status');
  console.log('  GET    /api/gpu-queue/monitoring/health      - Monitoring health');
  console.log('  GET    /api/gpu-queue/monitoring/performance  - Monitoring performance');
  console.log('  GET    /api/gpu-queue/monitoring/activity     - Monitoring activity');
  console.log('  GET    /api/gpu-queue/monitoring/overview     - Monitoring overview');
  console.log('  GET    /health                    - Health check');
  console.log('');
  console.log('Note: Queue processor disabled. Use orchestrator.mjs to process jobs with MCP tools.');
});

// Queue processor disabled - use orchestrator.mjs instead
// queue.startQueueProcessor().catch(error => {
//   console.error('Queue processor failed:', error);
// });

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
