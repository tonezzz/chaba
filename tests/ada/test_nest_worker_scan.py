"""Regression fixture + benchmark for nest-worker queue discovery
(card jevnest-worker-scan-latency, OPS-1003).

History: a single --once scan took several minutes over 25+ Drive packs
because discovery issued one `rclone lsf` per pack plus one `rclone lsl`
per claim file and one `rclone cat` per candidate. Discovery now runs in
~2 rclone calls regardless of pack count: a single recursive
`lsf -F pt` (names+mtimes, so stale-claim checks ride the same listing)
and a single `copy --files-from` (pending pack.yml + preflight.json).

Pinned here:
  - plan_pass() stays O(1) in rclone calls over a 200-pack fixture
  - claim / stale-claim / needs / requires admission semantics unchanged
  - requires is re-checked at claim time (drain-in-one-pass preserved)

Live timing:  python3 tests/ada/test_nest_worker_scan.py \
                  --remote gdrive:ada-nest-kk-llm
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "scripts/ada/nest-worker.py"
FIXTURE = REPO / "tests/fixtures/nest-worker-queue.json"

spec = importlib.util.spec_from_file_location("nest_worker_scan", WORKER)
nw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nw)

REMOTE = "fake:ada-nest"


class FakeRemote:
    """Drive stand-in: {pack: {rel: (content, mtime_epoch)}}.

    Serves the rclone subcommands discovery uses — `lsf` (plain,
    --recursive, --format pt), `cat`, `lsl`, `copy --files-from`,
    `deletefile` — and counts every invocation."""

    def __init__(self, tree):
        self.tree = {p: dict(files) for p, files in tree.items()}
        self.calls = []

    @classmethod
    def from_fixture(cls, path, now=None):
        doc = json.loads(Path(path).read_text())
        now = time.time() if now is None else now
        tree = {}
        for pack, spec_ in doc["packs"].items():
            tree[pack] = {
                rel: (f.get("content", ""), now - f.get("age_s", 0))
                for rel, f in spec_["files"].items()}
        return cls(tree), doc

    @classmethod
    def scaled(cls, n_packs, now=None):
        """n_packs-1 done packs + one pending, for call-count bounds."""
        now = time.time() if now is None else now
        tree = {}
        for i in range(n_packs - 1):
            tree[f"pack-{i:04d}"] = {
                "pack.yml": (f"name: pack-{i:04d}\n", now - 80000),
                "done": ("ok", now - 70000),
                "claim/w-1": ("1700000000", now - 70000)}
        tree["zz-pending"] = {
            "pack.yml": ("name: zz-pending\n", now - 300)}
        return cls(tree)

    def _fmt(self, ts):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    def _recursive_lines(self):
        """`lsf packs --recursive -F pt`: dirs and files, sorted."""
        lines = []
        for pack in sorted(self.tree):
            files = self.tree[pack]
            mtimes = [m for _, m in files.values()]
            lines.append(f"{pack}/;{self._fmt(max(mtimes, default=0))}")
            for rel in sorted(files):
                _, m = files[rel]
                parts = rel.split("/")
                for i in range(1, len(parts)):
                    d = "/".join(parts[:i])
                    kids = [mm for r, (_, mm) in files.items()
                            if r.startswith(d + "/")]
                    lines.append(f"{pack}/{d}/;{self._fmt(max(kids))}")
                lines.append(f"{pack}/{rel};{self._fmt(m)}")
        return lines

    def rc(self, *args, check=True, timeout=900):
        args = list(args)
        self.calls.append(list(args))
        ok = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        fail = types.SimpleNamespace(returncode=1, stdout="",
                                     stderr="not found")
        op = args.pop(0)
        path = args.pop(0) if args else ""
        rel = path[len(REMOTE):].lstrip("/") if path.startswith(REMOTE) \
            else ""
        if op == "lsf":
            fmt_pt = ("--format" in args
                      and args[args.index("--format") + 1] == "pt")
            if "--recursive" in args:
                lines = self._recursive_lines()
            elif rel.rstrip("/") == "packs":
                lines = [f"{p}/" for p in sorted(self.tree)]
            elif rel.startswith("packs/"):
                sub = rel[len("packs/"):].rstrip("/")
                if "/" in sub:                  # packs/<pack>/<dir>
                    pack, d = sub.split("/", 1)
                    lines = sorted(
                        r[len(d) + 1:] + ("/" if any(
                            x.startswith(r[len(d) + 1:] + "/")
                            for x in self.tree.get(pack, {})) else "")
                        for r in self.tree.get(pack, {})
                        if r.startswith(d + "/"))
                else:                           # packs/<pack>
                    files = self.tree.get(sub, {})
                    tops = sorted({r.split("/")[0] for r in files})
                    lines = [t + "/" if any(r.startswith(t + "/")
                                            for r in files) else t
                             for t in tops]
            else:
                return fail
            if fmt_pt:
                if not "--recursive" in args and rel != "packs":
                    # non-recursive format-pt listing isn't used; support
                    # by tagging entries with pack mtime
                    pass
                ok.stdout = "\n".join(
                    l if ";" in l else f"{l}" for l in lines) + "\n"
            else:
                ok.stdout = "\n".join(
                    l.split(";")[0] for l in lines) + "\n"
            return ok
        if op == "cat":
            pack, _, r = rel[len("packs/"):].partition("/")
            entry = self.tree.get(pack, {}).get(r)
            if entry is None:
                return fail
            ok.stdout = entry[0]
            return ok
        if op == "lsl":
            pack, _, r = rel[len("packs/"):].partition("/")
            entry = self.tree.get(pack, {}).get(r)
            if entry is None:
                return fail
            ok.stdout = (f"{len(entry[0]):>8} {self._fmt(entry[1])}"
                         f".000000000 {r}\n")
            return ok
        if op == "deletefile":
            pack, _, r = rel[len("packs/"):].partition("/")
            self.tree.get(pack, {}).pop(r, None)
            return ok
        if op == "copy":
            dst = Path(args[0])
            lst = Path(args[args.index("--files-from") + 1]).read_text()
            for want in lst.split():
                pack, _, r = want.partition("/")
                entry = self.tree.get(pack, {}).get(r)
                if entry is None:
                    continue
                fp = dst / want
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(entry[0])
            return ok
        raise AssertionError(f"unexpected rclone op: {op} {args}")


def ops(fake):
    return [c[0] for c in fake.calls]


class ScanFixtureCase(unittest.TestCase):
    def setUp(self):
        self.fake, self.doc = FakeRemote.from_fixture(FIXTURE)
        self._old_rc = nw.rc
        self._old_caps = getattr(nw, "CAPS", None)
        nw.rc = self.fake.rc
        nw.CAPS = dict(self.doc["caps"])

    def tearDown(self):
        nw.rc = self._old_rc
        nw.CAPS = self._old_caps

    def plan(self):
        return nw.plan_pass(REMOTE, self.doc["stale_claim_min"])


class TestScanFixture(ScanFixtureCase):
    """Semantic matrix over tests/fixtures/nest-worker-queue.json."""

    def test_admission_matrix(self):
        candidates, releases, inv, meta = self.plan()
        names = [d for d, _ in candidates]
        # done/failed/live-claimed packs are invisible to discovery
        for absent in ("p01-done", "p02-failed", "p03-live-claim",
                       "p05-mixed-claims", "dep-done", "zz-preflight",
                       "zz2-preflight", "p07-needs-unmet", "p08-no-yml",
                       "p09-scalar-yml", "p15-empty-dir"):
            self.assertNotIn(absent, names, absent)
        for present in ("p04-stale-claim", "p06-pending",
                        "p10-requires-done-dep",
                        "p11-requires-preflight-fail",
                        "p13-requires-preflight-ok",
                        "p14-requires-undone-dep"):
            self.assertIn(present, names, present)
        # stale claims: released only when no live claim guards the pack
        rel = {(d, c) for d, c, _ in releases}
        self.assertEqual(rel, {("p04-stale-claim", "dead-worker-1"),
                               ("p05-mixed-claims", "dead-worker-2")})

    def test_requires_gate_at_claim_time(self):
        candidates, releases, inv, meta = self.plan()
        specs = {d: s for d, s in candidates}
        self.assertEqual(
            "", nw.requires_unmet(specs["p10-requires-done-dep"],
                                  REMOTE, inv, meta))
        self.assertIn("verdict",
                      nw.requires_unmet(specs["p11-requires-preflight-fail"],
                                        REMOTE, inv, meta))
        self.assertEqual(
            "", nw.requires_unmet(specs["p13-requires-preflight-ok"],
                                  REMOTE, inv, meta))
        self.assertIn("not done",
                      nw.requires_unmet(specs["p14-requires-undone-dep"],
                                        REMOTE, inv, meta))

    def test_drain_in_one_pass(self):
        """A dependency finished mid-pass unblocks dependents."""
        candidates, releases, inv, meta = self.plan()
        specs = {d: s for d, s in candidates}
        self.assertIn("not done",
                      nw.requires_unmet(specs["p14-requires-undone-dep"],
                                        REMOTE, inv, meta))
        # simulate p06-pending completing earlier in the same pass
        self.fake.tree["p06-pending"]["done"] = ("ok", time.time())
        nw.refresh_requires(specs["p14-requires-undone-dep"],
                            REMOTE, inv, meta)
        self.assertEqual(
            "", nw.requires_unmet(specs["p14-requires-undone-dep"],
                                  REMOTE, inv, meta))

    def test_discovery_call_bound(self):
        """Regression: discovery must not degrade to per-pack calls."""
        self.plan()
        n_lsf = sum(1 for c in self.fake.calls
                    if c[0] == "lsf" and "--recursive" in c)
        n_copy = sum(1 for c in self.fake.calls if c[0] == "copy")
        n_lsl = sum(1 for c in self.fake.calls if c[0] == "lsl")
        # one recursive listing + one batch fetch, that's all — pack.yml
        # presence is known from the inventory so even missing-yml packs
        # cost no extra call (p08, p15); never per-pack lsf/lsl/cat
        self.assertEqual(n_lsf, 1)
        self.assertEqual(n_copy, 1)
        self.assertEqual(n_lsl, 0)
        self.assertLessEqual(len(self.fake.calls), 2, str(ops(self.fake)))

    def test_fresh_claim_not_released(self):
        """A claim comfortably inside the stale window stays live."""
        now = time.time()
        self.fake.tree["edge-claim"] = {
            "pack.yml": ("name: edge-claim\n", now - 300),
            "claim/w": ("x", now - 3000)}     # 50min < 60min window
        candidates, releases, _, _ = self.plan()
        self.assertNotIn("edge-claim", [d for d, _ in candidates])
        self.assertEqual([], [r for r in releases if r[0] == "edge-claim"])


class TestScanBenchmark(ScanFixtureCase):
    """Call-count + wall-time bound at 200 packs."""

    def setUp(self):
        self.fake = FakeRemote.scaled(200)
        self._old_rc = nw.rc
        self._old_caps = getattr(nw, "CAPS", None)
        nw.rc = self.fake.rc
        nw.CAPS = {"gpu_gb": 0.0, "disk_gb": 1e6,
                   "egress_only_ok": False, "ram_gb": 1e6}
        self.doc = {"stale_claim_min": 60}

    def test_scale(self):
        t0 = time.time()
        candidates, releases, inv, meta = self.plan()
        dt = time.time() - t0
        self.assertEqual([d for d, _ in candidates], ["zz-pending"])
        self.assertLessEqual(len(self.fake.calls), 2,
                             f"{len(self.fake.calls)} calls: {ops(self.fake)}")
        self.assertLess(dt, 5.0, f"plan_pass took {dt:.1f}s on 200 packs")
        print(f"\n  bench: 200 packs -> {len(self.fake.calls)} calls, "
              f"{dt * 1000:.0f}ms")


def live(remote, stale_min):
    """Time real discovery against a Drive queue — read-only."""
    nw.CAPS = {"gpu_gb": 0.0, "disk_gb": 1e6,
               "egress_only_ok": False, "ram_gb": 1e6}
    t0 = time.time()
    candidates, releases, inv, meta = nw.plan_pass(remote, stale_min)
    dt = time.time() - t0
    print(f"remote={remote} packs={len(inv)} pending={len(candidates)} "
          f"stale={len(releases)} discovery={dt:.1f}s")
    for d, _ in candidates[:10]:
        print(f"  pending: {d}")


if __name__ == "__main__":
    if "--remote" in sys.argv:
        i = sys.argv.index("--remote")
        live(sys.argv[i + 1],
             int(sys.argv[sys.argv.index("--stale-min") + 1])
             if "--stale-min" in sys.argv else 60)
    else:
        unittest.main(verbosity=2)
