#!/usr/bin/env node

/**
 * Migration script to add missing columns to gpu_queue_jobs table
 * This adds columns that were added to schema.sql but may be missing from existing databases
 */

import pg from 'pg';

const { Pool } = pg;

const DATABASE_URL = process.env.DATABASE_URL || 'postgres://chaba:chabapass@localhost:5432/chaba';

const pool = new Pool({
  connectionString: DATABASE_URL,
});

async function migrate() {
  const client = await pool.connect();
  
  try {
    console.log('Starting migration: Add missing columns to gpu_queue_jobs table');
    
    // Check current columns
    const columnsResult = await client.query(`
      SELECT column_name, data_type 
      FROM information_schema.columns 
      WHERE table_name = 'gpu_queue_jobs'
      ORDER BY ordinal_position;
    `);
    
    const existingColumns = columnsResult.rows.map(row => row.column_name);
    console.log('Existing columns:', existingColumns);
    
    // Columns to add (from schema.sql)
    const columnsToAdd = [
      { name: 'execution_time_ms', type: 'INTEGER' },
      { name: 'gpu_used', type: 'BOOLEAN', default: 'false' },
      { name: 'vram_used_mb', type: 'INTEGER' },
      { name: 'mode', type: 'VARCHAR(10)' },
      { name: 'batch_size', type: 'INTEGER', default: '1' },
      { name: 'queue_wait_time_ms', type: 'INTEGER' },
      { name: 'result', type: 'JSONB' },
      { name: 'embedding_dimensions', type: 'INTEGER' },
      { name: 'embedding_model', type: 'VARCHAR(100)' },
      { name: 'text_count', type: 'INTEGER', default: '1' }
    ];
    
    let addedCount = 0;
    
    for (const column of columnsToAdd) {
      if (!existingColumns.includes(column.name)) {
        const defaultClause = column.default ? ` DEFAULT ${column.default}` : '';
        const alterSQL = `ALTER TABLE gpu_queue_jobs ADD COLUMN IF NOT EXISTS ${column.name} ${column.type}${defaultClause}`;
        
        console.log(`Adding column: ${column.name}`);
        await client.query(alterSQL);
        addedCount++;
      } else {
        console.log(`Column already exists: ${column.name}`);
      }
    }
    
    console.log(`Migration complete. Added ${addedCount} columns.`);
    
    // Verify final schema
    const finalColumns = await client.query(`
      SELECT column_name, data_type 
      FROM information_schema.columns 
      WHERE table_name = 'gpu_queue_jobs'
      ORDER BY ordinal_position;
    `);
    
    console.log('Final columns:', finalColumns.rows.map(row => row.column_name));
    
  } catch (error) {
    console.error('Migration failed:', error);
    throw error;
  } finally {
    client.release();
    await pool.end();
  }
}

migrate().then(() => {
  console.log('Migration completed successfully');
  process.exit(0);
}).catch((error) => {
  console.error('Migration failed:', error);
  process.exit(1);
});
