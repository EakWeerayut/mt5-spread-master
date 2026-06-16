# Headless-safe view-only dashboard tunnel — for Alice / automation.
#
# Same idea as share_viewonly.ps1 but safe to run hidden / non-interactive:
#   - NO Set-Clipboard (throws in non-interactive/STA-less sessions)
#   - NO $ErrorActionPreference='Stop' (one non-fatal error must not kill the run)
#   - Writes the share URL to deribit-dashboard-url.txt only
# Keeps running (Wait-Process on cloudflared) until the tunnel dies or is killed.

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- stable token (created once, reused every run) ---------------------------
$tokenFile = Join-Path $here '.share_token'
if (Test-Path $tokenFile) {
  $token = (Get-Content $tokenFile -Raw).Trim()
} else {
  $token = -join ((48..57)+(97..122) | Get-Random -Count 16 | ForEach-Object {[char]$_})
  Set-Content -Path $tokenFile -Value $token -Encoding ASCII -NoNewline
}

# --- free port 5051 if a previous share session is still running -------------
Get-NetTCPConnection -LocalPort 5051 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

# --- start the view-only app on 5051 -----------------------------------------
$env:DASH_VIEW_ONLY = '1'
$env:DASH_PORT      = '5051'
$env:DASH_TOKEN     = $token
$app = Start-Process python -ArgumentList 'app.py' -WorkingDirectory $here -WindowStyle Hidden -PassThru
for ($i = 0; $i -lt 40; $i++) {
  try { Invoke-WebRequest "http://localhost:5051/?key=$token" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
  catch { Start-Sleep -Milliseconds 500 }
}

# --- start cloudflared and capture the generated URL -------------------------
$log = Join-Path $env:TEMP 'cf_dash.log'
Remove-Item $log, "$log.out" -ErrorAction SilentlyContinue
$cf = Start-Process cloudflared `
  -ArgumentList 'tunnel','--url','http://localhost:5051','--no-autoupdate' `
  -RedirectStandardError $log -RedirectStandardOutput "$log.out" `
  -WindowStyle Hidden -PassThru

$base = $null
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Milliseconds 500
  if (Test-Path $log) {
    $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($m) { $base = $m.Matches[0].Value; break }
  }
}

try {
  if ($base) {
    $url = "$base/?key=$token"
    Set-Content -Path (Join-Path $here 'deribit-dashboard-url.txt') -Value $url -Encoding UTF8 -NoNewline
  }
  Wait-Process -Id $cf.Id
}
finally {
  Stop-Process -Id $cf.Id  -Force -ErrorAction SilentlyContinue
  Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
}
