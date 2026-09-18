$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$previousState = $env:WINDOWS_LOCAL_MCP_STATE
try {
    $env:WINDOWS_LOCAL_MCP_STATE = Join-Path $PSScriptRoot '.local'
    & '.\.venv\Scripts\python.exe' -m windows_local_mcp.control status
} finally { $env:WINDOWS_LOCAL_MCP_STATE = $previousState }
$pidPath = Join-Path $PSScriptRoot '.local\running.json'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host 'Tunnel has not been started.'; return }
$record = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
$process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
if (-not $process -or $process.StartTime.ToUniversalTime().Ticks -ne $record.start_ticks) { Write-Host 'Tunnel is stopped.'; return }
if (-not (Test-Path -LiteralPath $record.health_file)) { Write-Host 'Tunnel is starting; health address is not ready.'; return }
$address = (Get-Content -LiteralPath $record.health_file -Raw -Encoding UTF8).Trim()
$uri = [uri]$address
if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1' -or $uri.UserInfo) { throw 'Unexpected health address; refusing to contact it.' }
try {
    $response = Invoke-WebRequest -Uri ($uri.GetLeftPart([System.UriPartial]::Authority) + '/readyz') -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0
    Write-Host ('Tunnel readiness HTTP ' + $response.StatusCode)
} catch { Write-Host 'Tunnel is not ready. Check account permissions, network and the local tunnel log.' }
Write-Host 'Verify service_status from ChatGPT to check the MCP process and emergency hotkey.'
