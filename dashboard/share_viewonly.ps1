# Share the Deribit dashboard as a READ-ONLY public link (one click).
#
# Starts a second, view-only instance of app.py on port 5051 (your normal
# full-access dashboard on 5050 is untouched) and exposes it through a
# Cloudflare quick tunnel. The view-only instance refuses every write + live
# Deribit refresh; a fixed token (.share_token) keeps random visitors out.
#
# IMPORTANT: this uses cloudflared, NOT ngrok, on purpose. Your ngrok free
# account + static domain are reserved for the LINE bot (port 3000). ngrok free
# allows only one tunnel at a time, so the dashboard must NOT use ngrok or it
# would knock the LINE bot's webhook offline. This script never touches ngrok.
#
# The full share URL is printed, copied to your clipboard, and written to
# deribit-dashboard-url.txt (in this dashboard folder). Press Ctrl+C to stop.
# (cloudflared quick tunnels get a fresh random URL each run.)

$ErrorActionPreference = 'Stop'
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
Write-Host "Starting view-only dashboard on http://localhost:5051 ..." -ForegroundColor Cyan
$env:DASH_VIEW_ONLY = '1'
$env:DASH_PORT      = '5051'
$env:DASH_TOKEN     = $token
$app = Start-Process python -ArgumentList 'app.py' -WorkingDirectory $here -WindowStyle Hidden -PassThru
for ($i = 0; $i -lt 40; $i++) {
  try { Invoke-WebRequest "http://localhost:5051/?key=$token" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
  catch { Start-Sleep -Milliseconds 500 }
}

# --- start cloudflared and capture the generated URL -------------------------
Write-Host "Opening Cloudflare tunnel ..." -ForegroundColor Cyan
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
    Set-Clipboard -Value $url
    Set-Content -Path (Join-Path $here 'deribit-dashboard-url.txt') -Value $url -Encoding UTF8
    # Scannable QR for the phone (auto-installs the tiny `segno` lib if missing)
    $qrPath = Join-Path $here 'deribit-dashboard-qr.png'
    $qrOk = $false
    try {
      python -c "import segno" 2>$null
      if ($LASTEXITCODE -ne 0) { python -m pip install --quiet segno 2>$null }
      python -c "import segno; segno.make(r'$url', error='m').save(r'$qrPath', scale=10, border=3)" 2>$null
      if ($LASTEXITCODE -eq 0) { $qrOk = $true }
    } catch { }
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  SHARE THIS URL (read-only, copied to clipboard):" -ForegroundColor Green
    Write-Host "  $url" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  Also saved to dashboard\deribit-dashboard-url.txt" -ForegroundColor DarkGray
    if ($qrOk) { Write-Host "  QR code saved to dashboard\deribit-dashboard-qr.png (scan with phone)" -ForegroundColor DarkGray }
    Write-Host "  Keep this window open. Press Ctrl+C to stop sharing." -ForegroundColor DarkGray
    Write-Host ""
  } else {
    Write-Host "Could not detect the tunnel URL. See $log" -ForegroundColor Red
  }
  Wait-Process -Id $cf.Id
}
finally {
  Write-Host "Stopping tunnel + view-only server ..." -ForegroundColor Cyan
  Stop-Process -Id $cf.Id  -Force -ErrorAction SilentlyContinue
  Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
}
