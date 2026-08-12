# Impact Scoring System

## What it is

Data-driven improvement prioritization system that quantifies expected value using weighted impact scores across business, technical, user experience, and cost savings dimensions. Enables objective prioritization decisions and resource allocation.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Impact Categories

### Business Impact (1-10 scale)
- Revenue impact, customer satisfaction, competitive advantage
- 10: Critical business impact, revenue-generating
- 7-9: Significant business value, strategic importance
- 4-6: Moderate business value, operational improvement
- 1-3: Low business value, nice to have

### Technical Impact (1-10 scale)
- Code quality, architecture, performance, security
- 10: Critical technical debt, security vulnerability
- 7-9: Significant technical improvement, performance gain
- 4-6: Moderate technical improvement, code quality
- 1-3: Low technical impact, minor cleanup

### User Experience Impact (1-10 scale)
- Usability, performance, reliability, features
- 10: Critical UX issue, user-facing outage
- 7-9: Significant UX improvement, major feature
- 4-6: Moderate UX improvement, minor feature
- 1-3: Low UX impact, polish

### Cost Savings Impact (1-10 scale)
- Infrastructure costs, operational efficiency, time savings
- 10: Major cost reduction, significant savings
- 7-9: Moderate cost reduction, measurable savings
- 4-6: Minor cost reduction, some efficiency gains
- 1-3: Minimal cost impact, negligible savings

## Priority Calculation

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

## SSOT Integration

### SSOT Fields
```yaml
- label: Improvement Name
  business_impact: 6
  technical_impact: 8
  user_experience_impact: 7
  cost_savings_impact: 5
  impact_summary: Brief description of expected impact
```

### Default Values
- Missing impact scores default to 5 (neutral impact)
- Use explicit scoring for accurate prioritization

## Overnight Assessment Integration

### Impact Analysis in Reports
- High Impact Improvements section (≥8/10)
- Impact distribution counts (high/medium/low)
- Category impact averages
- Priority mismatch identification

### Assessment Enhancements
- Impact scores automatically analyzed during overnight assessments
- High impact improvements highlighted in reports
- Impact distribution included in assessment results
- Priority mismatches identified for review

## Best Practices

### Scoring Guidelines
- **Be Realistic**: Avoid overestimating impact - conservative scoring is better
- **Consider Effort**: High impact with low effort should be prioritized
- **Think Long-term**: Consider both immediate and future impact
- **Be Specific**: Use impact summaries to explain scoring rationale
- **Review Regularly**: Update impact scores as understanding improves

### Priority Alignment
- Use impact scores to validate manual priority assignments
- Address priority mismatches (manual vs impact-based)
- Consider both impact and dependencies when planning
- Adjust manual priority if impact analysis suggests different prioritization

### Category Considerations
- Different categories naturally have different impact profiles
- Technical improvements may have high technical impact but low business impact
- Monitoring improvements often have high business impact through risk reduction
- Documentation improvements typically have lower immediate impact

## Troubleshooting

### Script Not Finding SSOT File
**Issue**: Error "SSOT file not found"
**Solution**: Check SSOT_PATH in impact-scoring.mjs matches actual file location
```javascript
const SSOT_PATH = '/home/tony/CascadeProjects/chaba/docs/ssot/ssot.improvements.yml';
```

### Impact Scores Not Calculating
**Issue**: All improvements showing default 5/10 scores
**Solution**: Verify impact fields are properly formatted in SSOT
```yaml
business_impact: 6  # Not "business_impact: 6/10"
```

### Priority Mismatches Persisting
**Issue**: Manual priorities not aligning with impact scores
**Solution**: Review and update manual priorities in SSOT based on impact analysis

## Related Documentation

- **[Overnight Assessment](overnight-assessment.md)** - Assessment system documentation
- **[Dependency Management](dependency-management.md)** - Improvement dependency tracking
- **[SSOT Improvements](../ssot/ssot.improvements.yml)** - Improvements tracking file

## Tags

- **impact-scoring**: Data-driven prioritization
- **improvements**: System improvement tracking
- **prioritization**: Resource allocation decisions
- **assessment**: Overnight assessment integration
- **ssot**: Single source of truth integration