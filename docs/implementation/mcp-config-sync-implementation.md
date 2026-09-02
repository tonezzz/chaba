# MCP Configuration Synchronization Implementation

**Version:** 1.0
**Last Updated:** 2026-08-03
**Status:** Production Ready

## Overview

This implementation provides automated synchronization between SSOT (Single Source of Truth) YAML configuration files and the actual MCP (Model Context Protocol) server configuration used by Windsurf/Cascade. The system ensures consistency, validates configurations, and automates the deployment of MCP server settings.

## Architecture

### Components

1. **SSOT Configuration Files** (`docs/ssot/`)
   - `ssot.devin.tools.yml`: Defines MCP server configurations
   - `ssot.gpu.yml`: Defines tools provided by MCP servers
   - Other SSOT files: Application and infrastructure configurations

2. **Generation Script** (`scripts/generate-mcp-configs.py`)
   - Reads SSOT YAML files
   - Validates configuration consistency
   - Checks wrapper scripts
   - Generates MCP configuration JSON
   - Deploys to Windsurf config directory

3. **Validation Script** (`scripts/validate-configs.sh`)
   - Validates YAML syntax across all SSOT files
   - Checks SSOT structure compliance
   - Validates hostname usage (.local vs IP addresses)
   - Compares with served/public copies
   - MCP-specific validation

4. **Wrapper Scripts** (`.windsurf/run-*.sh`)
   - Shell scripts that wrap MCP server execution
   - Provide environment setup and error handling
   - Must be executable to pass validation

5. **Output Configuration** (`~/.config/windsurf/mcp_config.json`)
   - Generated MCP configuration in Windsurf format
   - Consumed by Windsurf/Cascade for MCP server management

### Data Flow

```
SSOT YAML Files
    ↓
generate-mcp-configs.py
    ↓ (validation)
validate-configs.sh
    ↓ (generation)
MCP Config JSON
    ↓ (deployment)
Windsurf Configuration
```

## SSOT Structure

### ssot.devin.tools.yml

This file defines MCP server configurations in two sections:

#### `mcp` Section
Lists MCP server names and their purposes:
```yaml
mcp:
  cdp-tony-dell: Chrome DevTools Protocol (Tony Dell).
  github: Local github service.
  mcp-gpu: Local GPU control.
  mcp-llama: Local Llama.cpp.
  yomi: LINE conversation viewer.
```

#### `mcp-conf` Section
Defines how to run each MCP server:
```yaml
mcp-conf:
- name: github
  command: /bin/bash
  args:
  - /home/tony/CascadeProjects/chaba/.windsurf/run-github-mcp.sh
- name: mcp-gpu
  command: /usr/bin/python3
  args:
  - /home/tony/CascadeProjects/chaba/mcp-servers/mcp-gpu/server.py
  env:
    IMAGEN_URL: http://localhost:8080/apps/imagen2/api
    LLAMA_URL: http://tony-omen.taila0626a.ts.net:8001
  disabled: false  # Optional, defaults to false
```

### ssot.gpu.yml

This file defines the tools provided by MCP servers:
```yaml
tools:
  mcp-gpu:
    - mcp1_gpu_status: Check VRAM and compute process summary
    - mcp1_hold_llama: Move llama-server to CPU
    - mcp1_resume_llama: Restore llama-server to original n_gpu_layers
  mcp-llama:
    - mcp2_status: Check llama-server health
    - mcp2_chat: Chat with loaded model
```

## Script Usage

### generate-mcp-configs.py

#### Purpose
Generate MCP configuration from SSOT files and deploy to Windsurf.

#### Usage
```bash
python3 scripts/generate-mcp-configs.py
```

#### Output
The script outputs:
1. Loading status of SSOT files
2. Consistency validation results
3. Wrapper script validation results
4. Generated MCP configuration (JSON)
5. Deployment status
6. Summary with counts

#### Exit Codes
- `0`: Success, no issues found
- `1`: Issues found (consistency or wrapper script problems)

#### Example Output
```
============================================================
MCP Configuration Synchronization
============================================================

1. Loading SSOT files...

2. Validating MCP configuration consistency...
No consistency issues found.

3. Checking wrapper scripts...
All wrapper scripts exist and are executable.

4. Generating MCP configuration...

Generated MCP configuration:
{
  "mcpServers": {
    "github": {
      "command": "/bin/bash",
      "args": [
        "/home/tony/CascadeProjects/chaba/.windsurf/run-github-mcp.sh"
      ]
    }
  }
}

5. Writing MCP configuration to /home/tony/.config/windsurf/mcp_config.json...
MCP configuration written successfully.

============================================================
Summary
============================================================
Consistency issues found: 0
Wrapper script issues: 0
MCP servers configured: 5

✓ MCP configuration synchronized successfully
```

### validate-configs.sh

#### Purpose
Validate all SSOT configuration files for syntax, structure, and compliance.

#### Usage
```bash
bash scripts/validate-configs.sh
```

#### Validation Checks
1. **YAML Syntax**: Ensures all YAML files are syntactically valid
2. **SSOT Structure**: Checks for required fields (title, sections)
3. **Duplicate Detection**: Identifies duplicate section titles
4. **Hostname Compliance**: Enforces .local hostname usage (not IP addresses)
5. **Served Copy Comparison**: Compares SSOT with served/public copies
6. **MCP Configuration**: Validates MCP-specific structure

#### Exit Codes
- `0`: Success (with or without warnings)
- `1`: Validation failed (errors found)

#### Example Output
```
==========================================
SSOT Configuration Validation
==========================================

Validating SSOT files in /home/tony/CascadeProjects/chaba/docs/ssot...

Checking: ssot.apps.chaba.yml
  ✓ Valid

Checking: ssot.devin.tools.yml
  ✓ Valid

Validating MCP configuration...

Checking: ssot.devin.tools.yml
  ✓ MCP servers defined
  ✓ MCP configuration section exists

==========================================
Validation Summary
==========================================
Total files checked: 16
Valid files: 16
Invalid files: 0
Total warnings: 0

✅ All SSOT files are valid
```

## Workflow Guide

### Adding a New MCP Server

1. **Update SSOT** (`docs/ssot/ssot.devin.tools.yml`):
   ```yaml
   mcp:
     new-server: Description of new server.

   mcp-conf:
   - name: new-server
     command: /path/to/command
     args:
     - /path/to/script.sh
     env:
       VAR_NAME: value
   ```

2. **Create wrapper script** (if using shell script):
   ```bash
   touch .windsurf/run-new-server.sh
   chmod +x .windsurf/run-new-server.sh
   # Edit script with server startup logic
   ```

3. **Run validation**:
   ```bash
   bash scripts/validate-configs.sh
   ```

4. **Generate MCP config**:
   ```bash
   python3 scripts/generate-mcp-configs.py
   ```

5. **Verify deployment**:
   ```bash
   cat ~/.config/windsurf/mcp_config.json
   ```

### Disabling an MCP Server

1. **Update SSOT** (`docs/ssot/ssot.devin.tools.yml`):
   ```yaml
   mcp-conf:
   - name: server-to-disable
     command: /path/to/command
     args:
     - /path/to/script.sh
     disabled: true  # Add this line
   ```

2. **Regenerate config**:
   ```bash
   python3 scripts/generate-mcp-configs.py
   ```

3. **Verify server is not in output**:
   ```bash
   cat ~/.config/windsurf/mcp_config.json
   # Server should not appear in mcpServers
   ```

### Updating MCP Server Configuration

1. **Modify SSOT** with new command, args, or env variables
2. **Run validation** to ensure YAML syntax is correct
3. **Generate MCP config** to apply changes
4. **Restart Windsurf/Cascade** to pick up new configuration

## Troubleshooting

### Issue: "Wrapper script missing for server-name"

**Cause:** The wrapper script referenced in SSOT does not exist.

**Solution:**
1. Check the path in `ssot.devin.tools.yml` under `mcp-conf`
2. Create the wrapper script if missing:
   ```bash
   touch .windsurf/run-server-name.sh
   chmod +x .windsurf/run-server-name.sh
   ```
3. Re-run `generate-mcp-configs.py`

### Issue: "Wrapper script not executable for server-name"

**Cause:** The wrapper script exists but lacks execute permissions.

**Solution:**
```bash
chmod +x .windsurf/run-server-name.sh
```

### Issue: "Duplicate command definition"

**Cause:** Two MCP servers have identical (command, args) pairs.

**Solution:**
1. Review `ssot.devin.tools.yml` mcp-conf section
2. Ensure each server has a unique command/args combination
3. If intentionally sharing a wrapper, use different arguments or environment variables

### Issue: "MCP servers in mcp-conf but not in mcp section"

**Cause:** A server is defined in mcp-conf but not listed in the mcp section.

**Solution:**
Add the server to the mcp section in `ssot.devin.tools.yml`:
```yaml
mcp:
  server-name: Description of server.
```

### Issue: "Skipping MCP config write (directory does not exist)"

**Cause:** The Windsurf configuration directory does not exist.

**Solution:**
```bash
mkdir -p ~/.config/windsurf
```

### Issue: "Invalid YAML syntax"

**Cause:** YAML syntax error in SSOT file.

**Solution:**
1. Run validation to identify the problematic file:
   ```bash
   bash scripts/validate-configs.sh
   ```
2. Check for common YAML errors:
   - Incorrect indentation (use spaces, not tabs)
   - Missing colons after keys
   - Unquoted special characters
   - Missing quotes around strings with colons
3. Fix the syntax error and re-run validation

### Issue: "IP addresses found (should use .local hostnames)"

**Cause:** SSOT file contains IP addresses instead of .local hostnames.

**Solution:**
Replace IP addresses with .local hostnames:
- `192.168.1.48` → `tony-omen.local`
- `192.168.1.42` → `tony-dell.local`

**Exception:** Health check configs (`ssot.health.*.yml`) may use IP addresses.

### Issue: Generated config not picked up by Windsurf

**Cause:** Windsurf/Cascade needs to be restarted to reload configuration.

**Solution:**
1. Restart Windsurf/Cascade application
2. Or reload MCP configuration if the application supports it
3. Check Windsurf logs for configuration loading errors

## Validation Rules

### Consistency Validation

The `generate-mcp-configs.py` script validates:

1. **Duplicate Command Definitions**
   - Checks for identical (command, args) pairs across servers
   - Prevents accidental duplication

2. **Wrapper Script Duplication**
   - Ensures wrapper scripts are not shared across servers
   - Each server should have its own wrapper or use direct commands

3. **Cross-Reference Consistency**
   - All servers in mcp-conf must be listed in mcp section
   - All servers in mcp section must have mcp-conf entries

### SSOT Validation

The `validate-configs.sh` script validates:

1. **YAML Syntax**
   - All YAML files must be syntactically valid
   - Uses Python yaml.safe_load for validation

2. **SSOT Structure**
   - Standard SSOT files must have a `title` field
   - Sections must be properly structured
   - Config-type files (health, gpu, services, apps) have flexible structures

3. **Duplicate Detection**
   - Checks for duplicate section titles
   - Warns about potential data duplication

4. **Hostname Compliance**
   - Enforces .local hostname usage
   - Allows IP addresses in health check configs
   - Checks for common private IP ranges (192.168.x.x, 10.x.x.x, 172.16-31.x.x)

5. **Served Copy Comparison**
   - Compares SSOT with served copies in `stacks/web/public/`
   - Compares SSOT with public copies in `public/docs/overview/`
   - Warns about discrepancies

6. **MCP Configuration**
   - Verifies MCP servers are defined
   - Checks mcp-conf section exists
   - Ensures MCP configuration structure is valid

## Best Practices

### SSOT Management

1. **Single Source of Truth**: Always edit SSOT files, never edit generated MCP config directly
2. **Version Control**: Commit SSOT changes to git before regenerating config
3. **Validation First**: Always run validation before making changes
4. **Incremental Changes**: Add one server at a time and test
5. **Documentation**: Document server purposes in the mcp section descriptions

### Wrapper Script Development

1. **Error Handling**: Include proper error handling in wrapper scripts
2. **Logging**: Add logging for debugging server startup issues
3. **Environment**: Use environment variables for configuration
4. **Idempotency**: Scripts should be safe to run multiple times
5. **Permissions**: Ensure scripts are executable before committing

### Configuration Updates

1. **Test Locally**: Test configuration changes in a local environment first
2. **Backup**: Backup existing MCP config before regenerating
3. **Rollback**: Keep previous SSOT versions for quick rollback
4. **Monitoring**: Monitor MCP server health after configuration changes
5. **Documentation**: Document configuration changes in commit messages

## Maintenance

### Regular Tasks

1. **Weekly Validation**: Run `validate-configs.sh` to catch issues early
2. **Monthly Review**: Review MCP server usage and disable unused servers
3. **Quarterly Audit**: Audit wrapper scripts for security and performance
4. **Version Updates**: Update MCP server versions as needed

### Monitoring

Monitor the following:
- MCP server startup success/failure
- Wrapper script execution errors
- Configuration validation failures
- SSOT file changes

### Backup Strategy

1. **SSOT Backups**: SSOT files are in git, use git for version control
2. **Generated Config**: Generated config can be regenerated from SSOT
3. **Wrapper Scripts**: Keep wrapper scripts in git under `.windsurf/`

## Integration with CI/CD

### Git Hook (Optional)

Add a pre-commit hook to validate SSOT files:
```bash
#!/bin/bash
# .git/hooks/pre-commit
bash scripts/validate-configs.sh
if [ $? -ne 0 ]; then
    echo "SSOT validation failed. Commit aborted."
    exit 1
fi
```

### CI Pipeline (Optional)

Add SSOT validation to CI pipeline:
```yaml
- name: Validate SSOT
  run: |
    bash scripts/validate-configs.sh
    python3 scripts/generate-mcp-configs.py
```

## Appendix

### File Locations

| File/Directory | Path | Purpose |
|----------------|------|---------|
| SSOT Directory | `docs/ssot/` | Single source of truth YAML files |
| Devin Tools SSOT | `docs/ssot/ssot.devin.tools.yml` | MCP server configurations |
| GPU SSOT | `docs/ssot/infrastructure/ssot.gpu.yml` | MCP tool definitions |
| Generation Script | `scripts/generate-mcp-configs.py` | MCP config generator |
| Validation Script | `scripts/validate-configs.sh` | SSOT validator |
| Wrapper Scripts | `.windsurf/run-*.sh` | MCP server startup scripts |
| Output Config | `~/.config/windsurf/mcp_config.json` | Generated MCP config |

### Exit Code Reference

| Script | Exit Code | Meaning |
|--------|-----------|---------|
| generate-mcp-configs.py | 0 | Success, no issues |
| generate-mcp-configs.py | 1 | Issues found (consistency or wrapper) |
| validate-configs.sh | 0 | Success (with or without warnings) |
| validate-configs.sh | 1 | Validation failed (errors) |

### Related Documentation

- [MCP Configuration Status Report](../reports/mcp-config-status-report.md)
- [SSOT Documentation](../overview/ssot-structure.md)
- [Hostname Enforcement Strategy](../overview/hostname-enforcement-strategy.md)
- [MCP Tools Knowledge Base](../kb/mcp-tools.md)

## Support

For issues or questions about MCP configuration synchronization:
1. Check this documentation
2. Review the status report for current issues
3. Run validation scripts to identify problems
4. Check wrapper script logs for server-specific issues
5. Consult SSOT documentation for structure questions
