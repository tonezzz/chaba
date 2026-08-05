#!/usr/bin/env node

import pg from 'pg';

const { Pool } = pg;

const DATABASE_URL = process.env.DATABASE_URL || 'postgres://chaba:chabapass@localhost:5432/chaba';

const pool = new Pool({
  connectionString: DATABASE_URL,
});

async function cleanOldErrors() {
  const client = await pool.connect();
  
  try {
    console.log('Cleaning up old error jobs with schema-related errors...');
    
    // Update jobs that failed due to missing columns to mark them as resolved
    // These were historical failures before schema was updated
    const result = await client.query(`
      UPDATE gpu_queue_jobs 
      SET error = 'Historical schema error - resolved by migration', 
          status = 'cancelled'
      WHERE error LIKE '%column "%" of relation "gpu_queue_jobs" does not exist%'
      RETURNING id, type, error
    `);
    
    console.log(`Updated ${result.rows.length} historical error jobs:`);
    result.rows.forEach(row => {
      console.log(`  ID: ${row.id}, Type: ${row.type}`);
    });
    
    console.log('Cleanup complete.');
    
  } catch (error) {
    console.error('Cleanup failed:', error);
    throw error;
  } finally {
    client.release();
    await pool.end();
  }
}

cleanOldErrors().then(() => {
  console.log('Cleanup completed successfully');
  process.exit(0);
}).catch((error) => {
  console.error('Cleanup failed:', error);
  process.exit(1);
});
