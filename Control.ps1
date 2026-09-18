$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
while ($true) {
    Write-Host ''
    Write-Host 'Windows Local MCP'
    Write-Host '1  Configure Tunnel ID and runtime key'
    Write-Host '2  Start connection'
    Write-Host '3  Check connection'
    Write-Host '4  Pause file and desktop tools'
    Write-Host '5  Resume file and desktop tools'
    Write-Host '6  Stop connection'
    Write-Host '7  Install / repair local dependencies'
    Write-Host '8  Read Chinese guide'
    Write-Host '9  Enable automatic connection after Windows sign-in'
    Write-Host '10 Disable automatic connection'
    Write-Host '0  Exit this menu (connection stays as it is)'
    $selection = Read-Host 'Select'
    $scriptName = switch ($selection) {
        '1' { 'Configure.ps1' }
        '2' { 'Start.ps1' }
        '3' { 'Check.ps1' }
        '4' { 'Pause.ps1' }
        '5' { 'Resume.ps1' }
        '6' { 'Stop.ps1' }
        '7' { 'Setup.ps1' }
        '9' { 'Install-AutoStart.ps1' }
        '10' { 'Remove-AutoStart.ps1' }
        default { $null }
    }
    if ($selection -eq '0') { break }
    if ($selection -eq '8') { Get-Content -LiteralPath 'README.md' -Encoding UTF8; continue }
    if ($scriptName) {
        try { & (Join-Path $PSScriptRoot $scriptName) }
        catch { Write-Host $_.Exception.Message -ForegroundColor Red }
    }
}
