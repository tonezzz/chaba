#!/usr/bin/env python3
"""
AutoAgent Control Server

Simple HTTP control panel for the AutoAgent test container.
Shows container status, environment, and provides quick actions.

Usage:
    python control-server.py --port 8080
"""

import asyncio
import os
import json
import subprocess
from pathlib import Path
from aiohttp import web

# Configuration
PORT = int(os.getenv("AUTOAGENT_CONTROL_PORT", "8080"))
HOST = os.getenv("AUTOAGENT_CONTROL_HOST", "0.0.0.0")
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", "/workspace"))

# Storage for running processes
running_processes = {}  # session_id -> {"process": Popen, "output": [], "done": False}


def get_env_info():
    """Get relevant environment variables."""
    keys = [
        "AUTOAGENT_MODEL",
        "AUTOAGENT_API_BASE_URL",
        "OPENROUTER_API_KEY",
        "COMPLETION_MODEL",
        "DEBUG"
    ]
    return {k: os.getenv(k, "Not set") for k in keys if os.getenv(k)}


def get_discovery_info():
    """Get GhostRoute discovery info if available."""
    discovery_dir = WORKSPACE_DIR / "discovery" / "ghostroute" / "latest"
    config_file = discovery_dir / "recommended_config.json"
    
    if config_file.exists():
        try:
            with open(config_file) as f:
                return json.load(f)
        except:
            pass
    return None


def get_workspace_files():
    """List workspace contents."""
    try:
        files = []
        for item in WORKSPACE_DIR.iterdir():
            if item.is_dir():
                files.append({"name": item.name + "/", "type": "dir"})
            else:
                files.append({"name": item.name, "type": "file"})
        return sorted(files, key=lambda x: (x["type"], x["name"]))
    except Exception as e:
        return [{"name": f"Error: {e}", "type": "error"}]


def run_command(cmd, timeout=5):
    """Run a shell command safely."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "(timed out)"
    except Exception as e:
        return f"Error: {e}"


async def handle_control(request):
    """Main control panel page."""
    env_info = get_env_info()
    discovery = get_discovery_info()
    workspace_files = get_workspace_files()
    
    # Build env table
    env_html = ""
    for k, v in env_info.items():
        masked = v[:10] + "..." if "key" in k.lower() and len(v) > 20 else v
        env_html += f'<tr><td>{k}</td><td><code>{masked}</code></td></tr>'
    
    # Build discovery section
    discovery_html = ""
    if discovery:
        primary = discovery.get("primary_model", "N/A")
        fallbacks = discovery.get("fallback_chain", [])
        discovery_html += f'<div class="card"><h2>GhostRoute Discovery</h2>'
        discovery_html += f'<p><strong>Primary:</strong> <code>{primary}</code></p>'
        discovery_html += '<p><strong>Fallbacks:</strong></p><ul>'
        for fb in fallbacks[:5]:
            discovery_html += f'<li><code>{fb}</code></li>'
        discovery_html += '</ul></div>'
    
    # Build workspace file list
    files_html = ""
    for f in workspace_files[:20]:
        icon = "📁" if f["type"] == "dir" else "📄"
        files_html += f'<div class="file-item">{icon} {f["name"]}</div>'
    
    # Get system info
    disk_usage = run_command("df -h /workspace 2>/dev/null || df -h .")
    memory = run_command("free -h 2>/dev/null || echo 'N/A'")
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>AutoAgent Control Panel</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; background: #f0f2f5; }}
        h1 {{ color: #1a73e8; border-bottom: 3px solid #1a73e8; padding-bottom: 10px; }}
        h2 {{ color: #5f6368; margin-top: 25px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; margin: 15px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .status {{ display: inline-block; padding: 6px 14px; border-radius: 20px; font-weight: bold; font-size: 14px; }}
        .status.ok {{ background: #e6f4ea; color: #1e8e3e; }}
        .status.warn {{ background: #fef3e8; color: #f9ab00; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #e0e0e0; }}
        th {{ background: #f8f9fa; color: #5f6368; font-weight: 600; }}
        code {{ background: #f1f3f4; padding: 2px 8px; border-radius: 4px; font-family: 'Roboto Mono', monospace; font-size: 0.9em; }}
        .file-item {{ padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }}
        .file-item:hover {{ background: #f8f9fa; }}
        .action-btn {{ display: inline-block; background: #1a73e8; color: white; padding: 10px 24px; text-decoration: none; border-radius: 6px; margin: 5px; border: none; cursor: pointer; font-size: 14px; }}
        .action-btn:hover {{ background: #1557b0; }}
        .action-btn.secondary {{ background: #5f6368; }}
        .action-btn.secondary:hover {{ background: #3c4043; }}
        .metric {{ display: inline-block; margin: 10px 20px 10px 0; padding: 15px; background: #f8f9fa; border-radius: 8px; min-width: 120px; }}
        .metric-value {{ font-size: 28px; font-weight: bold; color: #1a73e8; }}
        .metric-label {{ font-size: 12px; color: #5f6368; text-transform: uppercase; margin-top: 5px; }}
        pre {{ background: #f8f9fa; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 12px; line-height: 1.5; }}
        .refresh {{ float: right; background: #1a73e8; color: white; padding: 8px 16px; text-decoration: none; border-radius: 6px; font-size: 14px; }}
        ul {{ padding-left: 20px; }}
        li {{ margin: 5px 0; }}
    </style>
</head>
<body>
    <h1>AutoAgent Control Panel</h1>
    <a href="/" class="refresh">Refresh</a>
    
    <div class="card">
        <h2>Status</h2>
        <span class="status ok">● Running</span>
        <p>Container: <strong>autoagent-test</strong></p>
        <p>Workspace: <code>{WORKSPACE_DIR}</code></p>
    </div>
    
    <div class="card">
        <h2>Environment</h2>
        <table>
            <tr><th>Variable</th><th>Value</th></tr>
            {env_html if env_html else '<tr><td colspan="2">No env vars set</td></tr>'}
        </table>
    </div>
    
    {discovery_html}
    
    <div class="card">
        <h2>Actions</h2>
        <button class="action-btn" onclick="location.href='/test'">Run Model Test</button>
        <button class="action-btn secondary" onclick="location.href='/discovery'">View Discovery</button>
        <button class="action-btn secondary" onclick="location.href='/api/health'">Health Check (JSON)</button>
        <button class="action-btn" style="background: #ea4335;" onclick="location.href='/runner'">AutoAgent Runner</button>
    </div>
    
    <div class="card">
        <h2>Workspace Files</h2>
        {files_html if files_html else '<p>No files in workspace</p>'}
    </div>
    
    <div class="card">
        <h2>System Info</h2>
        <h3>Disk Usage</h3>
        <pre>{disk_usage}</pre>
        <h3>Memory</h3>
        <pre>{memory}</pre>
    </div>
    
    <script>
        setTimeout(() => window.location.reload(), 60000);
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_api_health(request):
    """JSON health endpoint."""
    return web.json_response({
        "status": "healthy",
        "container": "autoagent-test",
        "workspace": str(WORKSPACE_DIR),
        "discovery_available": get_discovery_info() is not None
    })


async def handle_test(request):
    """Run a quick test and show results."""
    html = """<!DOCTYPE html>
<html>
<head>
    <title>AutoAgent Test</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        .loading { text-align: center; padding: 50px; }
        .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #1a73e8; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <h1>Running Model Test...</h1>
    <div class="loading">
        <div class="spinner"></div>
        <p>Testing connection to OpenRouter...</p>
    </div>
    <p>This page will not auto-refresh. Check the logs with:</p>
    <code>docker logs autoagent-test</code>
    <p><a href="/">Back to Control Panel</a></p>
</body>
</html>"""
    # Start test in background
    asyncio.create_task(run_test_async())
    return web.Response(text=html, content_type="text/html")


async def run_test_async():
    """Run test in background."""
    cmd = "cd /app && python -c \"import requests; print(requests.get('https://openrouter.ai/api/v1/models', headers={'Authorization': 'Bearer ' + os.getenv('OPENROUTER_API_KEY', '')}).status_code)\" 2>&1"
    result = run_command(cmd, timeout=10)
    print(f"Test result: {result}")


async def handle_discovery(request):
    """Show discovery data."""
    discovery = get_discovery_info()
    if not discovery:
        return web.Response(
            text="<h1>No Discovery Data</h1><p>Run discovery first.</p><p><a href='/'>Back</a></p>",
            content_type="text/html"
        )
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Discovery Data</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 30px auto; padding: 20px; }}
        pre {{ background: #f5f5f5; padding: 20px; border-radius: 8px; overflow-x: auto; }}
    </style>
</head>
<body>
    <h1>Discovery Data</h1>
    <pre>{json.dumps(discovery, indent=2)}</pre>
    <p><a href="/">Back to Control Panel</a></p>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_runner(request):
    """AutoAgent Runner Panel - simple command execution interface."""
    discovery = get_discovery_info()
    primary_model = discovery.get("primary_model", "default") if discovery else "default"
    
    html = """<!DOCTYPE html>
<html>
<head>
    <title>AutoAgent Runner</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; background: #f0f2f5; }
        h1 { color: #1a73e8; border-bottom: 3px solid #1a73e8; padding-bottom: 10px; }
        .card { background: white; border-radius: 12px; padding: 20px; margin: 15px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .command-input { width: 100%; padding: 12px; font-family: monospace; font-size: 14px; border: 1px solid #ddd; border-radius: 6px; margin: 10px 0; }
        .btn { background: #1a73e8; color: white; padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; margin: 5px; }
        .btn:hover { background: #1557b0; }
        .btn-secondary { background: #5f6368; }
        .btn-secondary:hover { background: #3c4043; }
        .btn-danger { background: #ea4335; }
        .btn-danger:hover { background: #d33b28; }
        .output { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 6px; font-family: 'Courier New', monospace; font-size: 13px; white-space: pre-wrap; min-height: 200px; max-height: 500px; overflow-y: auto; }
        .preset { display: inline-block; background: #e8f0fe; padding: 8px 16px; margin: 5px; border-radius: 20px; cursor: pointer; font-size: 13px; }
        .preset:hover { background: #d2e3fc; }
        .status { display: inline-block; padding: 5px 12px; border-radius: 4px; font-weight: bold; font-size: 12px; }
        .status.idle { background: #e6f4ea; color: #1e8e3e; }
        .status.running { background: #fef3e8; color: #f9ab00; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        label { font-weight: 600; color: #5f6368; font-size: 14px; }
        .back { float: right; color: #1a73e8; text-decoration: none; }
        .back:hover { text-decoration: underline; }
        
        /* Tab Styles */
        .tabs { display: flex; border-bottom: 2px solid #e0e0e0; margin-bottom: 15px; }
        .tab-btn { 
            background: #f5f5f5; 
            border: none; 
            padding: 12px 24px; 
            cursor: pointer; 
            font-size: 14px; 
            font-weight: 500;
            color: #666;
            border-radius: 8px 8px 0 0;
            margin-right: 4px;
            transition: all 0.2s;
        }
        .tab-btn:hover { background: #e8e8e8; }
        .tab-btn.active { 
            background: #1a73e8; 
            color: white; 
            border-bottom: 2px solid #1a73e8;
            margin-bottom: -2px;
        }
        .tab-content { display: none; padding: 10px 0; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
    <h1>AutoAgent Runner <span id="status" class="status idle">● Idle</span> <a href="/" class="back">← Back to Control Panel</a></h1>
    
    <div class="card">
        <div class="tabs">
            <button class="tab-btn active" onclick="showTab('smart')">🧠 Smart Research</button>
            <button class="tab-btn" onclick="showTab('free')">🔥 Free Models</button>
            <button class="tab-btn" onclick="showTab('paid')">💎 Paid Models</button>
        </div>
        
        <div id="tab-smart" class="tab-content active">
            <p style="font-size: 13px; color: #666; margin-bottom: 12px;">
                <b>LLM-powered KB search first.</b> Classifies queries, finds similar articles, combines cached + fresh research.
            </p>
            <div>
                <span class="preset" onclick='setFreeCommand("python /workspace/smart-research.py ")' style="background: #e3f2fd; color: #1565c0; border: 2px solid #1565c0;">🧠 Smart Research (Free)</span>
                <span class="preset" onclick='setFreeCommand("python /workspace/smart-research.py --plan paid ")' style="background: #fff3e0; color: #e65100; border: 2px solid #e65100;">🧠 Smart Research (Paid)</span>
                <span class="preset" onclick='setCommand("python /workspace/smart-research.py")' style="background: #f3e5f5; color: #7b1fa2;">📊 KB Stats</span>
                <span class="preset" onclick='setCommand("python /workspace/wiki-knowledge.py")' style="background: #fff3e0; color: #e65100;">� Browse Wiki</span>
            </div>
        </div>
        
        <div id="tab-free" class="tab-content">
            <p style="font-size: 13px; color: #666; margin-bottom: 12px;">
                <b>Direct API calls.</b> Bypasses LiteLLM. Uses nvidia/minimax free models. No caching.
            </p>
            <div>
                <span class="preset" onclick='setFreeCommand("python /workspace/free-research.py ")' style="background: #e8f5e9; color: #2e7d32;">🆓 Free Research</span>
                <span class="preset" onclick='setFreeCommand("python /workspace/free-research.py ")' style="background: #e8f5e9; color: #2e7d32;">📝 Code Task</span>
                <span class="preset" onclick='setCommand("python /workspace/free-research.py")' style="background: #f1f8e9; color: #558b2f;">🔍 List Models</span>
            </div>
        </div>
        
        <div id="tab-paid" class="tab-content">
            <p style="font-size: 13px; color: #666; margin-bottom: 12px;">
                <b>Via AutoAgent CLI.</b> Uses LiteLLM. Requires paid OpenRouter credits.
            </p>
            <div>
                <span class="preset" onclick="setCommand('auto agent --model=openai/gpt-4o-mini --query=')">🧠 Deep Research ($)</span>
                <span class="preset" onclick="setCommand('auto agent --model=openai/gpt-4o-mini --query=')">💻 Code Task ($)</span>
                <span class="preset" onclick="setCommand('auto main')">🚀 Start Main</span>
                <span class="preset" onclick="setCommand('auto agent --help')">❓ Help</span>
            </div>
        </div>
    </div>
    
    <div class="card">
        <h2>Custom Command</h2>
        <label>Command:</label><br>
        <input type="text" id="command" class="command-input" placeholder="Click a preset above or type: python /workspace/free-research.py 'your question'" />
        <br>
        <button class="btn" onclick="runCommand()">▶ Run</button>
        <button class="btn btn-secondary" onclick="stopCommand()">⏹ Stop</button>
        <button class="btn btn-secondary" onclick="clearOutput()">🗑 Clear</button>
    </div>
    
    <div class="card">
        <h2>Output</h2>
        <div id="output" class="output">Loading... (if this doesn't change, JavaScript may be disabled)</div>
    </div>
    
    <script>
        let sessionId = null;
        let pollInterval = null;
        
        function showTab(tabName) {
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            // Remove active from all buttons
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            // Show selected tab
            document.getElementById('tab-' + tabName).classList.add('active');
            // Activate button
            event.target.classList.add('active');
        }
        
        function setCommand(cmd) {
            document.getElementById('command').value = cmd;
            document.getElementById('command').focus();
        }
        
        function setFreeCommand(prefix) {
            // For free-research.py commands
            const query = prompt('Enter your research question:');
            if (query) {
                // Wrap query in single quotes
                document.getElementById('command').value = prefix + "'" + query + "'";
                document.getElementById('command').focus();
            }
        }
        
        async function runCommand() {
            const cmd = document.getElementById('command').value.trim();
            console.log('runCommand called with:', cmd);
            
            if (!cmd) {
                alert('Please enter a command');
                return;
            }
            
            document.getElementById('output').innerHTML = 'Starting: ' + cmd + '<br>---<br>';
            document.getElementById('status').textContent = '● Running';
            document.getElementById('status').className = 'status running';
            
            try {
                console.log('Fetching /api/execute...');
                const response = await fetch('/api/execute', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({command: cmd})
                });
                console.log('Response status:', response.status);
                
                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error('HTTP ' + response.status + ': ' + errorText);
                }
                
                const data = await response.json();
                console.log('Response data:', data);
                
                if (data.error) {
                    throw new Error(data.error);
                }
                
                sessionId = data.session_id;
                console.log('Session ID:', sessionId);
                
                // Start polling for output
                pollInterval = setInterval(pollOutput, 1000);
            } catch (e) {
                console.error('Error:', e);
                document.getElementById('output').innerHTML += '<br>Error: ' + e.message + '<br>';
                setIdle();
            }
        }
        
        async function pollOutput() {
            if (!sessionId) return;
            
            try {
                const response = await fetch('/api/output/' + sessionId);
                if (!response.ok) {
                    console.error('Poll failed:', response.status);
                    return;
                }
                
                const data = await response.json();
                
                if (data.output && data.output.length > 0) {
                    document.getElementById('output').innerHTML = data.output.join('<br>');
                    
                    // Auto-scroll to bottom
                    const outputDiv = document.getElementById('output');
                    outputDiv.scrollTop = outputDiv.scrollHeight;
                }
                
                if (data.done) {
                    setIdle();
                }
            } catch (e) {
                console.error('Poll error:', e);
            }
        }
        
        async function stopCommand() {
            console.log('stopCommand called, sessionId:', sessionId);
            if (!sessionId) {
                document.getElementById('output').textContent += ' No active process to stop ';
                return;
            }
            
            try {
                const response = await fetch('/api/stop/' + sessionId, {method: 'POST'});
                console.log('Stop response:', response.status);
                document.getElementById('output').textContent += ' [Stop requested] ';
            } catch (e) {
                console.error('Stop error:', e);
            }
            setIdle();
        }
        
        function setIdle() {
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
            sessionId = null;
            document.getElementById('status').textContent = '● Idle';
            document.getElementById('status').className = 'status idle';
        }
        
        function clearOutput() {
            document.getElementById('output').textContent = '';
        }
        
        // Debug logging
        console.log('Runner panel loaded');
        
        // All DOM manipulation after DOM ready
        document.addEventListener('DOMContentLoaded', function() {
            console.log('DOM ready, initializing...');
            
            // Set initial message
            const outputDiv = document.getElementById('output');
            if (outputDiv) {
                outputDiv.innerHTML = 'Ready! Click a preset or type a command.<br><br>Presets: Deep Research, Code Task, Start Main, Agent Help';
            }
            
            // Attach Enter key listener
            const cmdInput = document.getElementById('command');
            if (cmdInput) {
                cmdInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') runCommand();
                });
            }
            
            console.log('Initialization complete');
        });
        
        // Also try immediate attachment
        setTimeout(function() {
            const cmdInput = document.getElementById('command');
            if (cmdInput && !cmdInput.dataset.hasListener) {
                cmdInput.dataset.hasListener = 'true';
                cmdInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') runCommand();
                });
            }
        }, 100);
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_execute(request):
    """Execute AutoAgent command."""
    try:
        data = await request.json()
        command = data.get("command", "").strip()
        
        if not command:
            return web.json_response({"error": "No command provided"}, status=400)
        
        # Validate command (must start with 'auto' or 'python' for safety)
        if not (command.startswith("auto") or command.startswith("python")):
            return web.json_response({"error": "Only 'auto' or 'python' commands allowed"}, status=403)
        
        import uuid
        import shlex
        session_id = str(uuid.uuid4())[:8]
        
        # Parse command properly to handle quoted arguments
        try:
            cmd_parts = shlex.split(command)
        except ValueError as e:
            return web.json_response({"error": f"Invalid command syntax: {e}"}, status=400)
        
        # Start process without shell to preserve quotes
        process = subprocess.Popen(
            cmd_parts,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(WORKSPACE_DIR)
        )
        
        running_processes[session_id] = {
            "process": process,
            "output": [f"$ {command}", "---"],
            "done": False,
            "start_time": asyncio.get_event_loop().time()
        }
        
        # Start background reader
        asyncio.create_task(read_output(session_id))
        
        return web.json_response({
            "session_id": session_id,
            "status": "started"
        })
    
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def read_output(session_id):
    """Read process output in background."""
    proc_data = running_processes.get(session_id)
    if not proc_data:
        return
    
    process = proc_data["process"]
    
    # Read output line by line
    while True:
        line = process.stdout.readline()
        if not line:
            break
        proc_data["output"].append(line.rstrip())
        # Limit output size (keep last 1000 lines)
        if len(proc_data["output"]) > 1000:
            proc_data["output"] = proc_data["output"][-1000:]
    
    # Wait for process to complete
    process.wait()
    proc_data["done"] = True
    proc_data["returncode"] = process.returncode
    proc_data["output"].append(f"--- Exit code: {process.returncode}")


async def handle_output(request):
    """Get output for a running process."""
    session_id = request.match_info.get("session_id")
    proc_data = running_processes.get(session_id)
    
    if not proc_data:
        return web.json_response({"error": "Session not found"}, status=404)
    
    return web.json_response({
        "output": proc_data["output"],
        "done": proc_data["done"],
        "returncode": proc_data.get("returncode")
    })


async def handle_stop(request):
    """Stop a running process."""
    session_id = request.match_info.get("session_id")
    proc_data = running_processes.get(session_id)
    
    if proc_data and not proc_data["done"]:
        proc_data["process"].terminate()
        proc_data["output"].append("--- Process terminated by user")
        proc_data["done"] = True
    
    return web.json_response({"status": "stopped"})


async def main():
    """Start the control server."""
    app = web.Application()
    app.router.add_get("/", handle_control)
    app.router.add_get("/api/health", handle_api_health)
    app.router.add_get("/test", handle_test)
    app.router.add_get("/discovery", handle_discovery)
    
    # Runner panel routes
    app.router.add_get("/runner", handle_runner)
    app.router.add_post("/api/execute", handle_execute)
    app.router.add_get("/api/output/{session_id}", handle_output)
    app.router.add_post("/api/stop/{session_id}", handle_stop)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    
    print(f"AutoAgent Control Server running on http://{HOST}:{PORT}/")
    print(f"Health API: http://{HOST}:{PORT}/api/health")
    
    # Keep running
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    
    HOST = args.host
    PORT = args.port
    
    asyncio.run(main())
