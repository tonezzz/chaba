---
category: operations
---

# Impact Scoring System

## What it is

Data-driven improvement prioritization system that quantifies expected value using weighted impact scores across business, technical, user experience, and cost savings dimensions. Enables objective prioritization decisions and resource allocation.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


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

## See also

- [Impact Scoring Calculation](impact-scoring-calculation.md)
- [Impact Scoring Categories](impact-scoring-categories.md)
- [Impact Scoring Integration](impact-scoring-integration.md)
