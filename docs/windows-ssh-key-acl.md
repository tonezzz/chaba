# Windows SSH key ACL fix

When NTFS permissions prevent WSL/OpenSSH from using a private key (the “UNPROTECTED PRIVATE KEY FILE” error), run the following in an elevated PowerShell session. This consistently resets ownership and grants read-only access to the current user:

```powershell
$acct = "$env:COMPUTERNAME\$env:USERNAME"

takeown /F "C:\chaba\.secrets\pc1\chaba2\.ssh\chaba_ed25519"

icacls "C:\chaba\.secrets\pc1\chaba2\.ssh" /inheritance:r
icacls "C:\chaba\.secrets\pc1\chaba2\.ssh" /grant:r "$($acct):(OI)(CI)(RX)"

icacls "C:\chaba\.secrets\pc1\chaba2\.ssh\chaba_ed25519" /inheritance:r
icacls "C:\chaba\.secrets\pc1\chaba2\.ssh\chaba_ed25519" /grant:r "$($acct):(R)"
```

After running these commands, retry the SSH command from WSL.
