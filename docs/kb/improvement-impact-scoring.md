# Improvement impact scoring

Use impact scoring to prioritize improvements based on their expected value.

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

**Priority Calculation:** Weighted average of impact scores

- Formula: (business * 0.3) + (technical * 0.3) + (user_experience * 0.2) + (cost_savings * 0.2)
- Result: Used for automatic prioritization alongside manual priority
