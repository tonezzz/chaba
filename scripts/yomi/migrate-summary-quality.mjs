import pool from './db.mjs';

async function migrateSummaryQuality() {
  try {
    console.log('Starting summary quality migration...');
    
    // Add new columns for summary quality tracking
    await pool.query(`
      ALTER TABLE conversations 
      ADD COLUMN IF NOT EXISTS summary_quality INTEGER,
      ADD COLUMN IF NOT EXISTS summary_generated_at TIMESTAMP,
      ADD COLUMN IF NOT EXISTS summary_retry_count INTEGER DEFAULT 0,
      ADD COLUMN IF NOT EXISTS summary_error_message TEXT
    `);
    
    console.log('✓ Added summary quality columns');
    
    // Create index on summary_quality for faster queries
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_conversations_summary_quality 
      ON conversations(summary_quality)
    `);
    
    console.log('✓ Created summary_quality index');
    
    // Initialize existing summaries with quality scores
    const { rows: conversations } = await pool.query(`
      SELECT chat_id, summary 
      FROM conversations 
      WHERE summary IS NOT NULL AND summary != ''
    `);
    
    console.log(`Evaluating quality for ${conversations.length} existing summaries...`);
    
    let updated = 0;
    for (const conv of conversations) {
      const quality = evaluateSummaryQuality(conv.summary);
      await pool.query(`
        UPDATE conversations 
        SET summary_quality = $1, summary_generated_at = COALESCE(summary_generated_at, updated_at)
        WHERE chat_id = $2
      `, [quality, conv.chat_id]);
      updated++;
    }
    
    console.log(`✓ Updated quality scores for ${updated} summaries`);
    
    await pool.end();
    console.log('Migration completed successfully!');
  } catch (error) {
    console.error('Migration failed:', error);
    process.exit(1);
  }
}

function evaluateSummaryQuality(summary) {
  if (!summary || summary.trim() === '') return 0;
  
  const text = summary.trim();
  const length = text.length;
  
  // Check for generic error messages
  const errorPatterns = [
    /conversation unavailable/i,
    /no summary possible/i,
    /no available conversation/i,
    /unable to provide/i,
    /service unavailable/i,
    /unanswerable/i
  ];
  
  for (const pattern of errorPatterns) {
    if (pattern.test(text)) return 0;
  }
  
  // Quality scoring based on length and content
  if (length < 10) return 10; // Very short
  if (length < 20) return 30; // Short
  if (length < 50) return 60; // Medium
  if (length < 100) return 80; // Good
  return 100; // Excellent
}

migrateSummaryQuality();