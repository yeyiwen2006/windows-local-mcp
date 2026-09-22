param([switch]$ConfirmEnable, [switch]$Disable)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run Setup.ps1 first.' }
if ($Disable) {
    & $python -B -m windows_local_mcp.control commands-disable
} else {
    if (!$ConfirmEnable) {
        Write-Host 'Commands can read, change, delete and upload data with your Windows user permissions.'
        Write-Host 'This is not an OS sandbox. Desktop focus checks do not apply to commands.'
        if ((Read-Host 'Type ENABLE to allow local commands') -cne 'ENABLE') { throw 'Not enabled.' }
    }
    & $python -B -m windows_local_mcp.control commands-enable --acknowledge-current-user-access
}
if ($LASTEXITCODE -ne 0) { throw 'Local command permission was not updated.' }
