#!/usr/bin/env python3
"""Run queue/test_gpu_reservations.py with scheduler.INVENTORY pointed at
the mirror's inventory.ini (scheduler hardcodes /home/tony/ansible)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "ansible-mirror"
sys.path.insert(0, str(HERE / "queue"))

import scheduler  # noqa: E402

scheduler.INVENTORY = HERE / "inventory.ini"
scheduler.PLAYBOOK = HERE / "playbooks" / "dispatch_job.yml"
scheduler.ANSIBLE_DIR = HERE

sys.argv = ["test_gpu_reservations.py", "--redis", "100.123.163.11", "--db", "15"]
sys.path.insert(0, str(HERE / "queue"))
import test_gpu_reservations  # noqa: E402

sys.exit(test_gpu_reservations.main())
