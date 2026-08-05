#!/usr/bin/env node
/**
 * GPU Queue Monitoring Summary
 * Generates a comprehensive monitoring report for the GPU Queue system
 */

import * as db from './db.mjs';

async function generateMonitoringReport() {
  console.log('='.repeat(60));
  console.log('GPU Queue Monitoring Report');
  console.log('='.repeat(60));
  console.log();

  // Get overall queue status
  const status = await db.getQueueStatus();
  console.log('Queue Status:');
  console.log(`  Pending:   ${status.pending}`);
  console.log(`  Running:   ${status.running}`);
  console.log(`  Completed: ${status.completed}`);
  console.log(`  Failed:    ${status.failed}`);
  console.log(`  Cancelled: ${status.cancelled}`);
  console.log();

  // Get job statistics (24 hours)
  const stats = await db.getJobStats(24);
  console.log('Job Statistics (24 hours):');
  if (stats.length === 0) {
    console.log('  No jobs in the last 24 hours');
  } else {
    stats.forEach(stat => {
      console.log(`  ${stat.type} - ${stat.status}:`);
      console.log(`    Count: ${stat.count}`);
      if (stat.avg_execution_time_ms) {
        console.log(`    Avg Execution: ${Math.round(stat.avg_execution_time_ms)}ms`);
      }
      if (stat.avg_queue_wait_time_ms) {
        console.log(`    Avg Queue Wait: ${Math.round(stat.avg_queue_wait_time_ms)}ms`);
      }
      if (stat.avg_retry_count) {
        console.log(`    Avg Retries: ${parseFloat(stat.avg_retry_count).toFixed(2)}`);
      }
    });
  }
  console.log();

  // Get cancellation rate
  const cancellationRate = await db.getCancellationRate(24);
  console.log('Cancellation Rate (24 hours):');
  if (cancellationRate.length === 0) {
    console.log('  No jobs in the last 24 hours');
  } else {
    cancellationRate.forEach(rate => {
      console.log(`  ${rate.type}:`);
      console.log(`    Total: ${rate.total}`);
      console.log(`    Completed: ${rate.completed}`);
      console.log(`    Failed: ${rate.failed}`);
      console.log(`    Cancelled: ${rate.cancelled}`);
      console.log(`    Cancellation Rate: ${rate.cancellation_rate}%`);
    });
  }
  console.log();

  // Get recent failures
  const failures = await db.getRecentFailures(5);
  console.log('Recent Failures (last 5):');
  if (failures.length === 0) {
    console.log('  No recent failures');
  } else {
    failures.forEach(failure => {
      console.log(`  Job ${failure.id} (${failure.type}):`);
      console.log(`    Status: ${failure.status}`);
      console.log(`    Error: ${failure.error || 'None'}`);
      console.log(`    Created: ${failure.created_at}`);
      console.log(`    Retries: ${failure.retry_count}`);
    });
  }
  console.log();

  // Get job type breakdown
  const breakdown = await db.getJobTypeBreakdown();
  console.log('Job Type Breakdown:');
  Object.entries(breakdown).forEach(([type, counts]) => {
    console.log(`  ${type}:`);
    Object.entries(counts).forEach(([status, count]) => {
      console.log(`    ${status}: ${count}`);
    });
  });
  console.log();

  // Get priority distribution
  const priorityDist = await db.getPriorityDistribution();
  console.log('Priority Distribution (pending jobs):');
  if (Object.keys(priorityDist).length === 0) {
    console.log('  No pending jobs');
  } else {
    Object.entries(priorityDist).forEach(([priority, count]) => {
      console.log(`  Priority ${priority}: ${count} jobs`);
    });
  }
  console.log();

  console.log('='.repeat(60));
  console.log('Report generated successfully');
  console.log('='.repeat(60));
}

// Run the report
generateMonitoringReport().catch(error => {
  console.error('Error generating monitoring report:', error);
  process.exit(1);
});
