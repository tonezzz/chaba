"""Git helpers for focus dispatcher."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .state import (
    CURRENT,
    FOCUS,
    INBOX_DIR,
    PROCESSED_DIR,
    REPO,
)


def _is_allowed_staged_path(path):
    rel = Path(path).relative_to(REPO)
    if path in (str(CURRENT), str(FOCUS)):
        return True
    inbox_rel = Path("docs/ssot/focus-inbox")
    try:
        rel.relative_to(inbox_rel)
        return True
    except ValueError:
        pass
    return False


def git_mv_inbox(inbox_path):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    target = PROCESSED_DIR / inbox_path.name
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(inbox_path)],
        cwd=REPO,
        capture_output=True,
    ).returncode == 0
    if tracked:
        subprocess.run(
            ["git", "mv", str(inbox_path), str(target)],
            cwd=REPO,
            check=True,
        )
    else:
        shutil.move(str(inbox_path), str(target))
        subprocess.run(
            ["git", "add", str(target)],
            cwd=REPO,
            check=True,
        )
    return target


def _pull_rebase(repo):
    result = subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        cwd=repo, capture_output=True, text=True
    )
    if result.returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], cwd=repo, capture_output=True)
        raise RuntimeError(f"git pull --rebase --autostash failed: {result.stderr}")


def _push_with_retry(repo, attempts=3):
    for i in range(attempts):
        push = subprocess.run(["git", "push"], cwd=repo, capture_output=True, text=True)
        if push.returncode == 0:
            return
        # Remote moved; rebase onto it and retry.
        rebase = subprocess.run(
            ["git", "pull", "--rebase", "--autostash"],
            cwd=repo, capture_output=True, text=True
        )
        if rebase.returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=repo, capture_output=True)
            raise RuntimeError(f"git push failed and rebase retry failed: {rebase.stderr}")
    raise RuntimeError(f"git push failed after {attempts} attempts")


def git_commit(changed_paths, message):
    if not changed_paths:
        return
    unique_paths = sorted(set(str(p) for p in changed_paths))
    _pull_rebase(REPO)
    subprocess.run(["git", "add"] + unique_paths, cwd=REPO, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip().splitlines()
    for name in staged:
        if not _is_allowed_staged_path(REPO / name):
            print(f"[focus-dispatcher] warning: unexpected staged file will not be committed: {name}", file=sys.stderr)
    # Only commit the paths the dispatcher owns; leave any user-staged files staged.
    subprocess.run(["git", "commit", "-m", message, "--"] + unique_paths, cwd=REPO, check=True)
    if os.environ.get("FOCUS_DISPATCHER_PUSH") == "1":
        _push_with_retry(REPO)
