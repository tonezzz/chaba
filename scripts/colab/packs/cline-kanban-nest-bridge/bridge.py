#!/usr/bin/env python3
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

CONTAINER = "cline-kanban"
RUNTIME_HOST = "0.0.0.0"
RUNTIME_PORT = "3485"
JOB_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")


def validate_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError("task input must be a JSON object")
    job_key = spec.get("job_key", "")
    if not isinstance(job_key, str) or not JOB_KEY_RE.fullmatch(job_key):
        raise ValueError("job_key must be a lowercase slug of 2-60 characters")
    if spec.get("target_host") != "con01":
        raise ValueError("this pilot pack is restricted to con01")
    if spec.get("execute") is not True:
        raise ValueError("execute must be true for the explicit smoke pack")
    if spec.get("project_path") != "/workspace":
        raise ValueError("project_path must be the disposable /workspace")
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        raise ValueError("title is required")
    if len(spec["title"]) > 120:
        raise ValueError("title must be at most 120 characters")
    if not isinstance(spec.get("prompt"), str) or not spec["prompt"].strip():
        raise ValueError("prompt is required")
    if len(spec["prompt"]) > 4000:
        raise ValueError("prompt must be at most 4000 characters")
    if spec.get("agent_id") != "cline":
        raise ValueError("agent_id must be cline")
    if spec.get("base_ref") != "main":
        raise ValueError("base_ref must be the disposable workspace main branch")
    allowed = {
        ("ollama", "qwen3:4b"),
        ("ollama", "qwen2.5:7b"),
        ("openrouter", "or-free-nemotron-nano"),
        ("openrouter", "or-free-gemma31b"),
    }
    if (spec.get("provider_id"), spec.get("model_id")) not in allowed:
        raise ValueError(
            "provider/model must be one of: "
            + ", ".join(f"{p}/{m}" for p, m in sorted(allowed)))
    expected_file = spec.get("expected_file", "")
    if expected_file:
        path = PurePosixPath(expected_file)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("expected_file must be a relative path without traversal")
        if spec.get("expected_text") is not None and not isinstance(
                spec["expected_text"], str):
            raise ValueError("expected_text must be a string when set")
    timeout_s = spec.get("timeout_s", 600)
    if not isinstance(timeout_s, int) or not 30 <= timeout_s <= 900:
        raise ValueError("timeout_s must be between 30 and 900 seconds")
    return spec


def task_marker(spec):
    return f"[NEST_JOB_KEY:{spec['job_key']}]"


def task_prompt(spec):
    return f"{spec['prompt'].rstrip()}\n\n{task_marker(spec)}"


def task_title(spec):
    return f"{spec['title'].strip()} [{spec['job_key']}]"


def create_args(spec):
    return [
        "task",
        "create",
        "--title",
        task_title(spec),
        "--prompt",
        task_prompt(spec),
        "--project-path",
        spec["project_path"],
        "--base-ref",
        spec.get("base_ref", "main"),
        "--start-in-plan-mode",
        "false",
        "--auto-review-enabled",
        "false",
        "--agent-id",
        spec["agent_id"],
        "--cline-provider",
        spec["provider_id"],
        "--cline-model",
        spec["model_id"],
    ]


def run_container(args, timeout=60, allowed_codes=(0,)):
    # the kanban CLI drops stdout past ~8KB when writing to a pipe, so
    # redirect inside the container and read the files back out.
    stamp = f"{os.getpid()}-{time.time_ns()}"
    out_tmp = f"/tmp/nest-adapter-{stamp}.out"
    err_tmp = f"/tmp/nest-adapter-{stamp}.err"
    rc_tmp = f"/tmp/nest-adapter-{stamp}.rc"
    cmd = [
        "podman", "exec",
        "--env", f"KANBAN_RUNTIME_HOST={RUNTIME_HOST}",
        "--env", f"KANBAN_RUNTIME_PORT={RUNTIME_PORT}",
        "--env", f"O={out_tmp}", "--env", f"E={err_tmp}", "--env", f"R={rc_tmp}",
        CONTAINER, "sh", "-c",
        '"$@" >"$O" 2>"$E"; printf "%s" "$?" >"$R"',
        "sh", *args,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = _read_container_file(out_tmp)
        stderr = _read_container_file(err_tmp)
        rc_raw = _read_container_file(rc_tmp).strip()
        returncode = int(rc_raw) if rc_raw.isdigit() else -1
    finally:
        subprocess.run(
            ["podman", "exec", CONTAINER, "rm", "-f", out_tmp, err_tmp, rc_tmp],
            capture_output=True, timeout=30)
    if returncode not in allowed_codes:
        detail = (stderr or stdout).strip()[:500]
        raise RuntimeError(f"container command failed ({returncode}): {detail}")
    return stdout


def _read_container_file(path):
    result = subprocess.run(
        ["podman", "exec", CONTAINER, "cat", "--", path],
        capture_output=True, text=True, timeout=30)
    return result.stdout if result.returncode == 0 else ""


def run_kanban(args, timeout=60):
    output = run_container(["kanban", *args], timeout=timeout)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Kanban CLI returned invalid JSON: {output[:300]}") from exc
    if payload.get("ok") is not True:
        raise RuntimeError(f"Kanban CLI returned an error: {payload.get('error', 'unknown')}")
    return payload


def list_tasks(project_path):
    active = run_kanban(["task", "list", "--project-path", project_path])
    done = run_kanban([
        "task", "list", "--column", "trash", "--project-path", project_path,
    ])
    return [*active.get("tasks", []), *done.get("tasks", [])]


def find_existing_task(tasks, marker):
    return next(
        (task for task in tasks if marker in str(task.get("prompt", ""))),
        None,
    )


def should_start_task(task):
    return task.get("column") in {"backlog", "in_progress"}


def parse_worktrees(output):
    worktrees = []
    current = {}
    for line in output.splitlines() + [""]:
        if not line:
            if current.get("path"):
                worktrees.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"worktree", "HEAD", "branch"}:
            current[{"worktree": "path"}.get(key, key)] = value
    return worktrees


def choose_task_worktree(before, after, task_id):
    candidates = [
        item for item in after
        if item.get("path") != "/workspace"
        and (task_id in item.get("path", "") or task_id in item.get("branch", ""))
    ]
    if len(candidates) == 1:
        return candidates[0]
    before_paths = {item.get("path") for item in before}
    new_worktrees = [
        item for item in after
        if item.get("path") != "/workspace" and item.get("path") not in before_paths
    ]
    if len(new_worktrees) == 1:
        return new_worktrees[0]
    raise RuntimeError(
        f"could not uniquely identify worktree for task {task_id}: "
        f"{len(candidates)} task matches, {len(new_worktrees)} new worktrees"
    )


def get_worktrees():
    output = run_container([
        "git", "-C", "/workspace", "worktree", "list", "--porcelain",
    ])
    return parse_worktrees(output)


def get_task(tasks, task_id):
    return next((task for task in tasks if task.get("id") == task_id), None)


def wait_for_review(task_id, project_path, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        task = get_task(list_tasks(project_path), task_id)
        if task is None:
            raise RuntimeError(f"task {task_id} disappeared from the workspace")
        column = task.get("column")
        session = task.get("session") or {}
        exit_code = session.get("exitCode")
        if exit_code not in (None, 0):
            raise RuntimeError(f"Cline task exited with code {exit_code}")
        if column == "review" or exit_code == 0:
            return task
        if column == "trash":
            raise RuntimeError("task reached Done before the adapter collected its diff")
        time.sleep(5)
    raise TimeoutError(f"task {task_id} did not reach Review within {timeout_s}s")


def read_expected_file(worktree_path, expected_file):
    return run_container([
        "cat", "--", f"{worktree_path}/{expected_file}",
    ])


def collect_patch(worktree_path, out_path):
    tracked = run_container([
        "git", "-C", worktree_path, "diff", "--binary", "HEAD",
    ])
    untracked = run_container([
        "git", "-C", worktree_path, "ls-files", "--others",
        "--exclude-standard", "-z",
    ])
    chunks = [tracked] if tracked else []
    for relative in (p for p in untracked.split("\0") if p):
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe untracked path in task worktree: {relative}")
        diff = run_container(
            ["git", "-C", worktree_path, "diff", "--binary", "--no-index",
             "--", "/dev/null", f"{worktree_path}/{relative}"],
            allowed_codes=(0, 1),
        )
        if diff:
            chunks.append(diff)
    patch = "".join(chunks)
    if not patch.strip():
        raise RuntimeError("Cline task completed without a non-empty Git diff")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    temp_path.write_text(patch)
    temp_path.replace(out_path)
    status = run_container([
        "git", "-C", worktree_path, "status", "--porcelain",
        "--untracked-files=all",
    ])
    changed_files = [
        line[3:].strip() for line in status.splitlines() if len(line) > 3
    ]
    return patch, changed_files


def run_bridge(spec, output_path, patch_path):
    actual_host = socket.gethostname().split(".", 1)[0]
    if actual_host != spec["target_host"]:
        raise RuntimeError(f"pack targets {spec['target_host']}, running on {actual_host}")

    marker = task_marker(spec)
    before = get_worktrees()
    tasks = list_tasks(spec["project_path"])
    final_task = None
    worktree = None
    for attempt in range(2):
        tasks = list_tasks(spec["project_path"])
        task = find_existing_task(tasks, marker)
        if task and task.get("column") == "trash":
            raise RuntimeError(
                "matching task is already in Done; use a new job_key for another run"
            )
        if not task:
            created = run_kanban(create_args(spec))
            task = created.get("task")
            if not isinstance(task, dict) or not task.get("id"):
                raise RuntimeError("Kanban create response did not include task.id")
            print(f"created Cline task {task['id']}", flush=True)

        task_id = task["id"]
        if should_start_task(task):
            try:
                run_kanban([
                    "task", "start", "--task-id", task_id,
                    "--project-path", spec["project_path"],
                ], timeout=90)
            except subprocess.TimeoutExpired:
                pass
            print(f"ensured Cline task session {task_id}", flush=True)

        final_task = wait_for_review(task_id, spec["project_path"], spec["timeout_s"])
        worktree = choose_task_worktree(before, get_worktrees(), task_id)
        if not spec.get("expected_file"):
            break
        try:
            expected = read_expected_file(worktree["path"], spec["expected_file"])
        except RuntimeError:
            expected = None
        sentinel = spec.get("expected_text")
        ok = (
            expected is not None
            and (expected.strip() if not sentinel else sentinel in expected)
        )
        if ok:
            break
        if attempt == 0:
            run_kanban([
                "task", "delete", "--task-id", task_id,
                "--project-path", spec["project_path"],
            ])
            print(f"deleted failed Cline task {task_id} "
                  "(verification failed); retrying once", flush=True)
            continue
        if expected is None:
            raise RuntimeError("expected file was not written in the Cline task worktree")
        if sentinel and sentinel not in expected:
            raise RuntimeError("expected smoke text was not written in the Cline task worktree")
        raise RuntimeError("expected file was written but is empty")

    patch, changed_files = collect_patch(worktree["path"], patch_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "job_key": spec["job_key"],
        "task_id": task_id,
        "title": task_title(spec),
        "column": final_task.get("column"),
        "session": final_task.get("session"),
        "worktree_branch": worktree.get("branch"),
        "expected_file": spec["expected_file"],
        "changed_files": changed_files,
        "patch_bytes": len(patch.encode()),
        "result": "review-ready",
    }
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(result, indent=2) + "\n")
    temp_path.replace(output_path)
    print(f"Nest adapter completed task {task_id}; diff={len(patch.encode())} bytes",
          flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--patch", required=True, type=Path)
    args = parser.parse_args()
    spec = validate_spec(json.loads(args.input.read_text()))
    run_bridge(spec, args.output, args.patch)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"cline-kanban-nest-bridge: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
