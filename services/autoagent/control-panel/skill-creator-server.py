#!/usr/bin/env python3
"""
Skill Creator Standalone Server
Serves the Skill Creator UI on /skills
"""

import os
import json
import re
from pathlib import Path
from aiohttp import web

# Configuration
HOST = os.getenv("AUTOAGENT_CONTROL_HOST", "0.0.0.0")
PORT = int(os.getenv("AUTOAGENT_CONTROL_PORT", "8080"))
WIKI_API_URL = os.getenv("WIKI_API_URL", "http://mcp-wiki:8080")

# Load the HTML template
HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>Skill Creator</title>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: system-ui, -apple-system, sans-serif; 
            max-width: 1000px; 
            margin: 0 auto; 
            padding: 20px; 
            background: #f5f7fa; 
        }
        h1 { 
            color: #1a73e8; 
            border-bottom: 3px solid #1a73e8; 
            padding-bottom: 10px; 
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .card { 
            background: white; 
            border-radius: 12px; 
            padding: 24px; 
            margin: 20px 0; 
            box-shadow: 0 2px 8px rgba(0,0,0,0.1); 
        }
        .input-section {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }
        .text-input { 
            flex: 1;
            padding: 14px 18px; 
            font-size: 16px; 
            border: 2px solid #e0e0e0; 
            border-radius: 8px; 
            transition: border-color 0.2s;
        }
        .text-input:focus {
            outline: none;
            border-color: #1a73e8;
        }
        .btn { 
            background: #1a73e8; 
            color: white; 
            padding: 14px 28px; 
            border: none; 
            border-radius: 8px; 
            cursor: pointer; 
            font-size: 16px; 
            font-weight: 500;
            transition: background 0.2s;
        }
        .btn:hover { background: #1557b0; }
        .btn:disabled { 
            background: #ccc; 
            cursor: not-allowed; 
        }
        .btn-secondary { 
            background: #5f6368; 
            padding: 10px 20px;
            font-size: 14px;
        }
        .btn-secondary:hover { background: #3c4043; }
        .output { 
            background: #1e1e1e; 
            color: #d4d4d4; 
            padding: 20px; 
            border-radius: 8px; 
            font-family: 'SF Mono', 'Courier New', monospace; 
            font-size: 13px; 
            white-space: pre-wrap; 
            min-height: 200px;
            line-height: 1.6;
        }
        .back { 
            float: right; 
            color: #1a73e8; 
            text-decoration: none; 
            font-size: 14px;
            margin-top: 10px;
        }
        .back:hover { text-decoration: underline; }
        .status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
        }
        .status.ready { background: #e6f4ea; color: #1e8e3e; }
        .status.processing { 
            background: #e3f2fd; 
            color: #1565c0; 
        }
        .status.processing::before {
            content: "";
            width: 14px;
            height: 14px;
            border: 2px solid #1565c0;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .preview-box {
            background: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
        }
        .preview-box h3 {
            margin-top: 0;
            color: #5f6368;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .config-table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }
        .config-table td {
            padding: 8px 12px;
            border-bottom: 1px solid #e0e0e0;
        }
        .config-table td:first-child {
            color: #5f6368;
            font-weight: 500;
            width: 120px;
        }
        .revision-section {
            display: none;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 2px dashed #e0e0e0;
        }
        .revision-section.active {
            display: block;
        }
        .example-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 10px 0;
        }
        .pill {
            background: #e8f0fe;
            color: #1a73e8;
            padding: 6px 14px;
            border-radius: 16px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .pill:hover {
            background: #1a73e8;
            color: white;
        }
        .error { color: #ea4335; }
        .success { color: #1e8e3e; }
        
        .action-buttons {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        
        .status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
            background: #e0e0e0;
            color: #666;
            transition: all 0.3s;
        }
        .status-badge.active {
            transform: scale(1.05);
        }
        .status-badge.draft.active { background: #e3f2fd; color: #1565c0; }
        .status-badge.review.active { background: #fff3e0; color: #e65100; }
        .status-badge.approved.active { background: #e8f5e9; color: #2e7d32; }
        .status-badge.ready.active { background: #f3e5f5; color: #7b1fa2; }
    </style>
</head>
<body>
    <h1>
        🛠️ Skill Creator
        <span id="status" class="status ready">Ready</span>
    </h1>
    
    <div class="card">
        <p style="color: #5f6368; margin-bottom: 20px;">
            Describe what you want the skill to do in natural language. 
            The system will interpret your intent and generate a skill draft.
        </p>
        
        <div class="example-pills">
            <span class="pill" onclick='setExample("check the weather when I ask what\'s the weather")'>☁️ Weather check</span>
            <span class="pill" onclick='setExample("remind me about tasks when I say don\'t forget")'>⏰ Reminder</span>
            <span class="pill" onclick="setExample('search wiki articles when I ask find docs')">🔍 Wiki search</span>
            <span class="pill" onclick="setExample('tell me news headlines when I say news')">📰 News brief</span>
        </div>
        
        <div style="margin-top: 15px; padding: 12px; background: #fff8e1; border-radius: 8px; border-left: 4px solid #ffc107;">
            <strong>🇹🇭 Thai Language Templates:</strong>
            <div class="example-pills" style="margin-top: 8px;">
                <span class="pill" onclick="setExample('ตรวจสอบสภาพอากาศเมื่อถามว่าอากาศเป็นอย่างไร')">☁️ ตรวจสอบอากาศ</span>
                <span class="pill" onclick="setExample('เตือนฉันเกี่ยวกับงานเมื่อพูดว่าอย่าลืม')">⏰ เตือนความจำ</span>
            </div>
        </div>
        
        <div class="input-section">
            <input 
                type="text" 
                id="skillInput" 
                class="text-input" 
                placeholder="Describe your skill..."
                onkeypress="if(event.key==='Enter')createSkill()"
            >
            <button id="createBtn" class="btn" onclick="createSkill()">Create Skill</button>
        </div>
        
        <div id="previewBox" class="preview-box" style="display: none;">
            <h3>📊 Interpreted Intent</h3>
            <table class="config-table" id="configTable"></table>
            
            <h3>📄 Generated Skill (Preview)</h3>
            <div id="markdownPreview" class="output"></div>
            
            <div class="action-buttons">
                <button class="btn" onclick="saveToWiki()">💾 Save to Wiki</button>
                <button class="btn btn-secondary" onclick="showRevision()">🔧 Revise</button>
                <button class="btn btn-secondary" onclick="reset()">✕ Clear</button>
            </div>
            
            <div id="revisionSection" class="revision-section">
                <h3>🔧 Steer Development</h3>
                <div class="input-section">
                    <input 
                        type="text" 
                        id="revisionInput" 
                        class="text-input" 
                        placeholder="e.g., 'add Thai language support'"
                        onkeypress="if(event.key==='Enter')reviseSkill()"
                    >
                    <button class="btn" onclick="reviseSkill()">Apply Revision</button>
                </div>
            </div>
            
            <div id="resultMessage" style="margin-top: 15px; font-weight: 500;"></div>
        </div>
    </div>
    
    <script src="/static/skill-creator.js"></script>
</body>
</html>"""


async def handle_skills(request):
    """Serve the Skill Creator UI."""
    return web.Response(text=HTML_TEMPLATE, content_type="text/html")


async def handle_health(request):
    """Health check endpoint."""
    return web.json_response({"status": "healthy", "service": "skill-creator"})


async def handle_skill_interpret(request):
    """API: Interpret natural language into skill config."""
    try:
        data = await request.json()
        user_input = data.get("input", "").strip()
        
        if not user_input:
            return web.json_response({"error": "No input provided"}, status=400)
        
        # Simple interpretation
        text = user_input.lower()
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text)[:3]
        name = "_".join(words) if words else "new_skill"
        
        # Determine category
        category = "utility"
        if any(x in text for x in ["weather", "time", "date", "news"]):
            category = "info"
        elif any(x in text for x in ["remind", "task", "todo", "schedule"]):
            category = "action"
        elif any(x in text for x in ["search", "find", "lookup"]):
            category = "search"
        
        trigger_words = [w for w in text.split() if w in ["check", "get", "show", "find", "search", "remind", "tell"]]
        if not trigger_words:
            trigger_words = [text.split()[0]] if text.split() else ["trigger"]
        
        config = {
            "skill_name": name,
            "purpose": user_input,
            "trigger_phrases": [user_input] + [f"{w} {name.replace('_', ' ')}" for w in trigger_words[:2]],
            "handler_type": "tool_call",
            "suggested_tool": name + "_tool",
            "category": category,
            "examples": [user_input],
            "priority": 10
        }
        
        # Generate markdown
        trigger_section = "\\n".join([f'- "{t}"' for t in config["trigger_phrases"][:3]])
        
        markdown = f"""# Skill: {config['skill_name']}

## Metadata
- **Name**: {config['skill_name']}
- **Status**: draft
- **Version**: 1.0.0

## Purpose
{config['purpose']}

## Trigger Definition
- **Match Type**: prefix
- **Patterns**:
{trigger_section}
- **Priority**: {config['priority']}
- **Languages**: en

## Handler Configuration
- **Type**: {config['handler_type']}
- **Target**: {config['suggested_tool']}

## Examples
| Input | Expected Behavior |
|-------|-------------------|
| "{config['examples'][0]}" | Calls {config['suggested_tool']} |

## Development Notes
- Created from: "{user_input}"
"""
        
        return web.json_response({
            "config": config,
            "markdown": markdown
        })
        
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_skill_revise(request):
    """API: Revise skill based on feedback."""
    try:
        data = await request.json()
        markdown = data.get("markdown", "")
        revision_request = data.get("revision", "").lower()
        
        if not markdown or not revision_request:
            return web.json_response({"error": "Missing markdown or revision"}, status=400)
        
        # Apply simple transformations
        new_markdown = markdown
        
        if "thai" in revision_request:
            new_markdown = new_markdown.replace(
                "- **Languages**: en",
                "- **Languages**: en, th\\n- **Thai Patterns**: TBD"
            )
        
        if "priority" in revision_request:
            nums = re.findall(r'\\d+', revision_request)
            if nums:
                new_priority = nums[0]
                new_markdown = re.sub(
                    r'- \\*\\*Priority\\*\\*: \\d+',
                    f'- **Priority**: {new_priority}',
                    new_markdown
                )
        
        return web.json_response({
            "markdown": new_markdown,
            "applied": True
        })
        
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_skill_save(request):
    """API: Save skill to wiki."""
    try:
        data = await request.json()
        name = data.get("name", "")
        markdown = data.get("markdown", "")
        
        if not name or not markdown:
            return web.json_response({"error": "Missing name or markdown"}, status=400)
        
        # Save to local file
        wiki_dir = Path("/tmp/skill_drafts")
        wiki_dir.mkdir(exist_ok=True)
        
        filename = f"Skill_{name}.md"
        filepath = wiki_dir / filename
        
        with open(filepath, "w") as f:
            f.write(markdown)
        
        return web.json_response({
            "ok": True,
            "saved_to": str(filepath)
        })
        
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def main():
    """Start the skill creator server."""
    app = web.Application()
    
    # Routes
    app.router.add_get("/skills", handle_skills)
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/skills/interpret", handle_skill_interpret)
    app.router.add_post("/api/skills/revise", handle_skill_revise)
    app.router.add_post("/api/skills/save", handle_skill_save)
    
    # Static files
    static_path = Path(__file__).parent / "static"
    if static_path.exists():
        app.router.add_static("/static/", path=str(static_path))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    
    print(f"Skill Creator server running on http://{HOST}:{PORT}/skills")
    await site.start()
    
    # Keep running
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
