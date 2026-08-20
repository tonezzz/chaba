---
category: operations
---

# Priority Calculation

### Weighted Average Formula
```
Overall Impact = (business_impact × 0.3) + (technical_impact × 0.3) + 
                 (user_experience_impact × 0.2) + (cost_savings_impact × 0.2)
```

### Priority Mapping
- Overall Impact ≥ 8: HIGH priority
- Overall Impact 5-7: MEDIUM priority
- Overall Impact < 5: LOW priority

## Impact Scoring Script

### Script Location
`scripts/impact-scoring.mjs`

### Usage Modes

#### Analyze Mode
```bash
node scripts/impact-scoring.mjs analyze
```
- Shows impact distribution by category
- Displays category impact averages
- Lists impact summaries for each improvement

#### Score Mode
```bash
node scripts/impact-scoring.mjs score
```
- Calculates overall impact scores for all improvements
- Suggests priority based on impact
- Identifies priority mismatches (manual vs impact-based)
- Sorts improvements by overall impact score

#### Prioritize Mode
```bash
node scripts/impact-scoring.mjs prioritize
```
- Shows top 10 highest impact improvements
- Displays priority mismatches with status and effort
- Provides effort vs impact analysis
- Identifies quick wins and low-impact/high-effort items

