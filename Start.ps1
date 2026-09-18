param([switch]$Supervised)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$private = Join-Path $PSScriptRoot '.local'
$manualStopPath = Join-Path $private 'manual-stop'
if ($Supervised -and (Test-Path -LiteralPath $manualStopPath)) { return }
if (-not $Supervised) { Remove-Item -LiteralPath $manualStopPath -Force -ErrorAction SilentlyContinue }
$configPath = Join-Path $private 'connection.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Run Configure.ps1 first. No connection credentials have been saved.' }
$pidPath = Join-Path $private 'running.json'
if (Test-Path -LiteralPath $pidPath) {
    $running = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $previous = Get-Process -Id $running.pid -ErrorAction SilentlyContinue
    if ($previous -and $previous.StartTime.ToUniversalTime().Ticks -eq $running.start_ticks) { throw 'Already running. Use Check.ps1 or Stop.ps1.' }
}
$candidates = @(Get-ChildItem -LiteralPath (Join-Path $private 'tools') -Filter tunnel-client.exe -Recurse | Sort-Object FullName -Descending)
if ($candidates.Count -eq 0) { throw 'Run Setup.ps1 to install the official tunnel client.' }
$tunnelExe = $candidates[0].FullName
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$healthFile = Join-Path $private ('health-' + [guid]::NewGuid().ToString('N') + '.url')
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$secure = ConvertTo-SecureString -String $config.protected_key
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$names = @('CONTROL_PLANE_API_KEY','CONTROL_PLANE_TUNNEL_ID','MCP_COMMAND','PYTHONUTF8','PYTHONIOENCODING','WINDOWS_LOCAL_MCP_STATE')
$old = @{}
foreach ($name in $names) { $old[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $env:CONTROL_PLANE_TUNNEL_ID = $config.tunnel_id
    $env:MCP_COMMAND = '"{0}" -m windows_local_mcp' -f $pythonExe.Replace('\','/')
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:WINDOWS_LOCAL_MCP_STATE = $private
    $arguments = @('run', '--health.listen-addr', '127.0.0.1:0', '--health.url-file', ('"' + $healthFile + '"'), '--mcp.stdio-send-initialized-notification')
    $process = Start-Process -FilePath $tunnelExe -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $private 'tunnel.stdout.log') -RedirectStandardError (Join-Path $private 'tunnel.stderr.log')
    @{ pid = $process.Id; start_ticks = $process.StartTime.ToUniversalTime().Ticks; executable = $tunnelExe; health_file = $healthFile } | ConvertTo-Json | Set-Content -LiteralPath $pidPath -Encoding UTF8
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $secure.Dispose()
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $old[$name], 'Process') }
}
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $process.Refresh()
    if ($process.HasExited) { throw 'Tunnel client exited. Check .local\tunnel.stderr.log locally.' }
    if (Test-Path -LiteralPath $healthFile) { break }
    Start-Sleep -Milliseconds 250
}
Write-Host 'Tunnel client started in the background. Ctrl+Alt+F11 pauses file and desktop access.'
& (Join-Path $PSScriptRoot 'Check.ps1')
