#!/usr/bin/env python3
"""
CPU-only Embedding Service for Weaviate
Provides text embeddings using sentence-transformers on CPU
"""

from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import os
import logging
import time
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Model configuration
MODEL_NAME = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '32'))
MAX_TEXT_LENGTH = int(os.getenv('MAX_TEXT_LENGTH', '512'))

# Load model (CPU-only)
logger.info(f"Loading model: {MODEL_NAME}")
model = SentenceTransformer(MODEL_NAME)
logger.info(f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'model': MODEL_NAME,
        'dimension': model.get_sentence_embedding_dimension(),
        'batch_size': BATCH_SIZE
    })

@app.route('/embed', methods=['POST'])
def embed():
    """Generate embeddings for texts"""
    try:
        data = request.json
        texts = data.get('texts', [])
        
        if not texts:
            return jsonify({'error': 'No texts provided'}), 400
        
        if isinstance(texts, str):
            texts = [texts]
        
        logger.info(f"Generating embeddings for {len(texts)} texts")
        
        start_time = time.time()
        
        # Generate embeddings
        embeddings = model.encode(
            texts,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True
        )
        
        end_time = time.time()
        execution_time = (end_time - start_time) * 1000  # Convert to ms
        
        # Convert to list for JSON serialization
        embeddings_list = embeddings.tolist()
        
        result = {
            'embeddings': embeddings_list,
            'dimension': model.get_sentence_embedding_dimension(),
            'count': len(texts),
            'execution_time_ms': execution_time,
            'mode': 'cpu'
        }
        
        logger.info(f"Generated {len(texts)} embeddings in {execution_time:.2f}ms")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/embed/single', methods=['POST'])
def embed_single():
    """Generate embedding for single text (simpler interface)"""
    try:
        data = request.json
        text = data.get('text', '')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        logger.info(f"Generating embedding for text (length: {len(text)})")
        
        start_time = time.time()
        
        # Generate embedding
        embedding = model.encode(
            text,
            show_progress_bar=False,
            convert_to_numpy=True
        )
        
        end_time = time.time()
        execution_time = (end_time - start_time) * 1000  # Convert to ms
        
        result = {
            'embedding': embedding.tolist(),
            'dimension': model.get_sentence_embedding_dimension(),
            'execution_time_ms': execution_time,
            'mode': 'cpu'
        }
        
        logger.info(f"Generated embedding in {execution_time:.2f}ms")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/model-info', methods=['GET'])
def model_info():
    """Get model information"""
    return jsonify({
        'model_name': MODEL_NAME,
        'dimension': model.get_sentence_embedding_dimension(),
        'max_seq_length': MAX_TEXT_LENGTH,
        'batch_size': BATCH_SIZE,
        'mode': 'cpu'
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting embedding service on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
