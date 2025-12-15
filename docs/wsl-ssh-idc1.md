# Standard WSL → SSH → idc1 template (unattended)

Use this pattern for any remote command to avoid PowerShell quoting issues (especially with characters like `@`, `{}`, and quotes).

```powershell
# Remote bash script (multi-line)
$remote = @'
set -euo pipefail
echo "[REMOTE] host=$(hostname) user=$(whoami)"
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}" | head
'@

# Encode so we don't fight nested quoting
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($remote -replace "`r","")))

# Execute on idc1 via WSL ssh (unattended)
wsl bash -lc "printf %s '$b64' | base64 -d | /usr/bin/ssh -i ~/.ssh/chaba_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes chaba@idc1.surf-thailand.com 'bash -s'"
```

Notes:
- This requires the key to exist inside WSL at `~/.ssh/chaba_ed25519` with `chmod 600`.
- Prefer this over inline one-liners when the remote command contains quotes, braces, or Go-template strings like `{{.Names}}`.

Always use this unattended WSL → SSH pattern for idc1 work:
- `wsl bash -lc ...`
- user: `chaba@idc1.surf-thailand.com`
- key: `~/.ssh/chaba_ed25519`
- options: `-o IdentitiesOnly=yes -o BatchMode=yes`
