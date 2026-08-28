---
category: operations
---

# Phase 1 Feedback Loop Features

### Automated Issue Creation
The overnight assessment system can automatically create improvements in `ssot.improvements.yml` when critical issues are discovered:

**Auto-Creation Triggers:**
- Service health failures (HTTP errors, timeouts)
- GPU temperature critical (>85°C) or elevated (>75°C)
- GPU VRAM usage critical (>90%)
- Disk usage critical (>80%) or elevated (>70%)

**Implementation (August 3, 2026):**
- Added `autoCreateImprovement()` function to create improvement objects
- Added `improvementExists()` to prevent duplicate improvements
- Added `formatImprovementForSSOT()` to format improvements as YAML
- Added `appendToSSOTSection()` to append improvements to appropriate priority sections
- Added `syncAutoCreatedImprovements()` to group and sync improvements by priority
- Auto-created improvements include: label, text, status, priority, effort, category, discovered date, assessment reference, auto-generated flag, related files, and tags
- Improvements are grouped by priority (High/Medium/Low) and appended to corresponding SSOT sections

**Auto-Created Improvements Include:**
- Automatic label and description
- Priority level based on severity
- Category classification (gpu, service-health, storage, etc.)
- Related files reference
- Assessment report reference
- Git commit information (if available)
- Auto-generated tag for identification

**Usage:**
Improvements are automatically created during assessment runs if:
1. The issue doesn't already exist in SSOT (checked by label)
2. The issue meets severity thresholds
3. Auto-creation is enabled (default: enabled)

### Automated Verification Loop
Verify that improvements actually resolve the issues they address:

**Verification Script:** `scripts/verify-improvement.mjs`

**Usage:**
```bash
node scripts/verify-improvement.mjs <improvement-label>
```

**Verification by Category:**
- **GPU:** Checks temperature, VRAM usage, GPU processes
- **Yomi:** Verifies API health, summarization status, rate limiter queues
- **Service Health:** Tests specific service endpoints
- **Storage:** Validates disk usage thresholds
- **Configuration:** Checks for IP addresses in config files
- **Performance:** Collects memory and load metrics
- **General:** Manual verification recommended

**Verification Results:**
- Updates SSOT with verification method, result, details, and date
- Includes git commit information if available
- Returns exit code 0 for passed, 1 for failed
- Provides detailed feedback on what was checked

**Example:**
```bash
node scripts/verify-improvement.mjs "GPU Temperature Elevated"
# Output: PASSED/FAILED with specific metrics and thresholds
```

### Git Integration
Link improvements to git commits for traceability:

**Git Linking Script:** `scripts/link-improvement-to-git.mjs`

**Usage:**
```bash
node scripts/link-improvement-to-git.mjs <improvement-label> [commit-message]
```

**Git Information Captured:**
- Full commit hash
- Short commit hash (8 characters)
- Branch name
- Commit message (optional)

**Auto-Integration:**
- Overnight assessment automatically includes git info in auto-created improvements
- Verification script adds git info when verification passes
- Manual linking available for any improvement

**Example:**
```bash
node scripts/link-improvement-to-git.mjs "Docker Compose Configuration Fix" "Remove obsolete version attribute"
```

### Feedback Loop Workflow

**Complete Improvement Lifecycle:**

1. **Discovery:** Overnight assessment discovers issue
2. **Auto-Creation:** Issue automatically added to `ssot.improvements.yml`
3. **Planning:** Issue prioritized and assigned (manual)
4. **Implementation:** Work completed with git commits
5. **Git Linking:** Link improvement to resolving commit
6. **Verification:** Run verification script to confirm fix
7. **Status Update:** Mark as completed in SSOT
8. **Monitoring:** Future assessments track for regression

**SSOT Structure for Completed Improvements:**
```yaml
- label: Docker Compose Configuration Fix
  status: completed
  completed: 2026-08-04
  git_commit: abc123def456
  git_branch: fix/docker-compose-version
  git_short_commit: abc12345
  git_commit_message: Remove obsolete version attribute
  verification_method: automated
  verification_result: passed
  verification_details: No version attribute found in docker-compose.yml
  verification_date: 2026-08-04T08:15:00Z
```

## Feedback Loop Benefits

**Automation:**
- Reduces manual data entry
- Ensures no issues are lost
- Provides consistent issue tracking

**Traceability:**
- Links issues to code changes
- Tracks verification history
- Maintains audit trail

**Quality Assurance:**
- Automated verification prevents false positives
- Ensures fixes actually resolve issues
- Catches regressions early

**Continuous Improvement:**
- Data-driven prioritization
- Historical impact analysis
- Process optimization over time
