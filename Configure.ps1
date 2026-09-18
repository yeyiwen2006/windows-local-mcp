$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Run Setup.ps1 first.' }
$previousState = $env:WINDOWS_LOCAL_MCP_STATE
try {
    $env:WINDOWS_LOCAL_MCP_STATE = Join-Path $PSScriptRoot '.local'
    & '.\.venv\Scripts\python.exe' -c 'from windows_local_mcp.guard import Guard; Guard()'
    if ($LASTEXITCODE -ne 0) { throw 'Could not protect the credential directory.' }
} finally { $env:WINDOWS_LOCAL_MCP_STATE = $previousState }
Write-Host 'Create a tunnel at https://platform.openai.com/settings/organization/tunnels'
Write-Host 'Associate it with your ChatGPT workspace. Do not paste your API key into ChatGPT.'
$tunnelId = (Read-Host 'Tunnel ID').Trim()
if ($tunnelId -notmatch '^tunnel_[a-zA-Z0-9_-]+$') { throw 'Invalid Tunnel ID.' }
$secret = Read-Host 'Runtime API key (hidden input)' -AsSecureString
if ($secret.Length -eq 0) { throw 'An empty key cannot be saved.' }
New-Item -ItemType Directory -Force -Path '.local' | Out-Null
# ConvertFrom-SecureString uses Windows DPAPI, tied to this user on this machine.
$config = @{ tunnel_id = $tunnelId; protected_key = (ConvertFrom-SecureString -SecureString $secret) }
$config | ConvertTo-Json | Set-Content -LiteralPath '.local\connection.json' -Encoding UTF8
$secret.Dispose()
Write-Host 'Saved with Windows account protection. Run Start.ps1 when you want ChatGPT access.'
