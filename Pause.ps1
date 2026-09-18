$ErrorActionPreference = 'Stop'
$previousState = $env:WINDOWS_LOCAL_MCP_STATE
try {
    $env:WINDOWS_LOCAL_MCP_STATE = Join-Path $PSScriptRoot '.local'
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m windows_local_mcp.control pause
    if ($LASTEXITCODE -ne 0) { throw 'Pause failed. Run Stop.ps1.' }
} finally { $env:WINDOWS_LOCAL_MCP_STATE = $previousState }
