# Review proposal: OpenCode → JEV → Nest → Cline

**Status:** Human-authored review draft for DEV-0975. This is not approval to
dispatch work or run Cline/Nest.

## Recommendation

Keep OpenCode in a **proposal-only** role. Let it clarify the request and
compare options, but do not let its output set task class, target host,
allowed paths, MCP access, verifier, human gate, rollback, or execution
authority. JEV must classify the original request; a deterministic compiler
must combine that route with an immutable Chaba card snapshot. Only then,
after human review, may a narrow Nest job be submitted.

The recorded route choice on DEV-0975 is **repair the Cline/Nest artifact
contract first**. PR #62 is open and unmerged; GitHub reports the `syntax`
check passing and the `validate` check failing at **“Fail on warnings absent
from baseline.”** SSOT syntax/cross-reference and bridge/proxy test steps
passed. The exact new warning was not available through the read surface;
do not change the warning baseline to bypass it. Do not deploy or launch a
live canary until the validation failure is resolved and the artifact path
is independently re-tested.

## Proposed lifecycle

1. **Capture the request on Chaba Kanban.** The card ID and immutable version
   are the shared anchor. The board remains authoritative for approval,
   status, dispatch, and closeout.
2. **OpenCode drafts content only.** It asks for missing goals, constraints,
   and success criteria, then returns a recommendation, viewpoints, options,
   assumptions, and questions. Existing-work matches remain
   `not_evaluated` unless repository/SSOT evidence was actually supplied.
3. **JEV independently classifies and gates.** JEV sees the original request,
   not a model-selected lane. JEV is a decision plane; it does not write the
   work product or claim artifact verification.
4. **A deterministic compiler builds the review envelope.** It binds the
   proposal to the card ID/version, JEV route, task class, risk, target,
   allowed paths, MCP allowlist, artifact, verifier, escalation, rollback,
   and human gate. It rejects model-emitted policy fields or any attempt to
   widen the card's scope.
5. **Nest owns job lifecycle.** After approval, a narrow MCP door submits and
   reports the job. Nest owns claim, lease/heartbeat, bounded retry,
   `result_ref`, and terminal state.
6. **Cline is an isolated executor.** It receives a versioned snapshot and a
   disposable workspace. It cannot write Chaba board state, dispatch more
   work, auto-commit, or auto-PR.
7. **An independent verifier gates completion.** It checks the declared
   artifact and durable result reference. A Cline “complete” message, exit
   code, or Nest `done` state alone is insufficient. Only verified evidence
   is reported back to the Chaba card through board-api.

## Viewpoints

| View | Value | Cost / tradeoff |
|---|---|---|
| User/workflow | One Chaba card keeps Tony and every agent aligned on the same request, decision, and status. | Versioned snapshots and a review step add friction, but prevent stale or duplicate boards. |
| Technical | OpenCode drafts; JEV routes; the compiler owns policy; Nest orchestrates; Cline executes; a separate verifier checks. | This requires a small compiler and tested submission/result contracts instead of one model-to-tool shortcut. |
| Operations/safety | Model output cannot widen permissions; Cline stays isolated; hardware, purchase, credential, production, and write actions retain human gates. | The verifier and worker must agree on artifact paths, `result_ref`, and terminal transitions. |
| Cost/effort | Proposal drafting can use a local model, and JEV routing is deterministic for known cases. | Local Qwen was slow (about 2.5–6 minutes per response) and the proposal-only output needed prompt iteration; budget time for verification and bounded retries. |

“Many viewpoints” are a structured checklist from one proposal model, not
independent-agent consensus. Each perspective needs evidence, assumptions, and
unknowns separated.

## Evaluation evidence and limits

- JEV's deterministic classifier matched the three explicit synthetic cases
  (read-only report → `free_lane`, docs-only → `free_lane`, hardware →
  `manual`). This is a smoke test, not a broad classifier-quality claim.
- The v1 executable-envelope attempt passed **0/3**. One model output widened
  `allowed_paths` to `/`; the held-out verifier rejected it. Never pass
  model-proposed permissions to Nest/Cline.
- Proposal-only v2 passed **3/3** after a fixed schema and targeted missing-
  information prompts. It emitted no policy fields and made no tool/MCP
  calls. A deterministic compiler joined those proposals with synthetic
  card-policy snapshots and JEV routes; all compiled packages retained
  `execution_authorized: false` and remain review/clarification material.
- A standard scratch-context OpenCode runner passed a hardware proposal in
  356.9 seconds. This validates proposal output only, not a Nest job or Cline
  execution.
- A separate model-generated proposal for the real workflow idea failed the
  content rubric: it omitted essential role separation and gave generic
  viewpoints. The proposal above is Devin's synthesis of verified evidence,
  not an accepted OpenCode output.
- No Cline task, Nest job, dispatch, merge, deployment, or paid-model call
  was made in this evaluation.

## Next gate

1. Review this proposal and decide whether the private Education-draft
   request should be reopened; it is no longer in DEV-0975's `requests[]`.
2. Resolve PR #62's failing `validate` check; keep it unmerged and undeployed
   until the warning-baseline failure is understood and the check passes.
3. Bind the compiler to a real, immutable Chaba card ID/version and verify
   it cannot expand policy.
4. Only after that, run one supervised, no-merge Cline/Nest canary in a
   disposable workspace. Require the declared artifact, `result_ref`,
   terminal-state reconciliation, and independent verification before
   considering a five-job read-only pilot.
