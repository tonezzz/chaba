---
category: operations
---

# Key Details

### Common Error Patterns

#### 1. Indentation Errors

**Error**: Inconsistent or incorrect indentation
```yaml
# INCORRECT
services:
  - id: web
  url: http://localhost:8080
    category: web  # Wrong indentation level

# CORRECT
services:
  - id: web
    url: http://localhost:8080
    category: web
```

**Root Cause**: YAML is indentation-sensitive (like Python). Inconsistent indentation breaks the document structure.

**Detection**: YAML parsers throw indentation errors with line numbers.

**Prevention**:
- Use consistent indentation (2 spaces recommended)
- Configure editor to show whitespace characters
- Use YAML linter (yamllint) in pre-commit hooks

#### 2. Colon-Space Requirement

**Error**: Missing space after colon in key-value pairs
```yaml
# INCORRECT
name:tony-omen
port:8080

# CORRECT
name: tony-omen
port: 8080
```

**Root Cause**: YAML requires space after colon in key-value pairs to distinguish from other constructs.

**Detection**: Parser reports "mapping values are not allowed here" or similar errors.

**Prevention**:
- Always use space after colons in key-value pairs
- Use editor YAML syntax highlighting
- Configure linter to catch colon-space issues

#### 3. Quote Usage Issues

**Error**: Incorrect or missing quotes for special characters
```yaml
# INCORRECT
url: http://localhost:8080/apps/health-check/
message: This is a "quoted" string with issues

# CORRECT
url: "http://localhost:8080/apps/health-check/"
message: 'This is a "quoted" string with issues'
```

**Root Cause**: Special characters (colons, hashes, quotes) require proper quoting to avoid parsing ambiguity.

**Detection**: Parser reports unexpected character or mapping errors.

**Prevention**:
- Quote URLs and strings with special characters
- Use single quotes for strings with double quotes inside
- Use double quotes for escape sequences

#### 6. Multi-line Text Field Pattern

**Error**: Multi-line text fields using single quotes cause YAML parsing errors
```yaml
# INCORRECT - causes "Missing closing quote" error
text: 'This is a multi-line
  text field that spans
  multiple lines'

# CORRECT - use block scalar syntax
text: |
  This is a multi-line
  text field that spans
  multiple lines
```

**Root Cause**: YAML single-quoted strings cannot span multiple lines. Multi-line content requires block scalar syntax (`|` for literal, `>` for folded).

**Detection**: Parser reports "Missing closing quote" or "unexpected scalar" errors at the line where the multi-line content begins.

**Prevention**:
- Use `text: |` for literal multi-line strings (preserves newlines)
- Use `text: >` for folded multi-line strings (converts newlines to spaces)
- Indent content consistently under the block scalar marker
- Avoid single quotes for multi-line content

**Real-World Example**: Fixed in `docs/ssot/ssot.improvements.yml` (2026-08-12) - 8 text fields converted from single quotes to block scalars to resolve YAML parsing errors.

#### 7. Placeholder Variable Quoting

**Error**: Unquoted placeholder variables in URL values
```yaml
# INCORRECT - causes "Unexpected scalar at node end" error
url: {profile}/api/health
url: {profile}/apps/

# CORRECT - quoted placeholder variables
url: "{profile}/api/health"
url: "{profile}/apps/"
```

**Root Cause**: YAML interprets unquoted `{variable}` as potential flow collection syntax, causing parsing errors when followed by path segments.

**Detection**: Parser reports "Unexpected scalar at node end" with caret pointing to the placeholder variable.

**Prevention**:
- Always quote URL values containing placeholder variables
- Use double quotes for placeholders that will be substituted
- Apply consistently across all SSOT configuration files

**Real-World Example**: Fixed in `docs/ssot/infrastructure/ssot.health.yml` (2026-08-12) - 8 URL entries required quoting to enable MCP health server configuration parsing.

#### 8. List Format Errors

**Error**: Incorrect list item formatting
```yaml
# INCORRECT
services:
- web
- api
  database  # Wrong indentation

# CORRECT
services:
  - web
  - api
  - database
```

**Root Cause**: List items must be properly indented under their parent key.

**Detection**: Parser reports list formatting errors.

**Prevention**:
- Use consistent indentation for list items
- Ensure hyphen is at correct indentation level
- Use YAML linter to validate list structures

#### 9. Comment Placement

**Error**: Comments in invalid locations
```yaml
# INCORRECT
services: # This is a comment
  - id: web # Another comment
    url: http://localhost:8080 # Invalid comment placement

# CORRECT
services:  # Main services list
  - id: web
    url: http://localhost:8080  # Web service URL
```

**Root Cause**: Comments must be at the end of lines or on separate lines, not embedded in values.

**Detection**: Parser may accept but cause unexpected behavior.

**Prevention**:
- Place comments at end of lines or on separate lines
- Avoid comments in the middle of values
- Use descriptive keys instead of inline comments

### Validation Tools

#### yamllint

**Installation**:
```bash
pip install yamllint
