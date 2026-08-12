# Overnight System Assessment
## What it is

Automated overnight system assessment that runs comprehensive health checks and performance analysis of the Chaba infrastructure. Scheduled to run daily at 2:00 AM via systemd timer, generating detailed reports for system administrators.

## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation.


## Overview

Automated overnight system assessment that runs comprehensive health checks and performance analysis of the Chaba infrastructure. Scheduled to run daily at 2:00 AM via systemd timer, generating detailed reports for system administrators.

## Key files

| File | Purpose |
|------|---------|
| `chaba/.agents/skills/overnight-assessment/SKILL.md` | Assessment skill definition and scope |
| `chaba/scripts/overnight-assessment.mjs` | Main assessment script (Node.js) |
| `/etc/systemd/system/chaba-assessment.timer` | Systemd timer for scheduling |
| `/etc/systemd/system/chaba-assessment.service` | Systemd service definition |
| `chaba/reports/overnight-assessment-YYYY-MM-DD.md` | Generated assessment reports |
| `chaba/reports/archive/` | Reports older than 30 days (auto-archived) |

## Assessment Areas

### 1. Health Check Integration
- Calls existing health check API: `http://tony-omen.local:8080/api/health`
- Checks all service categories: web, api, datastore, gpu, queue, optional
- Tests individual service endpoints with response time measurement
- Identifies failed services and suggests recovery actions

### 2. GPU & Queue Analysis
- GPU status: model, VRAM usage, utilization, temperature
- GPU queue status: pending, running, completed, failed jobs
- Active GPU processes with memory usage
- Temperature and VRAM threshold monitoring

### 3. Yomi System Health
- Yomi API health status
- Rate limiter statistics (running/queued jobs)
- Circuit breaker states and failure patterns
- Summarization service status and error counts

### 4. Database & Cache Performance
- Docker container status checks
- Postgres, Redis, Weaviate service availability
- Connection pool performance monitoring

### 5. System Resources
- Disk usage analysis with threshold alerts
- Memory usage and swap utilization
- System load average monitoring

### 6. Configuration Validation
- SSOT YAML file existence checks
- Hostname enforcement validation (.local vs IP addresses)
- Configuration consistency verification

### 7. Improvements Tracking
- Checks for `ssot.improvements.yml` file existence
- Monitors pending, planned, and completed improvement counts
- Alerts if pending improvements exceed threshold (>5)
- Links improvement tracking to assessment reports

## Issue Prioritization

### Critical Issues (🚨)
- GPU temperature > 85°C
- Core service failures (Status API, Yomi API, etc.)
- Critical endpoint unavailability

### High Priority Issues (⚠️)
- GPU temperature > 75°C
- GPU VRAM usage > 90%
- Docker container failures
- High error counts in services

### Medium Priority Issues (📋)
- GPU queue failures
- Elevated resource usage
- Configuration inconsistencies

### Low Priority Issues (💡)
- IP addresses in config files (should use .local)
- Documentation updates needed
- Minor optimization opportunities

## Report Structure

Each overnight assessment generates a markdown report with:

1. **Executive Summary**
   - Overall health score (0-100)
   - Assessment timestamp
   - Total issues found by priority
   - System status overview

2. **Health Check Results**
   - Service status table with response times
   - Docker container status
   - Individual service health checks

3. **GPU & Queue Status**
   - GPU hardware metrics
   - VRAM usage and utilization
   - Temperature monitoring
   - Active GPU processes
   - Queue statistics

4. **Yomi System Health**
   - Rate limiter performance
   - Circuit breaker states
   - Summarization service status

5. **System Resources**
   - Disk usage analysis
   - Memory and swap usage
   - System load averages

6. **Configuration Validation**
   - SSOT file checks
   - Hostname compliance
   - Configuration drift detection

7. **Improvement Recommendations**
   - Prioritized action items
   - Ongoing maintenance tasks
   - Performance optimization suggestions

## Scheduling

**Timer Configuration:**
- **Schedule:** Daily at 2:00 AM (`OnCalendar=*-*-* 02:00:00`)
- **Persistence:** Enabled (runs missed jobs on boot)
- **Accuracy:** 1 minute
- **Location:** `/etc/systemd/system/chaba-assessment.timer`

**Service Configuration:**
- **User:** tony
- **Working Directory:** `/home/tony/CascadeProjects/chaba`
- **Script:** `scripts/overnight-assessment.mjs`
- **Logs:** `logs/assessment.log` (stdout), `logs/assessment-error.log` (stderr)

## Manual Execution

To run the assessment manually:

```bash
cd /home/tony/CascadeProjects/chaba
node scripts/overnight-assessment.mjs
```

To trigger the systemd service immediately:

```bash
sudo systemctl start chaba-assessment.service
```

To check timer status:

```bash
systemctl status chaba-assessment.timer
systemctl list-timers | grep chaba
```

## Log Locations

- **Assessment logs:** `/home/tony/CascadeProjects/chaba/logs/assessment.log`
- **Error logs:** `/home/tony/CascadeProjects/chaba/logs/assessment-error.log`
- **Reports:** `/home/tony/CascadeProjects/chaba/reports/overnight-assessment-YYYY-MM-DD.md`

## Integration with Existing Infrastructure

The overnight assessment system leverages existing Chaba infrastructure:

- **Health Check APIs:** Uses existing `/api/health` endpoints
- **SSOT Configuration:** Reads from `ssot.health.home.yml`
- **GPU Monitoring:** Integrates with GPU status API
- **Yomi System:** Checks Yomi API endpoints and rate limiters
- **Docker:** Uses existing Docker Compose setup
- **Systemd:** Follows pattern of existing Yomi timers
- **Improvements Tracking:** Monitors `ssot.improvements.yml` for pending/planned/completed items

## Thresholds and Alerts

Current monitoring thresholds:

- **GPU Temperature Critical:** > 85°C
- **GPU Temperature Elevated:** > 75°C
- **GPU VRAM Critical:** > 90%
- **Disk Usage Critical:** > 80%
- **Disk Usage Elevated:** > 70%
- **High Error Count:** > 5 errors in summarization
- **High Queue Count:** > 5 queued jobs

## Maintenance

**Regular Tasks:**
- Review assessment reports weekly
- Monitor for recurring issues
- Update thresholds as needed
- Archive old reports periodically (automated — see Report Archival below)
- Adjust assessment scope based on infrastructure changes

## Report Archival

Reports are automatically archived at the end of every assessment run via `archiveOldReports()` in `scripts/overnight-assessment.mjs`.

- **Retention:** 30 days in `reports/`
- **Archive destination:** `reports/archive/`
- **Trigger:** Runs automatically at the end of each assessment (no manual action needed)
- Files older than 30 days are moved (not deleted) — recoverable if needed

**Troubleshooting:**
- Check logs in `logs/assessment-error.log` for failures
- Verify systemd timer is active: `systemctl status chaba-assessment.timer`
- Test script manually to debug issues
- Check network connectivity to monitored services
- Verify Node.js runtime is available

## Future Enhancements

Potential improvements for the assessment system:

- **Historical Trend Analysis:** Track metrics over time
- **Automated Notifications:** Email/Slack alerts for critical issues
- **Dashboard Integration:** Display results in health check dashboard
- **Performance Baselines:** Compare against historical baselines
- **Predictive Analysis:** Identify trends before they become issues
- **Custom Assessment Profiles:** Different scopes for different needs
- **Integration with Monitoring:** Correlate with Netdata/Prometheus metrics

## Phase 3 Impact Scoring Features

**Documentation:** See `docs/kb/dependency-management.md` for comprehensive dependency management documentation.

### Impact Scoring System

**Purpose:** Quantify the expected value of improvements to enable data-driven prioritization and resource allocation.

**Impact Categories:**

**business_impact:** Business value (1-10 scale)
- Revenue impact, customer satisfaction, competitive advantage
- 10: Critical business impact, revenue-generating
- 7-9: Significant business value, strategic importance
- 4-6: Moderate business value, operational improvement
- 1-3: Low business value, nice to have

**technical_impact:** Technical improvement (1-10 scale)
- Code quality, architecture, performance, security
- 10: Critical technical debt, security vulnerability
- 7-9: Significant technical improvement, performance gain
- 4-6: Moderate technical improvement, code quality
- 1-3: Low technical impact, minor cleanup

**user_experience_impact:** User experience value (1-10 scale)
- Usability, performance, reliability, features
- 10: Critical UX issue, user-facing outage
- 7-9: Significant UX improvement, major feature
- 4-6: Moderate UX improvement, minor feature
- 1-3: Low UX impact, polish

**cost_savings_impact:** Cost reduction value (1-10 scale)
- Infrastructure costs, operational efficiency, time savings
- 10: Major cost reduction, significant savings
- 7-9: Moderate cost reduction, measurable savings
- 4-6: Minor cost reduction, some efficiency gains
- 1-3: Minimal cost impact, negligible savings

**impact_summary:** Brief description of expected impact
- Example: "Reduces infrastructure costs by 20% through GPU optimization"
- Purpose: Quick understanding of improvement value

### Priority Calculation

**Weighted Average Formula:**
```
Overall Impact = (business_impact × 0.3) + (technical_impact × 0.3) + 
                 (user_experience_impact × 0.2) + (cost_savings_impact × 0.2)
```

**Priority Mapping:**
- Overall Impact ≥ 8: HIGH priority
- Overall Impact 5-7: MEDIUM priority
- Overall Impact < 5: LOW priority

**Usage:** Used for automatic prioritization alongside manual priority settings.

### Impact Scoring Script

**Script:** `scripts/impact-scoring.mjs`

**Usage:**
```bash
# Analyze current impact scores
node scripts/impact-scoring.mjs analyze

# Calculate impact scores for all improvements
node scripts/impact-scoring.mjs score

# Prioritize improvements by impact
node scripts/impact-scoring.mjs prioritize
```

**Features:**
- **Analyze Mode:** Detailed impact analysis by category and status
- **Score Mode:** Calculate overall impact scores and suggest priorities
- **Prioritize Mode:** Sort improvements by impact and identify priority mismatches

**Example Output:**
```
1. 🟡 MEDIUM 7/10 - Memory Usage Optimization
   Business: 6, Technical: 8, UX: 7, Cost: 5
   Current priority: medium, Effort: 2-3 hours
```

### SSOT Integration

**SSOT Fields:**
```yaml
- label: Memory Usage Optimization
  business_impact: 6
  technical_impact: 8
  user_experience_impact: 7
  cost_savings_impact: 5
  impact_summary: Reduces infrastructure costs and improves system performance
```

**Assessment Integration:**
- Impact scores automatically analyzed during overnight assessments
- High impact improvements (≥8/10) highlighted in reports
- Impact distribution by category included in assessment results
- Priority mismatches between manual and impact-based prioritization identified

### Impact Analysis in Assessment Reports

**High Impact Improvements Section:**
- Lists all improvements with overall impact ≥ 8/10
- Shows individual impact scores and summaries
- Helps identify most valuable work to prioritize

**Impact Distribution:**
- High Impact (≥8): Count of high-value improvements
- Medium Impact (5-7): Count of moderate-value improvements
- Low Impact (<5): Count of low-value improvements

**Category Impact Averages:**
- Average impact score by category
- Identifies which categories have highest expected value
- Helps with resource allocation and category prioritization

### Impact-Based Prioritization Benefits

**Data-Driven Decisions:**
- Quantitative basis for improvement selection
- Reduces bias in prioritization decisions
- Enables comparison across different improvement types

**Resource Allocation:**
- Focus effort on highest-impact improvements
- Align resources with expected business value
- Optimize return on investment for improvement work

**Transparency:**
- Clear rationale for prioritization decisions
- Stakeholder understanding of improvement value
- Historical tracking of impact predictions vs actual results

**Continuous Improvement:**
- Track impact accuracy over time
- Refine impact scoring based on actual outcomes
- Learn which impact categories are most predictive

### Impact Scoring Integration (2026-08-05)
- **Integration**: Overnight assessment now uses shared `parseImprovements` from `impact-scoring.mjs`
- **Fix**: Resolved YAML parsing issues by importing shared parser instead of maintaining separate complex parser
- **Module Changes**:
  - `impact-scoring.mjs`: Exported `parseImprovements` and `calculateOverallImpact` functions
  - Added conditional execution guard to prevent running when imported as module
  - `overnight-assessment.mjs`: Imported shared parser, removed duplicate parsing logic
- **Results**:
  - High Impact (≥8/10): 1 (Security & Dependency Checking - 8.2/10)
  - Medium Impact (5-7/10): 15
  - Low Impact (<5/10): 2
  - Total improvements parsed: 28 (up from 18)
- **Benefits**:
  - Consistent parsing logic across scripts
  - Reduced code duplication
  - Better maintenance with single source of truth
  - Correct dependency tracking in overnight assessment

### Best Practices for Impact Scoring

**Scoring Guidelines:**
- **Be Realistic:** Avoid overestimating impact - conservative scoring is better
- **Consider Effort:** High impact with low effort should be prioritized
- **Think Long-term:** Consider both immediate and future impact
- **Be Specific:** Use impact summaries to explain scoring rationale
- **Review Regularly:** Update impact scores as understanding improves

**Priority Alignment:**
- Use impact scores to validate manual priority assignments
- Address priority mismatches (manual vs impact-based)
- Consider both impact and dependencies when planning
- Adjust manual priority if impact analysis suggests different prioritization

**Category Considerations:**
- Different categories naturally have different impact profiles
- Technical improvements may have high technical impact but low business impact
- Monitoring improvements often have high business impact through risk reduction
- Documentation improvements typically have lower immediate impact

### Integration with Existing Features

**Dependency Management:**
- Impact scores complement dependency analysis
- High impact improvements may justify breaking dependency rules
- Dependency chains can be prioritized by cumulative impact

**Git Integration:**
- Impact scores included in improvement metadata
- Track impact predictions vs actual outcomes via git history
- Link impact changes to specific commits

**Verification Loop:**
- Verify impact predictions during improvement completion
- Update impact scores based on actual results
- Learn from impact prediction accuracy

**Documentation:** See `docs/kb/dependency-management.md` for comprehensive dependency management documentation.

### Dependency Fields and Structure

**SSOT Dependency Fields:**
- **depends_on:** List of improvements that must be completed first (array or single string)
- **dependency_reason:** Explanation of why dependency exists
- **blocks:** List of improvements that cannot start until this one completes (array or single string)
- **blocking_reason:** Explanation of why this improvement blocks others

**Example SSOT Structure:**
```yaml
- label: Memory Usage Optimization
  status: pending
  priority: medium
  depends_on: GPU Queue Job History Verification
  dependency_reason: Memory analysis requires understanding GPU memory usage patterns
  blocks: System Load Analysis, GPU Process Management
  blocking_reason: Memory optimization baseline needed for load and GPU analysis
```

### Dependency Validation

**Automated Validation in Assessment:**
- Checks for missing dependencies (referenced improvements don't exist)
- Detects circular dependencies (A depends on B, B depends on A)
- Validates self-dependencies (improvement cannot depend on itself)
- Checks priority consistency (high priority shouldn't depend on low priority)
- Identifies blocked improvements (dependencies not completed)
- Reports blocking improvements (preventing others from starting)

**Validation Rules:**
- **Circular Dependencies:** Not allowed - flagged during validation
- **Missing Dependencies:** Referenced improvements must exist in SSOT
- **Self Dependencies:** An improvement cannot depend on itself
- **Status Validation:** Dependencies should be in 'completed' status before starting work
- **Priority Consistency:** Higher priority items shouldn't depend on lower priority

**Assessment Report Integration:**
- Dependency validation results included in assessment reports
- Blocked improvements listed with their dependencies
- Blocking improvements identified with downstream impact
- Critical and medium priority issues for dependency problems

**Enhanced Assessment Reports:**
- Blocked improvements identification section
- Blocking improvements reporting section
- Dependency validation results summary
- Dependency graph generation recommendations

### Dependency Graph Generation

**Graph Generation Script:** `scripts/dependency-graph.mjs`

**Usage:**
```bash
# Text format (console output)
node scripts/dependency-graph.mjs text

# Mermaid format (for documentation)
node scripts/dependency-graph.mjs mermaid

# DOT format (for Graphviz)
node scripts/dependency-graph.mjs dot
```

**Output Formats:**
- **Text:** Human-readable dependency tree with status indicators
- **Mermaid:** Markdown-compatible graph syntax for documentation
- **DOT:** Graphviz format for visual diagrams (can generate PNG)

**Text Format Features:**
- Status indicators (✅ completed, 🚀 ready, 🔒 blocked, 📋 planned)
- Dependency chains shown with arrows
- Blocking relationships displayed
- Critical path analysis (longest dependency chain)
- Grouped by status (completed, pending, planned)

**Example Output:**
```
🔒 Memory Usage Optimization (medium)
   ↳ Depends on: GPU Queue Job History Verification
   ↳ Blocks: System Load Analysis, GPU Process Management
```

### Automatic Dependency Resolution

**Resolution Script:** `scripts/dependency-resolver.mjs`

**Usage:**
```bash
node scripts/dependency-resolver.mjs
```

**Analysis Categories:**
- **Ready to Start:** Dependencies met, can begin implementation
- **Blocked:** Dependencies not completed, must wait
- **Suggested Dependencies:** Category-based dependency suggestions
- **Priority Conflicts:** Priority inconsistencies to resolve
- **Orphan Improvements:** No dependencies or dependents, may need relationships

**Smart Suggestions:**
- Category-based dependency recommendations (GPU → Performance, Monitoring → Configuration)
- Priority conflict detection and resolution suggestions
- Orphan improvement identification for relationship building
- Ready-to-start work prioritized by priority

**Example Output:**
```
=== 🚀 Ready to Start (Dependencies Met) ===
✅ Docker Compose Configuration Fix (high)
   Category: configuration
   Effort: 5 minutes
   Suggested action: Start implementation

=== 💡 Suggested Dependencies to Add ===
💡 GPU Temperature Elevated should depend on Memory Usage Optimization
   Reason: GPU work should be optimized after general performance analysis
```

### Dependency Management Workflow

**Complete Dependency Lifecycle:**

1. **Planning Phase:**
   ```bash
   # Analyze current dependencies
   node scripts/dependency-resolver.mjs
   
   # Generate dependency graph
   node scripts/dependency-graph.mjs text
   ```

2. **Implementation Phase:**
   - Start with ready-to-start improvements (no incomplete dependencies)
   - Complete dependencies before starting dependent work
   - Update SSOT status as work progresses

3. **Validation Phase:**
   - Overnight assessment automatically validates dependencies
   - Check for circular dependencies and missing references
   - Review blocked improvements and resolve dependencies

4. **Completion Phase:**
   - Mark improvements as completed in SSOT
   - Dependent improvements become ready to start
   - Re-run dependency resolver to update recommendations

**Best Practices:**
- **Be Specific:** Use exact improvement labels for dependencies
- **Document Reasons:** Always explain why dependencies exist
- **Keep It Minimal:** Only add necessary dependencies to avoid over-constraining
- **Review Regularly:** Remove dependencies that are no longer needed
- **Test Independence:** Ensure improvements can be verified independently
- **Plan Critical Path:** Identify dependencies that form the critical path for delivery

### Integration with Feedback Loop

**Dependency-Aware Auto-Creation:**
- Auto-created improvements check for existing dependencies
- Suggests dependencies based on category patterns
- Validates priority consistency with existing improvements

**Dependency-Aware Verification:**
- Verification checks if dependencies are completed
- Blocks verification if dependencies not met
- Provides clear dependency status in verification results

**Git Integration with Dependencies:**
- Git commits linked to improvements include dependency context
- Dependency completion tracked alongside code changes
- Historical analysis of dependency patterns

### Benefits of Dependency Management

**Planning Benefits:**
- Clear understanding of work sequence
- Accurate timeline estimation
- Critical path identification
- Resource allocation optimization

**Quality Benefits:**
- Prevents starting work without prerequisites
- Ensures proper sequence of changes
- Reduces integration issues
- Improves success rate

**Communication Benefits:**
- Clear dependency visualization
- Stakeholder understanding of constraints
- Progress tracking against dependencies
- Blocker identification and resolution

**Automation Benefits:**
- Automatic dependency validation
- Smart resolution suggestions
- Graph generation for documentation
- Integration with existing feedback loop

## Phase 1 Feedback Loop Features

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
## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **database**: database
- **postgres**: postgres
- **redis**: redis
- **mongodb**: mongodb
- **sql**: sql
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **security**: security
- **auth**: auth
- **encryption**: encryption
- **ssl**: ssl
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **automation**: automation
- **mcp**: mcp
- **weaviate**: weaviate
- **vector**: vector
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026
