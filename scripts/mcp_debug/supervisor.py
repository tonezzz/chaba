"""MCP stdio supervisor: one child mcp_debug.server process, auto-reloaded on source/SSOT changes."""
import atexit
import glob
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GLOBS = [
    REPO / "scripts" / "mcp_debug" / "*.py",
    REPO / "scripts" / "focus_common.py",
    REPO / "scripts" / "prompt_preprocessor.py",
    REPO / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug*.yml",
    REPO / "docs" / "ssot" / "infrastructure" / "ssot.health*.yml",
    REPO / "docs" / "ssot" / "infrastructure" / "ssot.services.yml",
]
IDLE_TIMEOUT = 1.5
POLL_INTERVAL = 1.0
DEBOUNCE = 0.5


def _mtimes():
    m = {}
    for g in GLOBS:
        for p in glob.glob(str(g)):
            try:
                m[p] = os.path.getmtime(p)
            except OSError:
                pass
    return m


def _mtimes_changed(old, new):
    if set(old.keys()) != set(new.keys()):
        return True
    for k, v in new.items():
        if old.get(k) != v:
            return True
    return False


def _start_child():
    env = os.environ.copy()
    scripts = str(REPO / "scripts")
    env["PYTHONPATH"] = scripts + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.Popen(
        [sys.executable, "-m", "mcp_debug.server"],
        cwd=str(REPO),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )


def _kill_child(child):
    if child is None or child.poll() is not None:
        return
    try:
        child.stdin.close()
    except Exception:
        pass
    try:
        child.terminate()
    except Exception:
        pass
    try:
        child.wait(1.0)
    except Exception:
        try:
            child.kill()
        except Exception:
            pass


def _stdout_forwarder(child, state):
    while True:
        try:
            data = child.stdout.read(8192)
        except OSError:
            break
        if not data:
            break
        with state["lock"]:
            state["last_activity"] = time.time()
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except OSError:
            break


def _stderr_forwarder(child, state):
    while True:
        try:
            data = child.stderr.read(8192)
        except OSError:
            break
        if not data:
            break
        try:
            sys.stderr.buffer.write(data)
            sys.stderr.buffer.flush()
        except OSError:
            break


def _stdin_forwarder(state):
    while True:
        try:
            data = sys.stdin.buffer.read(8192)
        except OSError:
            break
        if not data:
            with state["lock"]:
                state["stdin_closed"] = True
                child = state["child"]
            try:
                if child:
                    child.stdin.close()
            except Exception:
                pass
            break
        with state["lock"]:
            state["last_activity"] = time.time()
        while not state["stop"]:
            with state["lock"]:
                child = state["child"]
            if child is None:
                time.sleep(0.05)
                continue
            try:
                child.stdin.write(data)
                child.stdin.flush()
                break
            except (BrokenPipeError, OSError):
                time.sleep(0.05)
                continue


def _watcher(state, restart_event, pending, last_change, mt):
    while not state["stop"]:
        time.sleep(POLL_INTERVAL)
        with state["lock"]:
            child = state["child"]
            stdin_closed = state["stdin_closed"]
        if child and child.poll() is not None and not stdin_closed:
            pending[0] = True
            last_change[0] = time.time()
            restart_event.set()
        new_m = _mtimes()
        if _mtimes_changed(mt[0], new_m):
            mt[0] = new_m
            if not stdin_closed:
                pending[0] = True
                last_change[0] = time.time()
                restart_event.set()


def _restart(state):
    old = None
    with state["lock"]:
        old = state["child"]
        state["child"] = None
    if old is not None:
        _kill_child(old)
    new = _start_child()
    with state["lock"]:
        state["child"] = new
        state["last_activity"] = time.time()
    threading.Thread(target=_stdout_forwarder, args=(new, state), daemon=True).start()
    threading.Thread(target=_stderr_forwarder, args=(new, state), daemon=True).start()


def _shutdown(state):
    with state["lock"]:
        state["stop"] = True
        child = state["child"]
    _kill_child(child)


def _cleanup(state):
    with state["lock"]:
        child = state["child"]
    _kill_child(child)


def main():
    state = {
        "child": None,
        "last_activity": time.time(),
        "stop": False,
        "stdin_closed": False,
        "lock": threading.Lock(),
    }
    restart_event = threading.Event()
    pending = [False]
    last_change = [time.time()]
    mt = [_mtimes()]

    threading.Thread(target=_watcher, args=(state, restart_event, pending, last_change, mt), daemon=True).start()
    _restart(state)
    threading.Thread(target=_stdin_forwarder, args=(state,), daemon=True).start()

    signal.signal(signal.SIGTERM, lambda s, f: _shutdown(state))
    signal.signal(signal.SIGINT, lambda s, f: _shutdown(state))
    atexit.register(_cleanup, state)

    while not state["stop"]:
        if restart_event.is_set() and pending[0]:
            with state["lock"]:
                stdin_closed = state["stdin_closed"]
            if stdin_closed:
                state["stop"] = True
                break
            now = time.time()
            if now - state["last_activity"] > IDLE_TIMEOUT and now - last_change[0] > DEBOUNCE:
                _restart(state)
                pending[0] = False
                restart_event.clear()
                mt[0] = _mtimes()
            else:
                time.sleep(0.1)
        else:
            time.sleep(0.2)
        with state["lock"]:
            child = state["child"]
            stdin_closed = state["stdin_closed"]
        if child and child.poll() is not None and stdin_closed:
            state["stop"] = True
            break

    _cleanup(state)
    sys.exit(0)


if __name__ == "__main__":
    main()
