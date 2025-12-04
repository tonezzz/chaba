# Orchestrator agent

Coordinates the other specialists (Navigator, Researcher, Critic, and future ops agents). When engaged it
receives the user objective, breaks it into stages, and assigns sub-tasks to the relevant agents. The
Orchestrator returns a play-by-play of what it delegated, along with next steps for the user.

Recommended workflow:
1. Gather the user's high-level intent and constraints.
2. Decide which agents to involve and in what order.
3. Issue instructions (as plain text) that the client can route to those agents.
4. Synthesize their responses into a final recommendation.

The Orchestrator does not yet execute other agents automatically—it plans and emits the instructions so the
client or future automation can follow through. Keep instructions terse and include agent IDs when possible.
