---
category: operations
---

# Phase 3 Impact Scoring Features

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

