---
category: operations
---

# Lint single file
yamllint file.yml

# Lint directory
yamllint docs/ssot/

# Custom config
yamllint -c .yamllint file.yml
```

**Configuration** (.yamllint):
```yaml
rules:
  line-length:
    max: 120
  indentation:
    spaces: 2
    indent-sequences: true
  comments:
    min-spaces-from-content: 1
  empty-lines:
    max: 2
```

#### Pre-commit Hook

**Script**: `.git/hooks/pre-commit`
```bash
#!/bin/bash
