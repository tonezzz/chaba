#!/usr/bin/env node
import { pool } from './db.mjs';

async function addMissingColumns() {
  const client = await pool.connect();
  try {
    // Check if execution_time_ms column exists
    const checkExecTime = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'execution_time_ms'
    `);

    if (checkExecTime.rows.length === 0) {
      console.log('Adding execution_time_ms column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN execution_time_ms INTEGER
      `);
      console.log('✓ execution_time_ms column added');
    } else {
      console.log('✓ execution_time_ms column already exists');
    }

    // Check if embedding_dimensions column exists
    const checkEmbeddingDim = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'embedding_dimensions'
    `);

    if (checkEmbeddingDim.rows.length === 0) {
      console.log('Adding embedding_dimensions column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN embedding_dimensions INTEGER
      `);
      console.log('✓ embedding_dimensions column added');
    } else {
      console.log('✓ embedding_dimensions column already exists');
    }

    // Check if embedding_model column exists
    const checkEmbeddingModel = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'embedding_model'
    `);

    if (checkEmbeddingModel.rows.length === 0) {
      console.log('Adding embedding_model column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN embedding_model VARCHAR(100)
      `);
      console.log('✓ embedding_model column added');
    } else {
      console.log('✓ embedding_model column already exists');
    }

    // Check if text_count column exists
    const checkTextCount = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'text_count'
    `);

    if (checkTextCount.rows.length === 0) {
      console.log('Adding text_count column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN text_count INTEGER DEFAULT 1
      `);
      console.log('✓ text_count column added');
    } else {
      console.log('✓ text_count column already exists');
    }

    // Check if gpu_used column exists
    const checkGpuUsed = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'gpu_used'
    `);

    if (checkGpuUsed.rows.length === 0) {
      console.log('Adding gpu_used column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN gpu_used BOOLEAN DEFAULT false
      `);
      console.log('✓ gpu_used column added');
    } else {
      console.log('✓ gpu_used column already exists');
    }

    // Check if vram_used_mb column exists
    const checkVramUsed = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'vram_used_mb'
    `);

    if (checkVramUsed.rows.length === 0) {
      console.log('Adding vram_used_mb column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN vram_used_mb INTEGER
      `);
      console.log('✓ vram_used_mb column added');
    } else {
      console.log('✓ vram_used_mb column already exists');
    }

    // Check if mode column exists
    const checkMode = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'mode'
    `);

    if (checkMode.rows.length === 0) {
      console.log('Adding mode column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN mode VARCHAR(10)
      `);
      console.log('✓ mode column added');
    } else {
      console.log('✓ mode column already exists');
    }

    // Check if batch_size column exists
    const checkBatchSize = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'batch_size'
    `);

    if (checkBatchSize.rows.length === 0) {
      console.log('Adding batch_size column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN batch_size INTEGER DEFAULT 1
      `);
      console.log('✓ batch_size column added');
    } else {
      console.log('✓ batch_size column already exists');
    }

    // Check if queue_wait_time_ms column exists
    const checkQueueWait = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'queue_wait_time_ms'
    `);

    if (checkQueueWait.rows.length === 0) {
      console.log('Adding queue_wait_time_ms column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN queue_wait_time_ms INTEGER
      `);
      console.log('✓ queue_wait_time_ms column added');
    } else {
      console.log('✓ queue_wait_time_ms column already exists');
    }

    // Check if result column exists
    const checkResultColumn = await client.query(`
      SELECT column_name
      FROM information_schema.columns
      WHERE table_name = 'gpu_queue_jobs'
      AND column_name = 'result'
    `);

    if (checkResultColumn.rows.length === 0) {
      console.log('Adding result column...');
      await client.query(`
        ALTER TABLE gpu_queue_jobs
        ADD COLUMN result JSONB
      `);
      console.log('✓ result column added');
    } else {
      console.log('✓ result column already exists');
    }

    console.log('\nAll required columns are present!');
  } catch (error) {
    console.error('Error adding columns:', error);
  } finally {
    client.release();
    await pool.end();
  }
}

addMissingColumns();