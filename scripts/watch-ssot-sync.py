#!/usr/bin/env python3
"""Watch SSOT YAML files and auto-sync to MDDB when updated"""
import os
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

SSOT_DIR = "/home/tony/CascadeProjects/chaba/docs/ssot"
SYNC_SCRIPT = "/home/tony/CascadeProjects/chaba/scripts/sync-ssot-to-mddb.py"

class SSOTFileHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_sync = {}
        self.sync_delay = 2  # seconds to wait for file writes to complete
    
    def on_modified(self, event):
        if event.is_directory:
            return
        
        if event.src_path.endswith('.yml'):
            # Debounce rapid file changes
            current_time = time.time()
            if event.src_path in self.last_sync:
                if current_time - self.last_sync[event.src_path] < self.sync_delay:
                    return
            
            self.last_sync[event.src_path] = current_time
            rel_path = os.path.relpath(event.src_path, SSOT_DIR)
            print(f"📝 SSOT file modified: {rel_path}")
            print("⏳ Triggering sync to MDDB...")
            
            # Run sync script
            import subprocess
            try:
                result = subprocess.run(
                    ["python3", SYNC_SCRIPT],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    print("✅ SSOT sync completed successfully")
                else:
                    print(f"❌ SSOT sync failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                print("❌ SSOT sync timed out")
            except Exception as e:
                print(f"❌ SSOT sync error: {e}")

def main():
    print("👀 Starting SSOT file watcher...")
    print(f"📁 Monitoring: {SSOT_DIR}")
    print("🔄 Auto-syncing to MDDB on YAML changes")
    print("Press Ctrl+C to stop\n")
    
    event_handler = SSOTFileHandler()
    observer = Observer()
    observer.schedule(event_handler, SSOT_DIR, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping SSOT file watcher...")
        observer.stop()
    
    observer.join()
    print("✅ SSOT file watcher stopped")

if __name__ == "__main__":
    main()