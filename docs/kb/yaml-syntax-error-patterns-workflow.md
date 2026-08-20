---
category: operations
---

# Check YAML syntax in SSOT files
yamllint docs/ssot/*.yml
if [ $? -ne 0 ]; then
  echo "YAML syntax errors found. Please fix before committing."
  exit 1
fi
```

#### Online Validators

- YAML Lint: https://www.yamllint.com/
- YAML Validator: https://codebeautify.org/yaml-validator

### SSOT-Specific Patterns

#### SSOT Template Validation

**Common SSOT Errors**:
1. Missing required fields (label, status, priority)
2. Invalid enum values (status: pending/completed/planned)
3. Incorrect dependency references
4. Malformed URL patterns

**Validation Script**: `scripts/ssot-validate.mjs`
```bash
node scripts/ssot-validate.mjs docs/ssot/ssot.improvements.yml
```

#### Health Check Configuration

**Common Health Check Errors**:
1. Invalid URL formats
2. Missing required fields (id, url, category)
3. Incorrect category values
4. Malformed recovery actions

**Validation**: Use overnight assessment script
```bash
node scripts/overnight-assessment.mjs
```

## Error Resolution Workflow

### 1. Identify Error Location
```bash
# Use parser error message to find line number
# Example: "Error at line 45: mapping values are not allowed here"
```

### 2. Examine Context
```bash
# Read surrounding lines to understand structure
sed -n '40,50p' file.yml
```

### 3. Apply Fix
```bash
# Fix the specific syntax error
# Use consistent indentation
# Add required spaces/quotes
```

### 4. Validate Fix
```bash
# Test with YAML parser
python3 -c "import yaml; yaml.safe_load(open('file.yml'))"

# Or use yamllint
yamllint file.yml
```

### 5. Run Full Validation
```bash
# Run SSOT validation
node scripts/ssot-validate.mjs docs/ssot/ssot.improvements.yml

# Run overnight assessment
node scripts/overnight-assessment.mjs
```

