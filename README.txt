PI NODE WINDOWS AGENT HELPER - FIXED FOR PI NODE MONITOR PRO

This version fixes the exact compatibility issue found in /app/app.py:
the dashboard calls data.get("status", "").strip(), therefore JSON "status"
must be a plain text string, not an object/dictionary.

Requirements:
- Windows 10/11
- Docker Desktop running
- Python 3.10+
- Pi Node container named testnet2
- Same NODE_STATUS_TOKEN in this helper and SoloHost dashboard

Install:
1. Extract this folder
2. Run install.bat.
3. Enter the exact NODE_STATUS_TOKEN configured in SoloHost.
4. Run start.bat and leave its window open.

Test in a separate PowerShell:
  $token = Read-Host "Helper token"
  Invoke-RestMethod -Uri "http://127.0.0.1:18765/status" -Headers @{Authorization="Bearer $token"}

Expected response includes:
  ok       : True
  status   : [plain text node-status report]
  container: testnet2

Dashboard .env must retain:
  NODE_STATUS_URL=http://host.docker.internal:18765/status
  NODE_STATUS_TOKEN=the-same-secret
  REFRESH_SECONDS=15

Security:
- The helper is read-only and only executes `docker exec testnet2 node-status`.
- It does not access wallets, private keys, or passphrases.
- It binds on 0.0.0.0 so Docker Desktop can reach the Windows host.
- Do not router-port-forward port 18765 or expose it publicly.
- The /status endpoint requires Bearer token authentication.
- /health is an unauthenticated liveness endpoint and reveals no node report.

If the dashboard still errors after this update, check that the helper and SoloHost
use the same token and that the helper's start.bat console shows incoming requests.
