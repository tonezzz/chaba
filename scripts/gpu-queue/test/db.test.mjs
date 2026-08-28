import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import * as db from '../db.mjs';

describe('db.mjs', () => {
  // db.mjs initializes pool on module load, no initPool needed

  it('should create a job', async () => {
    const job = await db.createJob('imagen2', { prompt: 'test' });
    assert.ok(job.id);
    assert.strictEqual(job.type, 'imagen2');
    assert.strictEqual(job.status, 'pending');
  });

  it('should get a job by id', async () => {
    const created = await db.createJob('llama', { prompt: 'test' });
    const job = await db.getJob(created.id);
    assert.strictEqual(job.id, created.id);
    assert.strictEqual(job.type, 'llama');
  });

  it('should list jobs', async () => {
    await db.createJob('txt2vid', { prompt: 'test' });
    const jobs = await db.listJobs();
    assert.ok(Array.isArray(jobs));
    assert.ok(jobs.length > 0);
  });

  it('should get next pending job with priority', async () => {
    // Create jobs with different priorities
    await db.createJob('llama', { prompt: 'low priority' });
    await db.createJob('imagen2', { prompt: 'medium priority' });
    await db.createJob('txt2vid', { prompt: 'high priority' });

    const job = await db.getNextPendingJob();
    assert.ok(job);
    // txt2vid has highest priority (0)
    assert.strictEqual(job.type, 'txt2vid');
  });

  it('should update job status', async () => {
    const job = await db.createJob('imagen2', { prompt: 'test' });
    await db.updateJobStatus(job.id, 'running');
    const updated = await db.getJob(job.id);
    assert.strictEqual(updated.status, 'running');
    assert.ok(updated.started_at);
  });

  it('should get queue status', async () => {
    const status = await db.getQueueStatus();
    assert.ok(status);
    assert.ok(typeof status.pending === 'number');
    assert.ok(typeof status.running === 'number');
    assert.ok(typeof status.completed === 'number');
  });

  it('should cancel a job', async () => {
    const job = await db.createJob('imagen2', { prompt: 'test' });
    await db.cancelJob(job.id);
    const cancelled = await db.getJob(job.id);
    assert.strictEqual(cancelled.status, 'cancelled');
  });
});
