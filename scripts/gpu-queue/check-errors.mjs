#!/usr/bin/env node

import pg from 'pg';

const { Pool } = pg;

const DATABASE_URL = process.env.DATABASE_URL || 'postgres://chaba:chabapass@localhost:5432/chaba';

const pool = new Pool({
  connectionString: DATABASE_URL,
});

async function checkErrors() {
  try {
    const result = await pool.query(`
      SELECT id, type, status, error, created_at 
      FROM gpu_queue_jobs 
      WHERE error IS NOT NULL 
      ORDER BY created_at DESC 
      LIMIT 5
    `);
    
    console.log('Recent errors:');
    result.rows.forEach(row => {
      console.log(`ID: ${row.id}, Type: ${row.type}, Status: ${row.status}`);
      console.log(`Error: ${row.error}`);
      console.log(`Created: ${row.created_at}`);
      console.log('---');
    });
    
  } catch (error) {
    console.error('Error checking database:', error);
  } finally {
    await pool.end();
  }
}

checkErrors();
