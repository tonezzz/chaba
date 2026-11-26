"""Tests for stacks/idc02/jack-ide/lane/jack-task.py — the operator-side
promotion lane for the shared Jack OpenCode workspace (card
jack-shared-workspace-repo-promotion).

Fixtures build a real local git topology (bare origin + clone) inside a
tmpdir; the lane's GitHub-token path is exercised only through the pure
helpers (auth_args / _github_repo) — no network, no credentials."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "stacks" / "idc02" / "jack-ide" / "lane" / "jack-task.py"


def _load():
    spec = importlib.util.spec_from_file_location("jack_task", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jack_task"] = mod
    spec.loader.exec_module(mod)
    return mod


GIT_ENV = ["-c", "user.name=lane-test", "-c", "user.email=lane@test"]


def git(cwd, *args, check=True):
    proc = subprocess.run(["git", *GIT_ENV, "-C", str(cwd), *args],
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc


class LaneTest(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="jack-task-test-"))
        self.ws = self.tmp / "ws"
        self.cfg = self.tmp / "repos.json"
        self.gitenv = self.tmp / "jack-git.env"
        self._env = {}
        for k, v in {
            "JACK_IDE_WORKSPACE": str(self.ws),
            "JACK_IDE_REPOS_CONFIG": str(self.cfg),
            "JACK_IDE_GIT_ENV": str(self.gitenv),
        }.items():
            self._env[k] = os.environ.get(k)
            os.environ[k] = v
        # bare "origin" + one commit on main
        self.origin = self.tmp / "origin.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(self.origin)], check=True)
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "--quiet", str(self.origin), str(seed)], check=True)
        git(seed, "checkout", "-q", "-b", "main")
        (seed / "README.md").write_text("toy repo\n")
        git(seed, "add", "README.md")
        git(seed, "commit", "-qm", "init")
        git(seed, "push", "-q", "origin", "main")
        # allowlist + import
        self.cfg.write_text(json.dumps({"repos": [
            {"name": "toy", "url": str(self.origin), "default_branch": "main"}]}))
        assert self.mod.main(["import", "toy"]) == 0

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def wt(self, slug="fix1"):
        return self.ws / "worktrees" / f"toy--{slug}"

    def new_task(self, slug="fix1", extra=()):
        return self.mod.main(["new", "toy", slug, *extra])

    def commit_in_wt(self, slug, path, content):
        wt = self.wt(slug)
        (wt / path).parent.mkdir(parents=True, exist_ok=True)
        (wt / path).write_text(content)
        git(wt, "add", path)
        git(wt, "commit", "-qm", f"add {path}")

    # -- init / layout -----------------------------------------------------

    def test_init_creates_layout(self):
        rc = self.mod.main(["init"])
        self.assertEqual(rc, 0)
        for d in ("repos", "worktrees", "shared", "incoming", "outputs"):
            self.assertTrue((self.ws / d).is_dir(), d)
        self.assertTrue((self.ws / "AGENTS.md").exists())
        self.assertTrue((self.ws.parent / "tony-workspace").is_dir())

    # -- import / new -------------------------------------------------------

    def test_import_rejects_unlisted(self):
        with self.assertRaises(SystemExit):
            self.mod.main(["import", "evil"])

    def test_import_rejects_bad_name(self):
        with self.assertRaises(SystemExit):
            self.mod.main(["import", "../escape"])

    def test_new_creates_worktree_and_manifest(self):
        self.assertEqual(self.new_task(), 0)
        self.assertTrue((self.wt() / ".git").exists())
        man = json.loads((self.ws / "outputs/lane/tasks/fix1.json").read_text())
        self.assertEqual(man["branch"], "jack/fix1")
        self.assertEqual(man["stage"], "task")
        self.assertEqual(git(self.wt(), "symbolic-ref", "--short", "HEAD").stdout.strip(),
                         "jack/fix1")

    def test_new_rejects_bad_slug(self):
        self.new_task()
        with self.assertRaises(SystemExit):
            self.new_task("Fix_One")
        with self.assertRaises(SystemExit):
            self.new_task("fix1")  # duplicate

    # -- verify gates --------------------------------------------------------

    def test_verify_pass_and_push(self):
        self.new_task()
        self.commit_in_wt("fix1", "src/app.py", "print('hi')\n")
        self.assertEqual(self.mod.main(["verify", "fix1"]), 0)
        man = json.loads((self.ws / "outputs/lane/tasks/fix1.json").read_text())
        self.assertEqual(man["stage"], "verified")
        self.assertTrue(man["last_verdict"]["pass"])
        # push to the local bare origin (non-github -> no token needed)
        self.assertEqual(self.mod.main(["push", "fix1"]), 0)
        remote = git(self.origin, "rev-parse", "refs/heads/jack/fix1").stdout.strip()
        head = git(self.wt(), "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(remote, head)
        man = json.loads((self.ws / "outputs/lane/tasks/fix1.json").read_text())
        self.assertEqual(man["stage"], "pushed")
        self.assertEqual(man["remote_sha"], head)

    def test_push_requires_verify(self):
        self.new_task()
        self.commit_in_wt("fix1", "a.txt", "x\n")
        with self.assertRaises(SystemExit):
            self.mod.main(["push", "fix1"])

    def test_verify_fails_on_secret(self):
        self.new_task()
        self.commit_in_wt("fix1", "cfg.py",
                          'TOKEN = "ghp_' + "a" * 30 + '"\n')
        self.assertEqual(self.mod.main(["verify", "fix1"]), 1)
        v = json.loads((self.ws / "outputs/lane/tasks/fix1/verdict.json").read_text())
        self.assertFalse(v["pass"])
        self.assertFalse(v["gates"]["secret_scan"]["pass"])

    def test_verify_fails_on_env_file(self):
        self.new_task()
        self.commit_in_wt("fix1", ".env", "SECRET=1\n")
        self.assertEqual(self.mod.main(["verify", "fix1"]), 1)
        v = json.loads((self.ws / "outputs/lane/tasks/fix1/verdict.json").read_text())
        self.assertFalse(v["gates"]["forbidden_paths"]["pass"])

    def test_verify_allows_env_example(self):
        self.new_task()
        self.commit_in_wt("fix1", ".env.example", "SECRET=changeme\n")
        self.assertEqual(self.mod.main(["verify", "fix1"]), 0)

    def test_verify_fails_on_dirty_tree(self):
        self.new_task()
        self.commit_in_wt("fix1", "a.txt", "x\n")
        wt = self.wt()
        (wt / "dirty.txt").write_text("uncommitted\n")
        self.assertEqual(self.mod.main(["verify", "fix1"]), 1)
        v = json.loads((self.ws / "outputs/lane/tasks/fix1/verdict.json").read_text())
        self.assertFalse(v["gates"]["clean_tree"]["pass"])

    def test_verify_runs_tests_and_scrubs_token_env(self):
        os.environ["JACK_GIT_TOKEN"] = "supersecretvalue"
        self.new_task("t2", ("--test", "test -z \"$JACK_GIT_TOKEN\""))
        self.commit_in_wt("t2", "a.txt", "x\n")
        self.assertEqual(self.mod.main(["verify", "t2"]), 0)
        v = json.loads((self.ws / "outputs/lane/tasks/t2/verdict.json").read_text())
        self.assertEqual(v["gates"]["tests"]["status"], "pass")
        self.assertNotIn("supersecretvalue",
                         (self.ws / "outputs/lane/tasks/t2/test-output.log").read_text())

    def test_verify_fails_on_test_failure(self):
        self.new_task("t3", ("--test", "exit 3"))
        self.commit_in_wt("t3", "a.txt", "x\n")
        self.assertEqual(self.mod.main(["verify", "t3"]), 1)
        v = json.loads((self.ws / "outputs/lane/tasks/t3/verdict.json").read_text())
        self.assertEqual(v["gates"]["tests"]["status"], "fail")

    # -- credential scoping (pure helpers, no network) -----------------------

    def test_auth_args_only_for_github_https_with_token(self):
        self.assertEqual(self.mod.auth_args("/tmp/origin.git"), [])
        self.assertEqual(self.mod.auth_args("git@github.com:tonezzz/x.git"), [])
        self.assertEqual(self.mod.auth_args("https://github.com/tonezzz/x.git"), [])
        self.gitenv.write_text("JACK_GIT_TOKEN=github_pat_abc123\n")
        args = self.mod.auth_args("https://github.com/tonezzz/x.git")
        self.assertEqual(len(args), 2)
        self.assertIn("http.extraHeader", args[1])
        self.assertIn("github_pat_abc123", args[1])
        # never injected for non-github hosts even with a token present
        self.assertEqual(self.mod.auth_args("https://gitlab.com/x/y.git"), [])

    def test_github_repo_parse(self):
        self.assertEqual(self.mod._github_repo("https://github.com/t/r.git"),
                         ("t", "r"))
        self.assertEqual(self.mod._github_repo("git@github.com:tonezzz/chaba.git"),
                         ("tonezzz", "chaba"))
        self.assertIsNone(self.mod._github_repo("/tmp/origin.git"))

    def test_pr_refuses_non_github_origin(self):
        self.new_task()
        self.commit_in_wt("fix1", "a.txt", "x\n")
        self.assertEqual(self.mod.main(["verify", "fix1"]), 0)
        self.assertEqual(self.mod.main(["push", "fix1"]), 0)
        # origin is a local path -> pr must refuse (not github)
        with self.assertRaises(SystemExit):
            self.mod.main(["pr", "fix1"])


if __name__ == "__main__":
    unittest.main()
