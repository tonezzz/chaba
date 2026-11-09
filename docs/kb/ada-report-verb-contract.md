# Ada Report-Verb Read Path Contract

This document outlines how Ada interacts with the fleet jobs reporting mechanism.

## Overview
To answer queries such as "how are jobs", Ada uses a deterministic read path that accesses the pre-rendered artifact from the `fleet-jobs-report` aggregator.

## Read Path Constraints
1. **Sub-second Read**: Ada reads the rendered artifact directly from `reports/fleet-jobs-*.md` or its CMS representation.
2. **Never Live-Compute**: Ada does **not** perform live computations or trigger aggregator scripts on a voice turn. The `fleet-jobs-report.py` aggregator is run independently on a 4h schedule by the system timer.

## Implementation Details
The `ada-voice` tool wiring for this report-verb contract is tracked in a follow-up card and will be implemented in the separate `ada-voice` repository.
