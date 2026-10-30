```markdown
---
id: proposal-edu-no-th-marker
title: PILOT: Cline proposal analysis on no_th snapshot v1
---

# 1. Summary + Restated Request
The task is to analyze the versioned, read-only Chaba kanban card snapshot `education-lesson-no-th-marker-readback` (stable card id: `education-lesson-no-th-marker-readback`, marker `SNAP-edu-no-th-v1:d4cc6b50`). The request is to investigate why a lesson written through the unified `/lesson` door with `no_th=true` does not expose `meta.no_th=true` on a subsequent `/lesson op=get`. The lesson content is English-only, and the writer code intends to persist `no_th=true`. The task should not involve writing directly to WordPress, generating Thai translation, or changing the existing lesson post unless explicitly requested.

# 2. Matches/Duplicates
- **Real Matches**: None identified.
- **Adjacent**: Possible duplicate/adjacent card `audit-miss-education-lesson-write-timeout` (Education lesson upsert failed on WP GET timeout; symptom is retry-after-healthy, not a lost meta field).
- **Unrelated**: Other cards not directly related to this issue.

# 3. Viewpoints
## Stakeholder/User
- **Stakeholder**: The user creating the lesson expects the `no_th=true` metadata to persist when the lesson is read back.
- **User Experience**: The user experience should not be impacted by the issue, but the metadata should be correctly recorded and retrieved.

## Architecture
- **Architecture**: The architecture relies on the board-api to write and read lessons. The `no_th` metadata should be correctly serialized and deserialized.
- **Consistency**: The system should ensure that the `no_th` metadata is consistently recorded and retrieved.

## Operations
- **Operations**: The operations team needs to ensure that the board-api is functioning correctly and that the metadata is being properly recorded and retrieved.
- **Reproducibility**: The operations team should be able to reproduce the issue using a synthetic lesson and inspect the board-api serialization.

## Security/Privacy
- **Security**: The system should ensure that the `no_th` metadata is handled securely and that there are no privacy concerns.
- **Privacy**: The system should not expose any sensitive information and should handle metadata in a secure manner.

## Cost
- **Cost**: The cost of this task is minimal as it involves analysis and potential minor adjustments to the board-api.
- **Efficiency**: The task should be completed efficiently without unnecessary overhead.

## Delivery
- **Delivery**: The task should be completed within a reasonable timeframe and should not impact other ongoing projects.

# 4. Evidence vs Assumptions
- **Evidence**: [E] The lesson was created through `lesson-add.py` with `--no-th`.
- **Assumptions**: [A] The board-api is the only write door for lessons.
- **Evidence**: [E] The lesson content is English-only.
- **Assumptions**: [A] The `no_th` metadata should be persisted and retrievable through the board-api.
- **Evidence**: [E] The `no_th` metadata is intended to be persisted for Thai-free lessons.
- **Assumptions**: [A] The issue is not related to a timeout or other transient issue.

# 5. Options with Tradeoffs + One Recommendation
## Option 1: Inspect Board-api Serialization
- **Tradeoffs**: Requires inspection of the board-api serialization process. May involve minor code adjustments.
- **Recommendation**: Inspect the board-api serialization and ensure that the `no_th` metadata is being correctly serialized.

## Option 2: Adjust WP REST Meta Registration
- **Tradeoffs**: Requires adjusting the WP REST meta registration process. May involve changes to the service deployment process.
- **Recommendation**: Adjust the WP REST meta registration process to ensure that the `no_th` metadata is being correctly registered.

## Recommendation: Inspect Board-api Serialization
- **Reason**: Inspecting the board-api serialization process is a more direct approach to resolving the issue and is less likely to introduce additional complexity.

# 6. Acceptance Criteria + Open Questions
- **Acceptance Criteria**:
  - The `no_th` metadata is correctly serialized and deserialized by the board-api.
  - The `no_th` metadata is correctly retrieved when the lesson is read back.
  - The issue is resolved without impacting other systems or processes.
- **Open Questions**:
  - Are there any known issues with the board-api serialization process?
  - Should additional regression tests be added to ensure the issue is fully resolved?

# 7. Link-back
- **Card ID**: `education-lesson-no-th-marker-readback`
- **Snapshot V1**: `SNAP-edu-no-th-v1:d4cc6b50`

---
```