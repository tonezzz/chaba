#!/usr/bin/env python3
"""Simple web server for BitNet inference"""

import subprocess
import json
from flask import Flask, request, render_template_string

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BitNet Test</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        h1 { color: #333; }
        textarea { width: 100%; height: 100px; padding: 10px; font-size: 14px; }
        button { padding: 10px 20px; font-size: 16px; background: #007bff; color: white; border: none; cursor: pointer; }
        button:hover { background: #0056b3; }
        .result { margin-top: 20px; padding: 15px; background: #f5f5f5; border-radius: 5px; white-space: pre-wrap; }
        .loading { color: #666; font-style: italic; }
        .error { color: #dc3545; }
        .params { margin: 10px 0; }
        .params label { margin-right: 15px; }
        .params input { width: 60px; }
    </style>
</head>
<body>
    <h1>BitNet Inference Test</h1>
    <p>Model: Falcon3-1B-Instruct-1.58bit</p>
    
    <form id="inferenceForm">
        <textarea name="prompt" placeholder="Enter your prompt here...">Explain quantum computing in simple terms</textarea>
        <div class="params">
            <label>Max tokens: <input type="number" name="max_tokens" value="100" min="10" max="500"></label>
            <label>Threads: <input type="number" name="threads" value="4" min="1" max="16"></label>
        </div>
        <button type="submit">Generate</button>
    </form>
    
    <div id="result"></div>
    
    <script>
        document.getElementById('inferenceForm').onsubmit = async function(e) {
            e.preventDefault();
            const resultDiv = document.getElementById('result');
            resultDiv.innerHTML = '<p class="loading">Generating... (this may take 10-30 seconds)</p>';
            
            const formData = new FormData(e.target);
            const params = new URLSearchParams(formData);
            
            try {
                const response = await fetch('/generate?' + params.toString());
                const data = await response.json();
                
                if (data.error) {
                    resultDiv.innerHTML = '<p class="error">Error: ' + escapeHtml(data.error) + '</p>';
                } else {
                    const tps = data.tokens_per_sec || 0;
                    const time = data.time_seconds.toFixed(2);
                    let html = '<div class="result"><strong>Output:</strong><br><br>';
                    html += escapeHtml(data.output);
                    html += '<br><br><em>Time: ' + time + 's | ';
                    html += data.tokens_generated + ' tokens | ' + tps.toFixed(2) + ' tokens/sec</em></div>';
                    resultDiv.innerHTML = html;
                }
            } catch (err) {
                resultDiv.innerHTML = '<p class="error">Error: ' + err.message + '</p>';
            }
        };
        
        function escapeHtml(text) {
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/generate')
def generate():
    import time
    start = time.time()
    
    prompt = request.args.get('prompt', 'Hello')
    max_tokens = request.args.get('max_tokens', '100')
    threads = request.args.get('threads', '4')
    
    cmd = [
        'python', 'run_inference.py',
        '-m', 'models/falcon3-1b-gguf/ggml-model-i2_s.gguf',
        '-p', prompt,
        '-n', max_tokens,
        '-t', threads
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        elapsed = time.time() - start
        
        if result.returncode != 0:
            return json.dumps({
                'error': result.stderr or 'Unknown error',
                'time_seconds': elapsed
            })
        
        # Extract output (skip loading messages)
        lines = result.stdout.split('\n')
        output_lines = []
        for line in lines:
            if line.strip() and not line.startswith('llm_load'):
                output_lines.append(line)
        
        output_text = '\n'.join(output_lines)
        tokens = int(max_tokens)
        tokens_per_sec = tokens / elapsed if elapsed > 0 else 0
        
        return json.dumps({
            'output': output_text,
            'time_seconds': elapsed,
            'tokens_generated': tokens,
            'tokens_per_sec': round(tokens_per_sec, 2)
        })
        
    except subprocess.TimeoutExpired:
        return json.dumps({
            'error': 'Request timed out after 120 seconds',
            'time_seconds': 120
        })
    except Exception as e:
        return json.dumps({
            'error': str(e),
            'time_seconds': time.time() - start
        })

@app.route('/health')
def health():
    return json.dumps({'status': 'ok', 'model': 'Falcon3-1B-Instruct-1.58bit'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
