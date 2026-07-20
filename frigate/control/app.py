#!/usr/bin/env python3
"""Lightweight web control panel for the camera registry on tony-dell."""
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

FRIGATE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = FRIGATE_DIR.parent
sys.path.insert(0, str(FRIGATE_DIR))

from generate_config import (
    generate_config_yml,
    generate_map_html,
    load_registry,
    save_registry,
)

app = Flask(__name__)

# Set True to copy frigate/camera-map.html -> web/public/camera-map.html after edits.
SYNC_WEB_MAP = False

JOBS = {}
JOBS_LOCK = threading.Lock()


def _run_reader(proc, job_id):
    out = []
    for line in proc.stdout:
        out.append(line)
        with JOBS_LOCK:
            JOBS[job_id]["output"] = "".join(out)
    proc.wait()
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "done" if proc.returncode == 0 else "error"
        JOBS[job_id]["returncode"] = proc.returncode


def run_job(cmd, name):
    job_id = uuid.uuid4().hex[:8]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "name": name,
            "status": "running",
            "started": time.time(),
            "output": "",
            "returncode": None,
        }
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=REPO_ROOT,
    )
    t = threading.Thread(target=_run_reader, args=(proc, job_id), daemon=True)
    t.start()
    return job_id


def _regenerate_files(registry):
    generate_config_yml(registry)
    generate_map_html(registry)
    if SYNC_WEB_MAP:
        src = FRIGATE_DIR / "camera-map.html"
        dst = REPO_ROOT / "web" / "public" / "camera-map.html"
        if src.exists() and dst.parent.is_dir():
            shutil.copyfile(src, dst)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/registry")
def api_registry():
    registry = load_registry()
    return jsonify({"cameras": registry["cameras"], "groups": registry["groups"]})


@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.get_json() or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    registry = load_registry()
    cam = next((c for c in registry["cameras"] if c["name"] == name), None)
    if not cam:
        return jsonify({"error": "not found"}), 404
    cam["enabled"] = not cam.get("enabled", True)
    save_registry(registry)
    _regenerate_files(registry)
    return jsonify({"ok": True, "enabled": cam["enabled"]})


@app.route("/api/group", methods=["POST"])
def api_group():
    data = request.get_json() or {}
    name = data.get("name")
    group = data.get("group")
    if not name:
        return jsonify({"error": "name required"}), 400
    registry = load_registry()
    cam = next((c for c in registry["cameras"] if c["name"] == name), None)
    if not cam:
        return jsonify({"error": "not found"}), 404
    cam["group"] = group or None
    save_registry(registry)
    _regenerate_files(registry)
    return jsonify({"ok": True, "group": cam["group"]})


@app.route("/api/discover", methods=["POST"])
def api_discover():
    cmd = [sys.executable, str(FRIGATE_DIR / "generate_config.py"), "--discover"]
    return jsonify({"job_id": run_job(cmd, "discover")})


@app.route("/api/rtsp", methods=["POST"])
def api_rtsp():
    cmd = [sys.executable, str(FRIGATE_DIR / "generate_config.py"), "--discover-rtsp"]
    return jsonify({"job_id": run_job(cmd, "rtsp-scan")})


@app.route("/api/enixma", methods=["POST"])
def api_enixma():
    cmd = [sys.executable, str(FRIGATE_DIR / "generate_config.py"), "--discover-enixma"]
    return jsonify({"job_id": run_job(cmd, "enixma-scan")})


@app.route("/api/itic", methods=["POST"])
def api_itic():
    cmd = [sys.executable, str(FRIGATE_DIR / "generate_config.py"), "--discover-itic"]
    return jsonify({"job_id": run_job(cmd, "itic-scan")})


@app.route("/api/check", methods=["POST"])
def api_check():
    cmd = [sys.executable, str(FRIGATE_DIR / "generate_config.py"), "--check"]
    return jsonify({"job_id": run_job(cmd, "check")})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    cmd = [sys.executable, str(FRIGATE_DIR / "generate_config.py")]
    return jsonify({"job_id": run_job(cmd, "generate")})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    src = FRIGATE_DIR / "camera-map.html"
    dst = REPO_ROOT / "web" / "public" / "camera-map.html"
    if not src.exists():
        return jsonify({"error": "frigate/camera-map.html not found"}), 404
    if not dst.parent.is_dir():
        return jsonify({"error": "web/public/ not found"}), 404
    shutil.copyfile(src, dst)
    return jsonify({"ok": True, "copied": str(dst)})


@app.route("/api/jobs")
def api_jobs():
    with JOBS_LOCK:
        return jsonify(
            [{k: v for k, v in job.items() if k != "output"} for job in JOBS.values()]
        )


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


@app.route("/map")
def map_page():
    return send_file(FRIGATE_DIR / "camera-map.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, debug=False)
