#!/usr/bin/env python3
"""
Generate MCP configuration from SSOT YAML files.

This script reads SSOT configuration files and generates/updates MCP server
configurations to ensure consistency between SSOT and actual MCP setup.
"""

import yaml
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any
import subprocess

# Paths
SSOT_DIR = Path("/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot")
DEVIN_TOOLS_SSOT = SSOT_DIR / "ssot.devin.tools.yml"
GPU_SSOT = SSOT_DIR / "infrastructure" / "ssot.gpu.yml"
OUTPUT_DIR = Path("/home/tony/CascadeProjects/chaba-tony-dell/.windsurf")
MCP_CONFIG_OUTPUT = Path("/home/tony/.config/windsurf/mcp_config.json")

def load_yaml_file(filepath: Path) -> Dict[str, Any]:
    """Load a YAML file safely."""
    try:
        with open(filepath, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return {}

def validate_mcp_consistency(devin_tools: Dict, gpu_tools: Dict) -> List[str]:
    """
    Validate consistency within ssot.devin.tools.yml and cross-reference with ssot.gpu.yml.
    
    Note: devin.tools defines MCP server configurations (how to run them),
    while gpu.yml defines the tools they provide. These are different concerns.
    
    Returns list of issues found.
    """
    issues = []
    
    # Check for duplicate command definitions within mcp-conf
    mcp_conf = devin_tools.get('mcp-conf', [])
    commands_seen = {}
    for config in mcp_conf:
        name = config.get('name')
        command = config.get('command')
        args = tuple(config.get('args', []))
        key = (command, args)
        
        if key in commands_seen:
            issues.append(f"Duplicate command definition: {name} duplicates {commands_seen[key]}")
        else:
            commands_seen[key] = name
    
    # Check for wrapper script duplication
    wrapper_scripts = {}
    for config in mcp_conf:
        name = config.get('name')
        args = config.get('args', [])
        if args and args[0].endswith('.sh') and 'run-' in args[0]:
            script_path = args[0]
            if script_path in wrapper_scripts:
                issues.append(f"Wrapper script {script_path} used by both {wrapper_scripts[script_path]} and {name}")
            else:
                wrapper_scripts[script_path] = name
    
    # Cross-reference: check that MCP servers in mcp-conf are listed in mcp section
    mcp_servers = set(devin_tools.get('mcp', {}).keys())
    mcp_conf_names = {config.get('name') for config in mcp_conf if config.get('name')}
    
    missing_in_mcp_section = mcp_conf_names - mcp_servers
    if missing_in_mcp_section:
        issues.append(f"MCP servers in mcp-conf but not in mcp section: {missing_in_mcp_section}")
    
    missing_in_mcp_conf = mcp_servers - mcp_conf_names
    if missing_in_mcp_conf:
        issues.append(f"MCP servers in mcp section but not in mcp-conf: {missing_in_mcp_conf}")
    
    return issues

def generate_mcp_config(devin_tools: Dict) -> Dict[str, Any]:
    """
    Generate MCP configuration from ssot.devin.tools.yml.
    
    Returns the MCP configuration structure.
    """
    mcp_conf = devin_tools.get('mcp-conf', [])
    
    mcp_config = {
        "mcpServers": {}
    }
    
    for config in mcp_conf:
        name = config.get('name')
        command = config.get('command')
        args = config.get('args', [])
        env = config.get('env', {})
        disabled = config.get('disabled', False)
        
        if disabled:
            continue
        
        server_config = {
            "command": command,
            "args": args
        }
        
        if env:
            server_config["env"] = env
        
        mcp_config["mcpServers"][name] = server_config
    
    return mcp_config

def check_wrapper_scripts(mcp_conf: List[Dict]) -> List[str]:
    """
    Check if wrapper scripts exist and are executable.
    
    Returns list of missing or non-executable scripts.
    """
    issues = []
    
    for config in mcp_conf:
        name = config.get('name')
        args = config.get('args', [])
        
        if args and args[0].endswith('.sh'):
            script_path = Path(args[0])
            
            if not script_path.exists():
                issues.append(f"Wrapper script missing for {name}: {script_path}")
            elif not os.access(script_path, os.X_OK):
                issues.append(f"Wrapper script not executable for {name}: {script_path}")
    
    return issues

def fix_duplicate_commands(devin_tools: Dict) -> Dict:
    """
    Fix duplicate command definitions in mcp-conf.
    
    This is a placeholder for actual fix logic.
    """
    # For now, just return the original
    # In a full implementation, this would consolidate duplicates
    return devin_tools

def main():
    print("=" * 60)
    print("MCP Configuration Synchronization")
    print("=" * 60)
    
    # Load SSOT files
    print("\n1. Loading SSOT files...")
    devin_tools = load_yaml_file(DEVIN_TOOLS_SSOT)
    gpu_tools = load_yaml_file(GPU_SSOT)
    
    if not devin_tools:
        print("ERROR: Could not load ssot.devin.tools.yml")
        sys.exit(1)
    
    if not gpu_tools:
        print("WARNING: Could not load ssot.gpu.yml (continuing anyway)")
    
    # Validate consistency
    print("\n2. Validating MCP configuration consistency...")
    issues = validate_mcp_consistency(devin_tools, gpu_tools)
    
    if issues:
        print("Found issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("No consistency issues found.")
    
    # Check wrapper scripts
    print("\n3. Checking wrapper scripts...")
    mcp_conf = devin_tools.get('mcp-conf', [])
    script_issues = check_wrapper_scripts(mcp_conf)
    
    if script_issues:
        print("Wrapper script issues:")
        for issue in script_issues:
            print(f"  - {issue}")
    else:
        print("All wrapper scripts exist and are executable.")
    
    # Generate MCP config
    print("\n4. Generating MCP configuration...")
    mcp_config = generate_mcp_config(devin_tools)
    
    # Display generated config
    print("\nGenerated MCP configuration:")
    print(json.dumps(mcp_config, indent=2))
    
    # Write to output file if directory exists
    if MCP_CONFIG_OUTPUT.parent.exists():
        print(f"\n5. Writing MCP configuration to {MCP_CONFIG_OUTPUT}...")
        try:
            with open(MCP_CONFIG_OUTPUT, 'w') as f:
                json.dump(mcp_config, f, indent=2)
            print("MCP configuration written successfully.")
        except Exception as e:
            print(f"ERROR writing MCP configuration: {e}")
    else:
        print(f"\n5. Skipping MCP config write (directory {MCP_CONFIG_OUTPUT.parent} does not exist)")
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Consistency issues found: {len(issues)}")
    print(f"Wrapper script issues: {len(script_issues)}")
    print(f"MCP servers configured: {len(mcp_config['mcpServers'])}")
    
    if issues or script_issues:
        print("\n⚠️  Issues found - manual review recommended")
        sys.exit(1)
    else:
        print("\n✓ MCP configuration synchronized successfully")
        sys.exit(0)

if __name__ == "__main__":
    main()
