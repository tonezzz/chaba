import importlib.util
import unittest
from pathlib import Path


BRIDGE_PATH = (
    Path(__file__).parents[2]
    / "scripts/colab/packs/cline-kanban-nest-bridge/bridge.py"
)
SPEC = importlib.util.spec_from_file_location("cline_kanban_nest_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class ClineKanbanNestBridgeTests(unittest.TestCase):
    def task_spec(self, **overrides):
        spec = {
            "job_key": "cline-nest-smoke-20261027",
            "target_host": "con01",
            "execute": True,
            "title": "Nest adapter smoke test",
            "project_path": "/workspace",
            "base_ref": "main",
            "agent_id": "cline",
            "provider_id": "ollama",
            "model_id": "qwen3:4b",
            "timeout_s": 600,
            "expected_file": "nest-cline-smoke.txt",
            "expected_text": "Nest adapter smoke passed through Cline + Ollama.",
            "prompt": "Create the expected smoke file.",
        }
        spec.update(overrides)
        return spec

    def test_rejects_non_disposable_workspace_and_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "disposable /workspace"):
            bridge.validate_spec(self.task_spec(project_path="/home/tony"))
        with self.assertRaisesRegex(ValueError, "relative path"):
            bridge.validate_spec(self.task_spec(expected_file="../README.md"))

    def test_rejects_agent_start_without_explicit_execute_flag(self):
        with self.assertRaisesRegex(ValueError, "execute must be true"):
            bridge.validate_spec(self.task_spec(execute=False))

    def test_restricts_task_size_and_base_ref(self):
        with self.assertRaisesRegex(ValueError, "base_ref must be"):
            bridge.validate_spec(self.task_spec(base_ref="origin/main"))
        with self.assertRaisesRegex(ValueError, "prompt must be at most"):
            bridge.validate_spec(self.task_spec(prompt="x" * 4001))

    def test_task_identity_marker_is_idempotency_key(self):
        spec = bridge.validate_spec(self.task_spec())
        marker = bridge.task_marker(spec)
        task = {"id": "task-123", "prompt": f"{spec['prompt']}\n{marker}"}
        self.assertEqual(bridge.find_existing_task([task], marker), task)

    def test_create_command_pins_local_provider_and_disables_auto_review(self):
        args = bridge.create_args(bridge.validate_spec(self.task_spec()))
        self.assertIn("--agent-id", args)
        self.assertIn("cline", args)
        self.assertIn("--cline-provider", args)
        self.assertIn("ollama", args)
        self.assertIn("--cline-model", args)
        self.assertIn("qwen3:4b", args)
        auto_review = args.index("--auto-review-enabled")
        self.assertEqual(args[auto_review + 1], "false")
        self.assertNotIn("--auto-review-mode", args)

    def test_selects_only_task_worktree(self):
        before = [{"path": "/workspace", "branch": "refs/heads/main"}]
        after = before + [{
            "path": "/root/.cline/worktrees/task-123",
            "branch": "refs/heads/kanban/task-123",
        }]
        selected = bridge.choose_task_worktree(before, after, "task-123")
        self.assertEqual(selected["path"], "/root/.cline/worktrees/task-123")

    def test_parses_git_worktree_porcelain(self):
        output = (
            "worktree /workspace\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /root/.cline/worktrees/task-1\nHEAD def\n"
            "branch refs/heads/kanban/task-1\n"
        )
        self.assertEqual(bridge.parse_worktrees(output), [
            {"path": "/workspace", "HEAD": "abc", "branch": "refs/heads/main"},
            {
                "path": "/root/.cline/worktrees/task-1",
                "HEAD": "def",
                "branch": "refs/heads/kanban/task-1",
            },
        ])


if __name__ == "__main__":
    unittest.main()
