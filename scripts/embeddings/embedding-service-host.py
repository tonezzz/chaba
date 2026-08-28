#!/usr/bin/env python3
"""
Simple CPU-based embedding service using sentence-transformers
Runs on host without Docker to avoid dependency complexity
"""

from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import numpy as np
import time
import os

app = Flask(__name__)

# Global model variable
model = None
model_name = os.environ.get('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')

def load_model():
    """Load the embedding model"""
    global model
    if model is None:
        print(f"Loading model: {model_name}")
        model = SentenceTransformer(model_name)
        print(f"Model loaded successfully. Dimensions: {model.get_sentence_embedding_dimension()}")
    return model

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'model': model_name})

@app.route('/model-info', methods=['GET'])
def model_info():
    """Get model information"""
    model = load_model()
    return jsonify({
        'model_name': model_name,
        'dimensions': model.get_sentence_embedding_dimension(),
        'max_seq_length': model.max_seq_length
    })

@app.route('/embed', methods=['POST'])
def embed():
    """Generate embeddings for texts"""
    try:
        data = request.json
        texts = data.get('texts', [])
        
        if not texts:
            return jsonify({'error': 'No texts provided'}), 400
        
        # Load model if not loaded
        model = load_model()
        
        # Generate embeddings
        start_time = time.time()
        embeddings = model.encode(texts, convert_to_numpy=True)
        elapsed_time = time.time() - start_time
        
        # Convert to list for JSON serialization
        embeddings_list = embeddings.tolist()
        
        return jsonify({
            'embeddings': embeddings_list,
            'dimensions': len(embeddings_list[0]) if embeddings_list else 0,
            'count': len(texts),
            'time_seconds': elapsed_time,
            'model': model_name
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/embed-single', methods=['POST'])
def embed_single():
    """Generate embedding for a single text"""
    try:
        data = request.json
        text = data.get('text', '')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        # Load model if not loaded
        model = load_model()
        
        # Generate embedding
        start_time = time.time()
        embedding = model.encode([text], convert_to_numpy=True)[0]
        elapsed_time = time.time() - start_time
        
        # Convert to list for JSON serialization
        embedding_list = embedding.tolist()
        
        return jsonify({
            'embedding': embedding_list,
            'dimensions': len(embedding_list),
            'time_seconds': elapsed_time,
            'model': model_name
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting embedding service on port {port}")
    print(f"Model: {model_name}")
    
    # Pre-load model
    load_model()
    
    app.run(host='0.0.0.0', port=port, debug=False)