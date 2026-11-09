"""nest-worker ready-marker enforcement (OPS-1002 atomic-3-3).

Policy contract:
  auto -> 'required' on the dedicated kk-llm queue, 'optional' elsewhere
  required: unsealed pack (absent/invalid `ready`) is never claimable
  optional: absent marker = legacy pack, claimable; a present marker
            must validate against the remote manifest
"""
from __future__ import annotations

import importlib.util
import json
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "scripts" / "ada" / "nest-worker.py"
NPR = REPO / "scripts" / "ada" / "nest_pack_ready.py"

spec = importlib.util.spec_from_file_location("nest_worker_ready", WORKER)
nw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nw)
npr = importlib.util.spec_from_file_location("npr_mod", NPR)
npr_mod = importlib.util.module_from_spec(npr)
npr.loader.exec_module(npr_mod)

KK_REMOTE = "fake:ada-nest/kk-llm"
GEN_REMOTE = "fake:ada-nest"
NOW = time.time()


class Result:
    def __init__(self, stdout="", rc=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, rc, stderr


class FakeRemote:
    """{pack: {rel: (content, mtime)}} under <remote>/packs/; serves the
    rclone subcommands plan_pass + ready_check issue and counts calls."""

    def __init__(self, remote, tree):
        self.remote = remote
        self.tree = {p: dict(files) for p, files in tree.items()}
        self.calls = []

    def _fmt(self, ts):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    def _entries(self):
        for pack, files in self.tree.items():
            for rel, (content, ts) in files.items():
                yield pack, rel, content, ts
            if not files:
                yield pack, "", "", NOW

    def rc(self, *args, check=True, timeout=900):
        self.calls.append(args)
        cmd = args[0]
        if cmd == "lsf":
            path = args[1].rstrip("/")
            fmt = ""
            if "--format" in args:
                fmt = args[args.index("--format") + 1]
            packs_root = f"{self.remote}/packs"
            lines = []
            if path == packs_root and "--recursive" in args:
                for pack, rel, content, ts in self._entries():
                    full = f"{pack}/{rel}" if rel else pack + "/"
                    if fmt == "pt":
                        lines.append(f"{full};{self._fmt(ts)}")
                    elif fmt == "sp":
                        lines.append(f"{len(content)};{full}")
                    else:
                        lines.append(full)
            elif path.startswith(packs_root + "/"):
                pack = path[len(packs_root) + 1:]
                for p, rel, content, ts in self._entries():
                    if p != pack:
                        continue
                    if fmt == "pt":
                        lines.append(f"{rel};{self._fmt(ts)}")
                    elif fmt == "sp":
                        lines.append(f"{len(content)};{rel}")
                    else:
                        lines.append(rel)
            elif path == packs_root:
                lines = [p + "/" for p in self.tree]
            return Result("\n".join(lines))
        if cmd == "cat":
            path = args[1]
            pre = "/packs/"
            if pre in path:
                rest = path.split(pre, 1)[1]
                pack, _, rel = rest.partition("/")
                if rel in self.tree.get(pack, {}):
                    return Result(self.tree[pack][rel][0])
            return Result(rc=1, stderr="not found")
        if cmd == "copy" and "--files-from" in args:
            lst = args[args.index("--files-from") + 1]
            tmp = args[2]
            for rel in Path(lst).read_text().splitlines():
                rel = rel.strip()
                if not rel:
                    continue
                pack, _, sub = rel.partition("/")
                if sub in self.tree.get(pack, {}):
                    dest = Path(tmp) / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(self.tree[pack][sub][0])
            return Result()
        if cmd in ("deletefile", "check"):
            return Result()
        raise RuntimeError(f"unmocked rc {args}")


def tree_with(packs):
    """packs: {name: {rel: content}}; mtimes = NOW."""
    return {p: {r: (c, NOW) for r, c in files.items()}
            for p, files in packs.items()}


def seal(files):
    """Marker text for a pack's file dict {rel: content}."""
    entries = {r: len(c) for r, c in files.items()}
    return json.dumps(npr_mod.make_marker(entries, "test"))


def candidates(remote, tree, policy="auto"):
    fake = FakeRemote(remote, tree)
    orig_rc, orig_caps = nw.rc, getattr(nw, "CAPS", None)
    nw.rc = fake.rc
    nw.CAPS = {"gpu_gb": 99.0, "disk_gb": 999.0,
               "egress_only_ok": True, "ram_gb": 99.0}
    try:
        cand, releases, inv, meta = nw.plan_pass(remote, 60, policy)
    finally:
        nw.rc = orig_rc
        nw.CAPS = orig_caps
    return [d for d, _ in cand], fake


class ReadyPolicyTests(unittest.TestCase):
    def test_auto_required_on_kk_llm(self):
        self.assertEqual(nw.resolve_ready_policy(KK_REMOTE, "auto"),
                         "required")
        self.assertEqual(nw.resolve_ready_policy(
            "fake:ada-nest-kk-llm", "auto"), "required")
        self.assertEqual(nw.resolve_ready_policy(GEN_REMOTE, "auto"),
                         "optional")

    def test_required_skips_unsealed_pack(self):
        tree = tree_with({"kk-mac-task-x": {"pack.yml": "name: x\n"}})
        cand, _ = candidates(KK_REMOTE, tree)
        self.assertEqual(cand, [])

    def test_required_accepts_valid_seal(self):
        files = {"pack.yml": "name: kk-mac-task-x\n",
                 "inputs/task.json": "{}"}
        files["ready"] = seal(files)
        tree = tree_with({"kk-mac-task-x": files})
        cand, _ = candidates(KK_REMOTE, tree)
        self.assertEqual(cand, ["kk-mac-task-x"])

    def test_required_rejects_corrupt_seal(self):
        files = {"pack.yml": "name: kk-mac-task-x\n",
                 "inputs/task.json": "{}"}
        marker = json.loads(seal(files))
        files["inputs/extra.json"] = "tampered-after-seal"
        files["ready"] = json.dumps(marker)
        tree = tree_with({"kk-mac-task-x": files})
        cand, _ = candidates(KK_REMOTE, tree)
        self.assertEqual(cand, [])

    def test_required_rejects_unparseable_marker(self):
        files = {"pack.yml": "name: kk-mac-task-x\n", "ready": "not json"}
        tree = tree_with({"kk-mac-task-x": files})
        cand, _ = candidates(KK_REMOTE, tree)
        self.assertEqual(cand, [])

    def test_optional_allows_unmarked_legacy_pack(self):
        tree = tree_with({"legacy-pack": {"pack.yml": "name: l\n"}})
        cand, _ = candidates(GEN_REMOTE, tree)
        self.assertEqual(cand, ["legacy-pack"])

    def test_optional_rejects_corrupt_marker(self):
        files = {"pack.yml": "name: p\n", "ready": "{}"}
        tree = tree_with({"p": files})
        cand, _ = candidates(GEN_REMOTE, tree)
        self.assertEqual(cand, [])

    def test_terminal_and_claimed_unchanged(self):
        sealed = {"pack.yml": "x", "ready": "{}", "done": "ok"}
        claimed = {"pack.yml": "x", "ready": "{}", "claim/w": "1"}
        tree = tree_with({"done-pack": sealed, "claimed-pack": claimed})
        cand, _ = candidates(KK_REMOTE, tree)
        self.assertEqual(cand, [])


if __name__ == "__main__":
    unittest.main()
