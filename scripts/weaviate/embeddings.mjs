/**
 * Embedding Generation Module
 * 
 * Generates embeddings using local embedding service or OpenAI API
 * Supports both CPU and GPU modes for comparative testing
 */

const EMBEDDING_SERVICE_URL = process.env.EMBEDDING_SERVICE_URL || 'http://localhost:5000';
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const EMBEDDING_MODEL = 'text-embedding-3-small'; // 1536 dimensions, cost-effective
const LOCAL_MODEL_DIM = 384; // all-MiniLM-L6-v2 dimension

/**
 * Generate embedding for text using local service or OpenAI
 * @param {string} text - Text to embed
 * @param {string} mode - 'cpu', 'gpu', or 'auto'
 * @returns {Promise<number[]>} - Vector embedding
 */
export async function generateEmbedding(text, mode = 'auto') {
  // Try local service first (unless OpenAI is explicitly preferred)
  if (mode !== 'openai' && EMBEDDING_SERVICE_URL) {
    try {
      const response = await fetch(`${EMBEDDING_SERVICE_URL}/embed-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log(`Generated embedding using local service (${(data.time_seconds * 1000).toFixed(0)}ms)`);
        return data.embedding;
      }
    } catch (error) {
      console.warn('Local embedding service failed, falling back to OpenAI:', error.message);
    }
  }

  // Fallback to OpenAI
  if (OPENAI_API_KEY) {
    try {
      const response = await fetch('https://api.openai.com/v1/embeddings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${OPENAI_API_KEY}`,
        },
        body: JSON.stringify({
          model: EMBEDDING_MODEL,
          input: text,
        }),
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`OpenAI API error: ${error}`);
      }

      const data = await response.json();
      console.log('Generated embedding using OpenAI API');
      return data.data[0].embedding;
    } catch (error) {
      console.error('Error generating embedding with OpenAI:', error);
      throw error;
    }
  }

  throw new Error('No embedding service available (local service failed and no OpenAI API key)');
}

/**
 * Generate embeddings for multiple texts (batch processing)
 * @param {string[]} texts - Array of texts to embed
 * @param {string} mode - 'cpu', 'gpu', or 'auto'
 * @returns {Promise<number[][]>} - Array of vector embeddings
 */
export async function generateEmbeddings(texts, mode = 'auto') {
  // Try local service first
  if (mode !== 'openai' && EMBEDDING_SERVICE_URL) {
    try {
      const response = await fetch(`${EMBEDDING_SERVICE_URL}/embed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log(`Generated ${data.count} embeddings using local service (${(data.time_seconds * 1000).toFixed(0)}ms)`);
        return data.embeddings;
      }
    } catch (error) {
      console.warn('Local embedding service failed, falling back to OpenAI:', error.message);
    }
  }

  // Fallback to OpenAI
  if (OPENAI_API_KEY) {
    try {
      const response = await fetch('https://api.openai.com/v1/embeddings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${OPENAI_API_KEY}`,
        },
        body: JSON.stringify({
          model: EMBEDDING_MODEL,
          input: texts,
        }),
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`OpenAI API error: ${error}`);
      }

      const data = await response.json();
      console.log(`Generated ${texts.length} embeddings using OpenAI API`);
      return data.data.map(item => item.embedding);
    } catch (error) {
      console.error('Error generating embeddings with OpenAI:', error);
      throw error;
    }
  }

  throw new Error('No embedding service available (local service failed and no OpenAI API key)');
}

/**
 * Get embedding dimension based on current service
 * @returns {Promise<number>} - Embedding dimension
 */
export async function getEmbeddingDimension() {
  // Try local service first
  if (EMBEDDING_SERVICE_URL) {
    try {
      const response = await fetch(`${EMBEDDING_SERVICE_URL}/model-info`);
      if (response.ok) {
        const data = await response.json();
        return data.dimensions;
      }
    } catch (error) {
      console.warn('Failed to get local model info:', error.message);
    }
  }

  // Fallback to OpenAI dimension
  return 1536; // text-embedding-3-small dimension
}
