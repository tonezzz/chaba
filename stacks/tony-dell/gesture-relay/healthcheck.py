import sys
import urllib.request

sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8794/health", timeout=3).status == 200 else 1)
