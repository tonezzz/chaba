import * as db from './db.mjs';

/**
 * Get queue health status
 */
export async function getQueueHealth() {
  try {
    const status = await db.getQueueStatus();
    const runningJob = await db.getRunningJob();
    const jobTypeBreakdown = await db.getJobTypeBreakdown();
    const priorityDistribution = await db.getPriorityDistribution();

    return {
      ok: true,
      status: status,
      running_job: runningJob ? {
        id: runningJob.id,
        type: runningJob.type,
        started_at: runningJob.started_at
      } : null,
      job_type_breakdown: jobTypeBreakdown,
      priority_distribution: priorityDistribution,
      timestamp: new Date().toISOString()
    };
  } catch (error) {
    return {
      ok: false,
      error: error.message,
      timestamp: new Date().toISOString()
    };
  }
}

/**
 * Get performance metrics
 */
export async function getPerformanceMetrics() {
  try {
    const recentJobs = await db.getRecentJobs(10);
    
    // Calculate success rate
    const completedCount = recentJobs.filter(j => j.status === 'completed').length;
    const successRate = recentJobs.length > 0 
      ? (completedCount / recentJobs.length * 100).toFixed(2) 
      : 0;

    // Calculate average execution time from recent jobs
    const jobsWithTime = recentJobs.filter(j => j.started_at && j.completed_at);
    const avgTime = jobsWithTime.length > 0
      ? jobsWithTime.reduce((sum, job) => {
          const time = new Date(job.completed_at) - new Date(job.started_at);
          return sum + time;
        }, 0) / jobsWithTime.length
      : 0;

    return {
      ok: true,
      recent_average_time_ms: Math.round(avgTime),
      success_rate_percent: parseFloat(successRate),
      recent_jobs_count: recentJobs.length,
      timestamp: new Date().toISOString()
    };
  } catch (error) {
    return {
      ok: false,
      error: error.message,
      timestamp: new Date().toISOString()
    };
  }
}

/**
 * Get recent activity
 */
export async function getRecentActivity(limit = 20) {
  try {
    const recentJobs = await db.getRecentJobs(limit);
    
    return {
      ok: true,
      jobs: recentJobs.map(job => ({
        id: job.id,
        type: job.type,
        status: job.status,
        created_at: job.created_at,
        started_at: job.started_at,
        completed_at: job.completed_at,
        error: job.error
      })),
      count: recentJobs.length,
      timestamp: new Date().toISOString()
    };
  } catch (error) {
    return {
      ok: false,
      error: error.message,
      timestamp: new Date().toISOString()
    };
  }
}

/**
 * Get system overview
 */
export async function getSystemOverview() {
  try {
    const status = await db.getQueueStatus();
    const jobTypeBreakdown = await db.getJobTypeBreakdown();
    const recentJobs = await db.getRecentJobs(5);

    // Calculate total jobs
    const totalJobs = Object.values(status).reduce((sum, count) => sum + count, 0);

    // Calculate success rate from recent jobs
    const completedCount = recentJobs.filter(j => j.status === 'completed').length;
    const successRate = recentJobs.length > 0 
      ? (completedCount / recentJobs.length * 100).toFixed(2) 
      : 0;

    // Calculate average execution time from recent jobs
    const jobsWithTime = recentJobs.filter(j => j.started_at && j.completed_at);
    const avgTime = jobsWithTime.length > 0
      ? jobsWithTime.reduce((sum, job) => {
          const time = new Date(job.completed_at) - new Date(job.started_at);
          return sum + time;
        }, 0) / jobsWithTime.length
      : 0;

    return {
      ok: true,
      queue_status: status,
      total_jobs: totalJobs,
      job_type_breakdown: jobTypeBreakdown,
      recent_activity: recentJobs.map(job => ({
        id: job.id,
        type: job.type,
        status: job.status,
        completed_at: job.completed_at
      })),
      performance: {
        recent_average_time_ms: Math.round(avgTime),
        success_rate_percent: parseFloat(successRate)
      },
      timestamp: new Date().toISOString()
    };
  } catch (error) {
    return {
      ok: false,
      error: error.message,
      timestamp: new Date().toISOString()
    };
  }
}
