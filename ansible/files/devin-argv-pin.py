#!/usr/bin/env python3
"""Idempotently enable software rendering in Devin Desktop's argv.json.

Path is derived from product.json dataFolderName ('.devin'), NOT the
user-data dir (~/.config/Devin). Preserves all other keys/comments and
prints CHANGED only when the file actually changed.
"""
import os
import re
import shutil
import sys
import time

path = os.path.expanduser("~/.devin/argv.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
if os.path.exists(path):
    original = open(path, encoding="utf-8").read()
else:
    original = '{\n\t"disable-hardware-acceleration": true\n}\n'

uncommented = re.compile(
    r'(?m)^([ \t]*)//[ \t]*"disable-hardware-acceleration"[ \t]*:'
    r'[ \t]*true[ \t]*,?[ \t]*$')
valued = re.compile(
    r'(?m)^([ \t]*)"disable-hardware-acceleration"[ \t]*:'
    r'[ \t]*[^\n,}]+')

if uncommented.search(original):
    updated = uncommented.sub(r'\1"disable-hardware-acceleration": true,', original)
elif valued.search(original):
    updated = valued.sub(r'\1"disable-hardware-acceleration": true', original)
else:
    idx = original.rfind('}')
    if idx < 0:
        print("ERROR: no closing brace in argv.json", file=sys.stderr)
        sys.exit(2)
    updated = original[:idx] + '\t"disable-hardware-acceleration": true,\n' + original[idx:]

if updated == original:
    print("OK")
    sys.exit(0)

if os.path.exists(path):
    shutil.copy2(path, path + ".bak." + time.strftime("%Y%m%dT%H%M%S"))
open(path, "w", encoding="utf-8").write(updated)
print("CHANGED")
