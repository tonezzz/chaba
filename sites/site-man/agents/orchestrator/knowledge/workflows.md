# Multi-agent workflows

- **Deploy readiness**: Orchestrator -> (Navigator plan) -> (Researcher add context) -> (Critic sign-off)
- **Bug investigation**: Orchestrator -> (Researcher gather logs/docs) -> (Navigator suggest fixes)
- **Ops escalation**: Orchestrator -> (Navigator run scripts) -> (Critic verify) -> (Orchestrator summarize outcome)

When delegating, explicitly reference the agent IDs so downstream automation can route the instructions.
