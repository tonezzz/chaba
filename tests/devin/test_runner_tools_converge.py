"""Stubbed-binary tests for scripts/devin/runner-tools-converge.sh.

OPS-1478 / card runner-tools-converge-local-scope-fix: the nightly unit
used to run deploy-runner-tools.yml fleet-wide FROM EVERY HOST — hosts
without ansible-playbook exited 1 and hosts with it failed --check on any
asleep fleet member (five false timer-alert cards, 2026-11-27). The script
must now (a) exit 0 with a skip note when ansible-playbook is absent,
(b) scope every playbook call to --limit <inventory_hostname>, and
(c) run the fleet pass only on the controller, over ping-reachable hosts.

No real ansible, ssh, systemd, or board-api is touched: every external
tool is a stub on PATH, and PATH contains ONLY the stub dir plus a dir of
symlinks to the handful of real tools the script needs (the real ansible
in /usr/bin must stay unreachable or the skip path can never trigger).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "devin" / "runner-tools-converge.sh"

# real binaries the script legitimately needs (never ansible itself)
REAL_TOOLS = ["bash", "env", "mkdir", "dirname", "awk", "sort", "grep",
              "paste", "cat", "rm", "python3", "uname", "tr", "printf"]

STUBS = {
    "ansible-playbook": """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_DIR/playbook.log"
exit "$(cat "$STUB_DIR/playbook.rc" 2>/dev/null || echo 0)"
""",
    "ansible-inventory": """#!/usr/bin/env bash
# --host <name>: succeed for hosts listed in $STUB_DIR/inventory, else fail
host=""
while [ $# -gt 0 ]; do
  [ "$1" = "--host" ] && { host="$2"; shift 2; continue; }
  shift
done
[ -n "$host" ] && grep -qx "$host" "$STUB_DIR/inventory" 2>/dev/null
""",
    "ansible": """#!/usr/bin/env bash
# only -m ping is used; emit one SUCCESS line per host in $STUB_DIR/ping_hosts
while read -r h; do [ -n "$h" ] && echo "$h | SUCCESS => {}"; done \\
  < "$STUB_DIR/ping_hosts"
exit 0
""",
    "hostname": """#!/usr/bin/env bash
cat "$STUB_DIR/fake_host"
""",
    "ssh": "#!/usr/bin/env bash\nexit 1\n",
}

INVENTORY = ["tony-dell", "tony-omen", "idc02", "idc03", "con01", "mn01",
             "tony-macbook"]


def _env(tmp_path: Path, fake_host: str, inventory: list[str],
         ping_hosts: list[str], ansible_present: bool = True) -> dict:
    stub_dir = tmp_path / "bin"
    tools_dir = tmp_path / "tools"
    home = tmp_path / "home"
    for d in (stub_dir, tools_dir, home, tmp_path / "tmp"):
        d.mkdir(parents=True, exist_ok=True)
    (stub_dir / "fake_host").write_text(fake_host + "\n")
    (stub_dir / "inventory").write_text("\n".join(inventory) + "\n")
    (stub_dir / "ping_hosts").write_text("\n".join(ping_hosts) + "\n")
    for name, body in STUBS.items():
        if not ansible_present and name.startswith("ansible"):
            continue
        p = stub_dir / name
        p.write_text(body)
        p.chmod(0o755)
    for tool in REAL_TOOLS:
        src = Path("/usr/bin") / tool
        if not src.exists():
            src = Path("/bin") / tool
        if src.exists():
            os.symlink(src, tools_dir / tool)
    env = dict(os.environ)
    env.update({
        "PATH": f"{stub_dir}:{tools_dir}",
        "HOME": str(home),
        "TMPDIR": str(tmp_path / "tmp"),
        "STUB_DIR": str(stub_dir),
    })
    return env


def _run(tmp_path: Path, fake_host: str, inventory: list[str],
         ping_hosts: list[str] | None = None,
         ansible_present: bool = True,
         extra_env: dict | None = None,
         playbook_rc: int = 0) -> tuple[subprocess.CompletedProcess, list[str]]:
    env = _env(tmp_path, fake_host, inventory,
               ping_hosts if ping_hosts is not None else inventory,
               ansible_present)
    if extra_env:
        env.update(extra_env)
    stub_dir = tmp_path / "bin"
    (stub_dir / "playbook.rc").write_text(str(playbook_rc))
    proc = subprocess.run(["bash", str(SCRIPT)], env=env,
                          capture_output=True, text=True, timeout=60)
    log = stub_dir / "playbook.log"
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def test_skip_exit0_when_ansible_absent(tmp_path):
    proc, calls = _run(tmp_path, "idc03", INVENTORY, ansible_present=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SKIP" in proc.stdout
    assert calls == []


def test_local_scope_uses_hostname_limit(tmp_path):
    proc, calls = _run(tmp_path, "idc03", INVENTORY, ping_hosts=[])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert calls, "expected playbook invocations"
    for call in calls:
        assert "--limit idc03" in call, call
        assert ("deploy-runner-tools.yml" in call
                or "audit-runner-tools.yml" in call)
    # non-controller must not run the fleet ping probe -> no fleet pass
    assert not any("idc02" in c or "mn01" in c for c in calls)


def test_controller_runs_fleet_pass_over_reachable(tmp_path):
    proc, calls = _run(tmp_path, "tony-dell", INVENTORY,
                       ping_hosts=["tony-dell", "idc02", "mn01"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    fleet = [c for c in calls if "--limit idc02:mn01" in c]
    assert fleet, f"expected fleet-scoped calls, got: {calls}"
    # self excluded from the fleet limit; unreachable hosts absent
    for call in fleet:
        assert "tony-omen" not in call and "idc03" not in call


def test_controller_skips_fleet_when_only_self_reachable(tmp_path):
    proc, calls = _run(tmp_path, "tony-dell", INVENTORY,
                       ping_hosts=["tony-dell"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    limited = [c for c in calls if "--limit" in c]
    assert limited and all("--limit tony-dell" in c for c in limited)
    assert not any("idc02" in c for c in calls)


def test_unknown_hostname_fails_loudly(tmp_path):
    proc, calls = _run(tmp_path, "bogus-host", INVENTORY)
    assert proc.returncode == 1
    assert "not in the ansible inventory" in proc.stdout
    assert calls == []


def test_check_failure_propagates(tmp_path):
    proc, calls = _run(tmp_path, "idc02", INVENTORY, ping_hosts=[],
                       playbook_rc=2)
    assert proc.returncode == 1
    assert "check failed" in proc.stdout


def test_fleet_env_override_from_non_controller(tmp_path):
    proc, calls = _run(tmp_path, "idc02", INVENTORY,
                       ping_hosts=["idc02", "idc03"],
                       extra_env={"RUNNER_CONVERGE_FLEET": "1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert any("--limit idc03" in c for c in calls)


def _scratch_repo(tmp_path: Path, dirty: bool) -> Path:
    """Minimal checkout with one pinned source, optionally locally edited."""
    repo = tmp_path / "scratch-repo"
    (repo / "scripts" / "devin").mkdir(parents=True)
    (repo / "ansible").mkdir()
    shutil.copy2(SCRIPT, repo / "scripts" / "devin" / "runner-tools-converge.sh")
    good = "#!/bin/sh\necho fixture\n"
    source = repo / "scripts" / "devin" / "manifest-fixture.sh"
    source.write_text(good + "# uncommitted WIP\n" if dirty else good)
    manifest = {
        "schemaVersion": 1,
        "tools": {
            "fixture": {
                "source": "scripts/devin/manifest-fixture.sh",
                "dest": "manifest-fixture",
                "sha256": hashlib.sha256(good.encode()).hexdigest(),
            }
        },
    }
    (repo / "scripts" / "devin" / "runner-tooling.manifest.json").write_text(
        json.dumps(manifest))
    return repo


def test_dirty_pinned_source_skips_all_playbooks(tmp_path):
    repo = _scratch_repo(tmp_path, dirty=True)
    proc, calls = _run(tmp_path, "idc02", INVENTORY, ping_hosts=[],
                       extra_env={"RUNNER_CONVERGE_ROOT": str(repo)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DIRTY_PINNED_SOURCES" in proc.stdout
    assert "manifest-fixture.sh" in proc.stdout
    assert "skip this pass" in proc.stdout
    assert calls == [], "a dirty checkout must not deploy unpinned bytes"


def test_clean_pinned_source_proceeds(tmp_path):
    repo = _scratch_repo(tmp_path, dirty=False)
    proc, calls = _run(tmp_path, "idc02", INVENTORY, ping_hosts=[],
                       extra_env={"RUNNER_CONVERGE_ROOT": str(repo)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PINNED_SOURCES_OK" in proc.stdout
    assert calls and all("--limit idc02" in c for c in calls)
