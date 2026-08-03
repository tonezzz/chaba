#!/usr/bin/env python3
"""
GPU-accelerated embedding service with VRAM management
Supports dynamic model loading/unloading and CPU fallback
"""

from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import torch
import numpy as np
import time
import os
import subprocess

app = Flask(__name__)

# Global model variables
model = None
model_name = os.environ.get('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
device = 'cuda' if torch.cuda.is_available() else 'cpu'

def check_vram_available(required_mb):
    """Check if sufficient VRAM is available"""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True
        )
        free_mb = int(result.stdout.strip())
        return free_mb >= required_mb
    except Exception as e:
        print(f"Error checking VRAM: {e}")
        return False

def get_vram_usage():
    """Get current VRAM usage in MB"""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True
        )
        return int(result.stdout.strip())
    except Exception as e:
        print(f"Error getting VRAM usage: {e}")
        return 0

def load_model(force_device=None):
    """Load the embedding model on specified device"""
    global model
    target_device = force_device or device
    
    if model is None:
        print(f"Loading model: {model_name} on {target_device}")
        
        # Check VRAM if trying to use GPU
        if target_device == 'cuda':
            # Estimate VRAM requirement based on model
            if 'MiniLM' in model_name:
                required_mb = 700
            elif 'SEA-LION' in model_name:
                required_mb = 1500
            else:
                required_mb = 1000
            
            if not check_vram_available(required_mb):
                print(f"Insufficient VRAM for GPU, falling back to CPU")
                target_device = 'cpu'
        
        model = SentenceTransformer(model_name)
        model.to(target_device)
        print(f"Model loaded successfully on {target_device}. Dimensions: {model.get_embedding_dimension()}")
        
        if target_device == 'cuda':
            vram_usage = get_vram_usage()
            print(f"Current VRAM usage: {vram_usage}MB")
    
    return model, target_device

def unload_model():
    """Unload the model to free VRAM"""
    global model
    if model is not None:
        vram_before = get_vram_usage() if device == 'cuda' else 0
        del model
        model = None
        torch.cuda.empty_cache()
        vram_after = get_vram_usage() if device == 'cuda' else 0
        print(f"Model unloaded. VRAM freed: {vram_before - vram_after}MB")

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'model': model_name,
        'device': device,
        'model_loaded': model is not None
    })

@app.route('/model-info', methods=['GET'])
def model_info():
    """Get model information"""
    model, current_device = load_model()
    vram_usage = get_vram_usage() if current_device == 'cuda' else 0
    
    return jsonify({
        'model_name': model_name,
        'dimensions': model.get_embedding_dimension(),
        'max_seq_length': model.max_seq_length,
        'device': current_device,
        'vram_usage_mb': vram_usage,
        'cuda_available': torch.cuda.is_available()
    })

@app.route('/embed', methods=['POST'])
def embed():
    """Generate embeddings for texts"""
    try:
        data = request.json
        texts = data.get('texts', [])
        use_gpu = data.get('use_gpu', True)
        
        if not texts:
            return jsonify({'error': 'No texts provided'}), 400
        
        # Determine device
        target_device = 'cuda' if (use_gpu and torch.cuda.is_available()) else 'cpu'
        
        # Load model
        model, actual_device = load_model(target_device)
        
        # Generate embeddings
        start_time = time.time()
        embeddings = model.encode(texts, convert_to_numpy=True, device=actual_device)
        elapsed_time = time.time() - start_time
        
        # Get VRAM usage if GPU
        vram_usage = get_vram_usage() if actual_device == 'cuda' else 0
        
        # Convert to list for JSON serialization
        embeddings_list = embeddings.tolist()
        
        return jsonify({
            'embeddings': embeddings_list,
            'dimensions': len(embeddings_list[0]) if embeddings_list else 0,
            'count': len(texts),
            'time_seconds': elapsed_time,
            'model': model_name,
            'device': actual_device,
            'vram_usage_mb': vram_usage
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/embed-single', methods=['POST'])
def embed_single():
    """Generate embedding for a single text"""
    try:
        data = request.json
        text = data.get('text', '')
        use_gpu = data.get('use_gpu', True)
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        # Determine device
        target_device = 'cuda' if (use_gpu and torch.cuda.is_available()) else 'cpu'
        
        # Load model
        model, actual_device = load_model(target_device)
        
        # Generate embedding
        start_time = time.time()
        embedding = model.encode([text], convert_to_numpy=True, device=actual_device)[0]
        elapsed_time = time.time() - start_time
        
        # Get VRAM usage if GPU
        vram_usage = get_vram_usage() if actual_device == 'cuda' else 0
        
        # Convert to list for JSON serialization
        embedding_list = embedding.tolist()
        
        return jsonify({
            'embedding': embedding_list,
            'dimensions': len(embedding_list),
            'time_seconds': elapsed_time,
            'model': model_name,
            'device': actual_device,
            'vram_usage_mb': vram_usage
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/unload', methods=['POST'])
def unload():
    """Unload the model to free VRAM"""
    try:
        unload_model()
        return jsonify({'status': 'unloaded'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting GPU embedding service on port {port}")
    print(f"Model: {model_name}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    print(f"Default device: {device}")
    
    # Don't pre-load model - load on demand to save VRAM
    print("Model will be loaded on demand")
    
    app.run(host='0.0.0.0', port=port, debug=False)