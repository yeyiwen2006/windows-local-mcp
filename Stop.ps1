$ErrorActionPreference = 'Stop'
$private = Join-Path $PSScriptRoot '.local'
New-Item -ItemType Directory -Path $private -Force | Out-Null
Set-Content -LiteralPath (Join-Path $private 'manual-stop') -Value ([DateTimeOffset]::UtcNow.ToString('O')) -Encoding UTF8
try { & (Join-Path $PSScriptRoot 'Pause.ps1') }
catch { Write-Warning 'Pause marker failed; continuing to stop the verified tunnel process.' }
$pidPath = Join-Path $private 'running.json'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host 'No tunnel process recorded.'; return }
$record = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
$process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
if (-not $process) { Write-Host 'Tunnel is already stopped.'; return }
if ($process.StartTime.ToUniversalTime().Ticks -ne $record.start_ticks -or $process.Path -ne $record.executable) { throw 'Recorded process identity changed. Refusing to stop a different process.' }
& taskkill.exe /PID $process.Id /T /F
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the tunnel process tree.' }
Write-Host 'Tunnel and its local MCP child stopped. Automatic supervision will stay idle until the next Windows logon or a manual start. Use Resume.ps1 before the next session.'
