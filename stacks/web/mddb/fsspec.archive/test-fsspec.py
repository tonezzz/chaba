#!/usr/bin/env python3
"""Test fsspec Google Drive integration feasibility"""
import sys
import os
import subprocess

print("🔍 Testing fsspec Google Drive integration feasibility...")

# Check if gdrivefs is available
try:
    from gdrivefs import GoogleDriveFileSystem
    print("✅ gdrivefs available in system Python")
    gdrivefs_available = True
except ImportError as e:
    print(f"❌ gdrivefs not available: {e}")
    print("💡 System Python is externally managed")
    print("💡 Options:")
    print("   1. Use mcp-kbman container (has gdrivefs installed)")
    print("   2. Create Python venv and install gdrivefs")
    print("   3. Keep using rclone (current working solution)")
    gdrivefs_available = False

# Check if mcp-kbman container exists
result = subprocess.run(['docker', 'ps', '-a'], capture_output=True, text=True)
if 'mcp-kbman' in result.stdout:
    print("✅ mcp-kbman container exists (has gdrivefs installed)")
    container_available = True
else:
    print("❌ mcp-kbman container not running")
    container_available = False

# Check service account
SERVICE_ACCOUNT = "/home/tony/.config/service_account.json"
if os.path.exists(SERVICE_ACCOUNT):
    print(f"✅ Service account available: {SERVICE_ACCOUNT}")
    service_account_available = True
else:
    print(f"❌ Service account not found: {SERVICE_ACCOUNT}")
    service_account_available = False

# Assessment
print("\n🎯 Feasibility Assessment:")
if gdrivefs_available:
    print("✅ Can use gdrivefs directly in system Python")
elif container_available and service_account_available:
    print("✅ Can use gdrivefs via mcp-kbman container")
    print("💡 Would need to run Python scripts inside container")
else:
    print("❌ fsspec not immediately feasible")
    print("💡 Recommendation: Keep using rclone (working solution)")

print("\n📋 Current Status:")
print(f"   - gdrivefs available: {gdrivefs_available}")
print(f"   - mcp-kbman container: {container_available}")
print(f"   - Service account: {service_account_available}")
print(f"   - rclone working: ✅ (current solution)")