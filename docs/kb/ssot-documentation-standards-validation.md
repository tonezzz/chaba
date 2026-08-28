---
category: operations
---

# Validation Rules

### Required Fields
- **Standard SSOT**: Must have `title` field
- **Sections**: Must have `title`, `icon`, and `layout` fields
- **Items**: Must have `label` and `text` fields

### YAML Syntax
- Use consistent 2-space indentation
- No trailing whitespace
- Valid YAML syntax (proper quoting, colons, nesting)
- Use `#` for comments

### Content Consistency
- No duplicate section titles within a file
- No duplicate item labels within a section
- Cross-references must be valid
- Tags should be consistent across similar items

### Hostname Compliance
- **Rule**: Use `.local` hostnames instead of IP addresses
- **Format**: `hostname.local` (e.g., `tony-omen.local`)
- **Exceptions**: Health check configs, network documentation
- **Examples**:
  - ✅ `tony-omen.local`
  - ✅ `tony-dell.local`
  - ❌ `192.168.1.42`
  - ❌ `10.0.0.5`

## Field Types and Values

### Status Field
- `active`: Currently being worked on
- `completed`: Finished work
- `pending`: Planned but not started
- `planned`: Future consideration

### Priority Field
- `high`: Critical or urgent
- `medium`: Normal priority
- `low`: Nice to have

### Layout Field
- `list`: Vertical list of items
- `grid`: Grid layout for items
- `timeline`: Chronological timeline

### Tags Field
- Use kebab-case for tag names
- Be consistent with tag terminology
- Use descriptive tags (e.g., `infrastructure`, `automation`, `shared`)

