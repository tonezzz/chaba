# Task: branch-code fixture — DISABLED profile

This fixture exists so the branch-code profile's config, envelopes and
rendered agent validate end-to-end. The profile is `status: disabled`
and `unattended: false`; every admission path denies it in this card.

When the profile is later enabled, the task shape is: implement
`{{TASK}}` inside an isolated worktree, run the tests, and emit the
JSON contract (`task, branch, worktree, files_changed, tests_run,
tests_passed, review_ref, artifact_complete`).
