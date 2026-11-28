#!/bin/bash
if [ -b /dev/zram0 ]; then
  swapoff /dev/zram0 2>/dev/null || true
  zramctl --reset /dev/zram0 2>/dev/null || true
fi
# Do not rmmod; zram may be used elsewhere.
