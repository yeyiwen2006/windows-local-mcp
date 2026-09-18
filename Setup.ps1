param([string]$Python = 'python', [switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
& $Python -c "import sys; assert sys.version_info >= (3,13), 'Python 3.13 or newer is required'"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.13 or newer first.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.\.venv\Scripts\python.exe' -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Server installation failed.' }
New-Item -ItemType Directory -Force -Path '.local' | Out-Null
# Reuse the server's dedicated-directory validation and private Windows ACL.
$previousState = $env:WINDOWS_LOCAL_MCP_STATE
try {
    $env:WINDOWS_LOCAL_MCP_STATE = Join-Path $PSScriptRoot '.local'
    & '.\.venv\Scripts\python.exe' -c 'from windows_local_mcp.guard import Guard; Guard()'
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize the private service directory.' }
} finally { $env:WINDOWS_LOCAL_MCP_STATE = $previousState }
if (-not $SkipDownload) {
    $existing = @(Get-ChildItem -LiteralPath '.local' -Filter tunnel-client.exe -Recurse -ErrorAction SilentlyContinue)
    if ($existing.Count -eq 0) {
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/openai/tunnel-client/releases/latest' -Headers @{'User-Agent'='windows-local-mcp'}
        $architecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
        $asset = @($release.assets | Where-Object { $_.name -match "^tunnel-client-v.*-windows-$architecture\.zip$" })
        if ($asset.Count -ne 1) { throw 'Official Windows release asset was not found.' }
        if ($asset[0].browser_download_url -notlike 'https://github.com/openai/tunnel-client/releases/download/*') { throw 'Unexpected download location.' }
        $destination = Join-Path '.local\tools' $release.tag_name
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        $archive = Join-Path $destination 'official-release.zip'
        Invoke-WebRequest -Uri $asset[0].browser_download_url -OutFile $archive -UseBasicParsing
        Expand-Archive -LiteralPath $archive -DestinationPath $destination
    }
}
Write-Host 'Installed. Run Configure.ps1 to enter your Tunnel ID and runtime key locally.'
