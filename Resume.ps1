$ErrorActionPreference = 'Stop'
$previousState = $env:WINDOWS_LOCAL_MCP_STATE
try {
    $env:WINDOWS_LOCAL_MCP_STATE = Join-Path $PSScriptRoot '.local'
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m windows_local_mcp.control resume
    if ($LASTEXITCODE -ne 0) { throw 'Resume failed.' }
} finally { $env:WINDOWS_LOCAL_MCP_STATE = $previousState }
