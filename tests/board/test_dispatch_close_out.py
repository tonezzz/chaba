"""End-to-end tests for the dispatch close-out merge step
(scripts/board/dispatch_repos.py — card dispatch-auto-merge).

Builds a bare origin + main clone + dispatch session worktree in a tmpdir
and exercises: checkpoint commit of leftovers, always-push, the
expected_goals gate, --no-ff merge, safe-pull conflict policy (generated
paths auto-resolve, real conflicts report), and the silent no-op path.

No network, no systemd — all git ops stay inside the tmpdir.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import dispatch_repos as dr  # noqa: E402

TID = "20990101-000000-test-close-out"


def _pytest_on(*bins: str) -> bool:
    """All listed interpreters can import pytest."""
    return all(
        subprocess.run([b, "-c", "import pytest"],
                       capture_output=True).returncode == 0
        for b in bins)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True)


def commit(repo: Path, path: str, content: str, msg: str) -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    git(repo, "add", path)
    r = git(repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", msg)
    assert r.returncode == 0, r.stderr


class Case(unittest.TestCase):
    """One fixture per test: origin(bare) + main(clone) + session wt."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._old_dir = os.environ.get("DISPATCH_DIR")
        os.environ["DISPATCH_DIR"] = str(self.tmp / "dispatch")
        # hermetic git identity — the close_out merge needs a committer;
        # hosts without a global user.name/email would fail the fixture
        self._old_ident = {k: os.environ.get(k) for k in (
            "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")}
        os.environ.update({
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        r = subprocess.run(["git", "init", "-q", "--bare",
                            "-b", "master", str(self.origin)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(seed)], capture_output=True)
        commit(seed, "file.txt", "base\n", "base")
        commit(seed, "docs/ssot/gen.yml", "v: 0\n", "gen0")
        # a tests/ dir so the merged tree engages the test gate
        commit(seed, "tests/test_smoke.py",
               "def test_ok():\n    assert True\n", "tests")
        r = git(seed, "push", "-q", "-u", "origin", "master")
        assert r.returncode == 0, r.stderr

        self.main = self.tmp / "main"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.main)], capture_output=True)
        # the dispatch session worktree + branch
        self.wt = self.tmp / f"dispatch-wt-{TID}"
        r = git(self.main, "worktree", "add", "-q", str(self.wt),
                "-b", f"dispatch/{TID}", "origin/master")
        assert r.returncode == 0, r.stderr
        task = self.tmp / "dispatch" / "tasks" / TID
        task.mkdir(parents=True)
        (task / "meta.json").write_text(json.dumps(
            {"repo": "chaba", "worktree": str(self.wt),
             "branch": f"dispatch/{TID}",
             "unit": f"devin-task-{TID}"}))
        self.card = {"id": "test-card",
                     "action": {"type": "dispatch", "task_id": TID,
                                "repo": "chaba"}}

    def tearDown(self) -> None:
        if self._old_dir is None:
            os.environ.pop("DISPATCH_DIR", None)
        else:
            os.environ["DISPATCH_DIR"] = self._old_dir
        for k, v in self._old_ident.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def remote_has(self, ref: str, path: str) -> bool:
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             f"{ref}:{path}"], capture_output=True, text=True)
        return r.returncode == 0

    def test_happy_path_merges_and_checkpoints(self):
        commit(self.wt, "feature.py", "print('hi')\n", "work")
        (self.wt / "dispatch-outcome-2099.md").write_text("outcome\n")
        (self.wt / "docs/ssot/jobs/kanban/x.yml").parent.mkdir(
            parents=True, exist_ok=True)
        (self.wt / "docs/ssot/jobs/kanban/x.yml").write_text("job: 1\n")

        res = dr.close_out(self.card)

        self.assertTrue(res["merged"], res)
        self.assertFalse(res.get("noop"))
        cp = res["checkpoint"]
        self.assertTrue(cp["committed"], cp)
        self.assertEqual(cp["files"], 2)          # two leftovers
        self.assertEqual(dr.dirty_count(self.wt), 0)
        self.assertTrue(res.get("pushed"), res)
        # branch really on origin
        r = git(self.main, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"dispatch/{TID}", r.stdout)
        # merge commit landed with --no-ff (two parents) on origin/master
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "cat-file", "-p",
             "master"], capture_output=True, text=True)
        self.assertGreaterEqual(r.stdout.count("\nparent "), 2, r.stdout)
        self.assertTrue(self.remote_has("master", "feature.py"))
        self.assertTrue(
            self.remote_has("master", "dispatch-outcome-2099.md"))
        notes = dr.close_out_notes(res)
        self.assertTrue(any("auto-merged" in n for n in notes), notes)
        self.assertTrue(any("checkpoint" in n for n in notes), notes)

    def test_noop_run_skips_silently(self):
        # branch exists but produced nothing — head == base tip is NOT
        # merged work (a 'merged' stamp would false-positive verified)
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"])
        self.assertTrue(res["noop"])
        self.assertEqual(dr.close_out_notes(res),
                         [n for n in dr.close_out_notes(res)
                          if "pushed" in n or "checkpoint" in n])

    def test_real_conflict_reports_paths(self):
        commit(self.wt, "file.txt", "session\n", "session change")
        commit(self.main, "file.txt", "upstream\n", "upstream change")
        r = git(self.main, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr

        res = dr.close_out(self.card)

        self.assertFalse(res["merged"], res)
        self.assertEqual(res["conflicts"], ["file.txt"], res)
        self.assertIn("upstream", subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             "master:file.txt"], capture_output=True, text=True).stdout)
        notes = dr.close_out_notes(res)
        self.assertTrue(any("conflict" in n and "file.txt" in n
                            for n in notes), notes)

    def test_generated_conflict_auto_resolves(self):
        commit(self.wt, "docs/ssot/gen.yml", "v: session\n", "gen-s")
        commit(self.main, "docs/ssot/gen.yml", "v: upstream\n", "gen-u")
        r = git(self.main, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr

        res = dr.close_out(self.card)

        self.assertTrue(res["merged"], res)
        out = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             "master:docs/ssot/gen.yml"], capture_output=True,
            text=True).stdout
        self.assertIn("upstream", out)  # safe-pull: upstream wins

    def test_goals_gate_holds_merge(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self.card["expected_goals"] = [
            {"id": "nope", "check": "command false"},
            {"id": "yes", "check": "command true"}]
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"])
        self.assertTrue(res["gate"]["ran"])
        self.assertEqual(res["gate"]["bad"], ["nope"])
        notes = dr.close_out_notes(res)
        self.assertTrue(any("expected_goals" in n for n in notes), notes)
        # the branch still pushed — work is not stranded
        r = git(self.main, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"dispatch/{TID}", r.stdout)

    def test_goals_gate_pass_merges(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self.card["expected_goals"] = [
            {"id": "built", "check": "file-exists feature.py"}]
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)

    def test_malformed_goals_block(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self.card["expected_goals"] = [
            {"id": "prose", "check": "make it work"}]
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"])
        self.assertFalse(res["gate"]["ok"])

    # -------------------------------------------------- shadow guard
    # gitignored-dir shadow paths (card dispatch-gitignore-shadow-guard,
    # the 2026-10-10 .venv incident): a clean merge is held pre-push when
    # the branch adds a symlink or a file whose name is ignored only as
    # a directory.

    def test_shadow_symlink_holds_merge(self):
        commit(self.wt, ".gitignore", ".venv/\n", "ignore venv dir")
        os.symlink("/nonexistent/venv", self.wt / ".venv")
        git(self.wt, "add", ".venv")
        r = git(self.wt, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-qm", "worktree venv")
        assert r.returncode == 0, r.stderr
        commit(self.wt, "feature.py", "x=1\n", "work")

        res = dr.close_out(self.card)

        self.assertFalse(res["merged"], res)
        self.assertTrue(res["shadows"], res)
        self.assertTrue(any(".venv" in s for s in res["shadows"]),
                        res["shadows"])
        # nothing reached origin/master — but the branch still pushed,
        # so the work isn't stranded for the fix
        self.assertFalse(self.remote_has("master", ".venv"))
        self.assertFalse(self.remote_has("master", "feature.py"))
        r = git(self.main, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"dispatch/{TID}", r.stdout)
        notes = dr.close_out_notes(res)
        self.assertTrue(any("shadow" in n and ".venv" in n
                            for n in notes), notes)
        # the board-api merge guard surfaces the same paths in its
        # unmerged-commits note
        g = dr.guard(self.card)
        self.assertFalse(g["allowed"])
        self.assertIn("shadow", g["note"])

    def test_shadow_dirpattern_file_holds_merge(self):
        # plain file named like an ignored dir — the `.venv/` pattern
        # here is `cache/`; the blob `cache` is trackable yet shadows it.
        commit(self.wt, ".gitignore", "cache/\n", "ignore cache dir")
        commit(self.wt, "cache", "oops a file\n", "not a dir")
        commit(self.wt, "feature.py", "x=1\n", "work")

        res = dr.close_out(self.card)

        self.assertFalse(res["merged"], res)
        self.assertTrue(any("cache" in s and "cache/" in s
                            for s in res["shadows"]), res["shadows"])
        self.assertFalse(self.remote_has("master", "cache"))

    def test_shadow_detector_direct(self):
        # unit-level: shadow_paths flags modes/patterns, stays quiet
        # for ordinary adds.
        commit(self.wt, ".gitignore", "cache/\n*.log\n", "ignores")
        os.symlink("/nonexistent", self.wt / ".venv")
        (self.wt / "debug.log").write_text("ignored anyway\n")
        git(self.wt, "add", "-f", ".venv", "debug.log")
        r = git(self.wt, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-qm", "shadow batch")
        assert r.returncode == 0, r.stderr
        commit(self.wt, "cache", "file\n", "shadow file")
        commit(self.wt, "plain.py", "x=1\n", "clean add")
        flags = dr.shadow_paths(self.wt, "origin/master", "HEAD")
        self.assertTrue(any(s.startswith(".venv") and "symlink" in s
                            for s in flags), flags)
        self.assertTrue(any(s.startswith("cache") for s in flags),
                        flags)
        # debug.log is ignored as a file — not a dir-shadow; plain.py
        # is clean
        self.assertFalse(any(s.startswith("debug.log")
                             for s in flags), flags)
        self.assertFalse(any(s.startswith("plain.py")
                             for s in flags), flags)

    def test_missing_session_is_silent_noop(self):
        card = {"id": "nope",
                "action": {"type": "dispatch", "task_id": "gone",
                           "repo": "chaba"}}
        res = dr.close_out(card)
        self.assertFalse(res["merged"])
        self.assertTrue(res.get("skipped"))

    # ------------------------------------------------------ test gate
    # The merged tree always has tests/ (seeded above); REPO_TESTS["chaba"]
    # is pointed at fake commands so the suite doesn't depend on a real
    # pytest install.

    def _with_test_gate(self, cfg: dict) -> None:
        old = dr.REPO_TESTS.get("chaba")
        dr.REPO_TESTS["chaba"] = cfg

        def restore():
            if old is None:
                dr.REPO_TESTS.pop("chaba", None)
            else:
                dr.REPO_TESTS["chaba"] = old
        self.addCleanup(restore)

    def test_gate_red_suite_holds_merge(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate({
            "command": "echo 'FAILED tests/test_x.py::test_broke - assert "
                       "False' >&2; exit 1",
            "timeout": 30})
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"], res)
        self.assertTrue(res["tests"]["ran"])
        self.assertFalse(res["tests"]["ok"])
        self.assertEqual(res["test_failures"],
                         ["tests/test_x.py::test_broke"])
        # the merged tree must NOT be on origin — but the branch pushed,
        # so the work isn't stranded for the retry
        self.assertFalse(self.remote_has("master", "feature.py"))
        r = git(self.main, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"dispatch/{TID}", r.stdout)
        notes = dr.close_out_notes(res)
        self.assertTrue(any("test gate" in n and "test_broke" in n
                            for n in notes), notes)

    def test_gate_green_merges_and_notes(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate({"command": "exit 0", "timeout": 30})
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertTrue(res["tests"]["ok"])
        self.assertTrue(self.remote_has("master", "feature.py"))
        self.assertTrue(any("test gate passed" in n
                            for n in dr.close_out_notes(res)))

    def test_gate_off_switch_merges(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        os.environ["KANBAN_TESTGATE"] = "0"
        self.addCleanup(os.environ.pop, "KANBAN_TESTGATE")
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertFalse(res["tests"]["ran"])
        self.assertEqual(res["tests"]["skipped"], "KANBAN_TESTGATE=0")

    def test_gate_timeout_holds_merge(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate({"command": "sleep 5", "timeout": 1})
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"], res)
        self.assertTrue(any("timeout" in f
                            for f in res.get("test_failures") or []),
                        res)
        self.assertIn("timed out", res["tests"]["error"])

    def test_gate_missing_runner_fails_open(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate(
            {"command": "no-such-pytest-bin-ci-test-gate", "timeout": 10})
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertIn("fail-open", res["tests"]["skipped"])

    def test_gate_no_tests_dir_skips(self):
        bare = self.tmp / "no-tests"
        bare.mkdir()
        r = dr.run_test_gate(bare, "chaba")
        self.assertTrue(r["ok"])
        self.assertFalse(r["ran"])
        self.assertIn("no tests", r["skipped"])

    # ----------------------------------------- venv interpreter gate
    # Card dispatch-test-gate-venv — the 2026-10-13 line-multihome
    # incident: ada-voice's suite is green only under the checkout's .venv
    # (google.genai etc.); system python3 went red and held a good merge.
    # The gate now resolves the interpreter per repo: an explicit
    # REPO_TESTS "python" pin, then the first {tree under test, canonical
    # checkout, repos.conf path}/{.venv,venv}/bin/python[3] that can
    # `import pytest`, else system python3. A venv WITHOUT pytest must
    # not win — chaba's venv/ has none, and picking it would silently
    # fail-open the gate.

    def _pin_repos_conf(self):
        """Hermetic repo table — point 'chaba' at the fixture checkout so
        venv resolution never touches real host paths."""
        conf = Path(os.environ["DISPATCH_DIR"]) / "repos.conf"
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(f"chaba {self.main} master\n")

    def _make_venv(self, root: Path, shim: str) -> Path:
        """Create <root>/.venv/bin/python from a shell shim body."""
        py = root / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text(shim)
        py.chmod(0o755)
        return py

    @unittest.skipUnless(_pytest_on("python3", sys.executable),
                         "pytest not installed")
    def test_gate_venv_python_unholds_merge(self):
        """The incident e2e: a suite red under system python (missing
        dep) goes green under the canonical checkout's .venv — the
        merge must land instead of being held."""
        self._pin_repos_conf()
        commit(self.wt, "tests/test_venvdep.py",
               "import venv_only_dep\n"
               "def test_dep():\n"
               "    assert venv_only_dep.answer == 42\n",
               "dep test")
        # the held-merge half: with no venv resolvable, system python3
        # cannot import the dep — the suite is red, exactly what held
        # the line-multihome merge
        r = dr.run_test_gate(self.wt, "chaba")
        self.assertFalse(r["ok"], r)
        self.assertTrue(r["command"].startswith("python3 "), r)
        self.assertTrue(any("venvdep" in f for f in r["failed"]), r)
        # the canonical checkout's .venv carries the dep. A shell shim
        # stands in for the venv python (real venvs are symlink +
        # pyvenv.cfg; the gate only needs an executable that can import
        # pytest and see the dep).
        lib = self.tmp / "venvlib"
        lib.mkdir()
        (lib / "venv_only_dep.py").write_text("answer = 42\n")
        py = self._make_venv(
            self.main,
            "#!/bin/sh\n"
            f"export PYTHONPATH={lib}\n"
            f'exec "{sys.executable}" "$@"\n')
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertTrue(res["tests"]["ok"], res)
        self.assertEqual(res["tests"]["python"], str(py))
        self.assertIn(".venv/bin/python", res["tests"]["command"])
        self.assertTrue(
            self.remote_has("master", "tests/test_venvdep.py"))

    def test_gate_skips_venv_without_pytest(self):
        """A venv whose python can't import pytest must not win —
        otherwise the gate fail-opens and stops testing entirely."""
        self._pin_repos_conf()
        commit(self.wt, "feature.py", "x=1\n", "work")
        # -S drops site-packages: the shim runs but `import pytest` fails
        self._make_venv(self.main,
                        "#!/bin/sh\nexec python3 -S \"$@\"\n")
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertEqual(res["tests"]["python"], "python3")
        self.assertTrue(
            res["tests"]["command"].startswith("python3 "),
            res["tests"])

    def test_gate_prefers_tree_venv_over_checkout(self):
        """Order: the tree under test's own venv outranks the canonical
        checkout's."""
        self._pin_repos_conf()
        # `-c` probes exit 0 without needing a real pytest — this test
        # only checks candidate order, it never runs the gate.
        shim = '#!/bin/sh\n[ "$1" = "-c" ] && exit 0\nexec python3 "$@"\n'
        wt_py = self._make_venv(self.wt, shim)
        self._make_venv(self.main, shim)
        py = dr.gate_python(self.wt, "chaba",
                            dr.test_gate_config("chaba"))
        self.assertEqual(py, str(wt_py))

    def test_resolve_gate_cmd_pin_and_nonpython(self):
        """An explicit REPO_TESTS "python" pin wins without probing;
        non-python commands pass through untouched."""
        pin = self.tmp / "pinbin" / "python"
        pin.parent.mkdir()
        pin.write_text("#!/bin/sh\nexec python3 \"$@\"\n")
        pin.chmod(0o755)
        cfg = {"python": str(pin)}
        cmd, py = dr._resolve_gate_cmd(
            "python3 -m pytest tests -k x -q", self.wt, "chaba", cfg)
        self.assertEqual(py, str(pin))
        self.assertEqual(cmd, f"{pin} -m pytest tests -k x -q")
        cmd, py = dr._resolve_gate_cmd("make test", self.wt, "chaba", cfg)
        self.assertEqual((cmd, py), ("make test", ""))

    @unittest.skipUnless(
        subprocess.run(["python3", "-c", "import pytest"],
                       capture_output=True).returncode == 0,
        "pytest not installed")
    def test_gate_real_pytest_names_failure(self):
        commit(self.wt, "tests/test_gate_target.py",
               "def test_broke():\n    assert False\n", "red test")
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"], res)
        self.assertTrue(res.get("test_failures"), res)
        self.assertTrue(any("test_broke" in f
                            for f in res["test_failures"]),
                        res["test_failures"])


class MergeRetryTest(unittest.TestCase):
    """kanban-dispatch merge_pending_one: a close_out test-gate failure
    rides the same rails as conflicts — verified=False plus an informed
    auto-retry requeue (action.last_failure carries the test names)."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "kanban_dispatch",
            REPO / "scripts" / "board" / "kanban-dispatch.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def _merge_card(self, action_yaml: str,
                    res: dict) -> dict:
        mod = self.mod
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "gate-card.yml"
        path.write_text(
            "id: gate-card\ncolumn: review\n" + action_yaml)
        with mock.patch.object(dr, "close_out", return_value=res), \
                mock.patch.object(mod, "ops_event"), \
                mock.patch.object(mod, "session_end_notes",
                                  return_value=[]):
            mod.merge_pending_one(path)
        return yaml.safe_load(path.read_text())

    RES = {"merged": False,
           "tests": {"ran": True, "ok": False,
                     "command": "pytest tests",
                     "failed": ["tests/test_x.py::test_broke"]},
           "test_failures": ["tests/test_x.py::test_broke"]}

    def test_testgate_failure_requeues_with_last_failure(self):
        # attempts=1 is the post-claim state (mark_start bumped it); a
        # first failure at the default max_attempts=2 must requeue —
        # the old `att = attempts + 1` double-count made 2 < 2 fail and
        # auto-retry never fired (kanban-autoretry-off-by-one).
        card = self._merge_card(
            "action: {type: dispatch, status: done, task_id: t-gate, "
            "attempts: 1}\n", self.RES)
        a = card["action"]
        self.assertEqual(a["status"], "queued")
        self.assertIs(a["verified"], False)
        # attempts is claim-side accounting — merge must not bump it
        self.assertEqual(a["attempts"], 1)
        self.assertIn("test_broke", a["last_failure"])
        self.assertNotIn("task_id", a)
        self.assertTrue(any("attempt 2/2" in (c.get("text") or "")
                            for c in card.get("comms") or []),
                        card.get("comms"))

    def test_retry_budget_exhausted_does_not_requeue(self):
        # attempts == max_attempts (default 2): the budget is spent —
        # no third dispatch, card stays unverified for a human.
        card = self._merge_card(
            "action: {type: dispatch, status: done, task_id: t-gate, "
            "attempts: 2}\n", self.RES)
        a = card["action"]
        self.assertNotEqual(a["status"], "queued")
        self.assertIs(a["verified"], False)
        self.assertEqual(a["attempts"], 2)

    def test_max_attempts_override_extends_budget(self):
        # max_attempts: 3 on the card beats the default of 2 — a second
        # failure still leaves one retry slot.
        card = self._merge_card(
            "action: {type: dispatch, status: done, task_id: t-gate, "
            "attempts: 2, max_attempts: 3}\n", self.RES)
        a = card["action"]
        self.assertEqual(a["status"], "queued")
        self.assertEqual(a["attempts"], 2)
        self.assertTrue(any("attempt 3/3" in (c.get("text") or "")
                            for c in card.get("comms") or []),
                        card.get("comms"))

    def test_autoretry_off_does_not_requeue(self):
        os.environ["KANBAN_AUTORETRY"] = "0"
        self.addCleanup(os.environ.pop, "KANBAN_AUTORETRY")
        card = self._merge_card(
            "action: {type: dispatch, status: done, task_id: t-gate, "
            "attempts: 1}\n", self.RES)
        a = card["action"]
        self.assertNotEqual(a["status"], "queued")
        self.assertIs(a["verified"], False)

    def test_clean_merge_stamps_verified(self):
        mod = self.mod
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "ok-card.yml"
        path.write_text(
            "id: ok-card\ncolumn: review\n"
            "action: {type: dispatch, status: done, task_id: t-ok}\n")
        res = {"merged": True, "noop": True,
               "note": "dispatch/t-ok already in origin/master"}
        with mock.patch.object(dr, "close_out", return_value=res), \
                mock.patch.object(mod, "session_end_notes",
                                  return_value=[]):
            out = mod.merge_pending_one(path)
        self.assertEqual(out, "noop")
        card = yaml.safe_load(path.read_text())
        self.assertIs(card["action"]["verified"], True)


if __name__ == "__main__":
    unittest.main()
