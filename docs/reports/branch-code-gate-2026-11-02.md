# Branch Code Gate Summary

| Field              | Value                                                                 |
|-------------------|----------------------------------------------------------------------|
| Status            | disabled                                                            |
| Task Classes      | branch_code                                                         |
| Required Stage    | S5                                                                   |
| Model Tier        | strong (default: litellm/claude-fable-5.1)                          |
| Enabled Tools     | read, grep, glob, list, todoread, todowrite, bash, write, edit, patch |
| Verifier Type     | independent_devin                                                   |
| Rollback Kind     | worktree-drop                                                       |
| S5 Entry Req      | - Implement task, run tests, produce JSON artifact
|                   | - No pushes/merges, tests must execute
|                   | - Artifact must include tests_run/test_passed flags                 |

