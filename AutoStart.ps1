param([switch]$AtLogon)

$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot
$private = Join-Path $PSScriptRoot '.local'
$manualStopPath = Join-Path $private 'manual-stop'
$pidPath = Join-Path $private 'running.json'
$logPath = Join-Path $private 'autostart.log'
New-Item -ItemType Directory -Path $private -Force | Out-Null

function Write-AutoStartLog([string]$Message) {
    if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -gt 1MB) {
        Move-Item -LiteralPath $logPath -Destination ($logPath + '.previous') -Force
    }
    Add-Content -LiteralPath $logPath -Value ('{0} {1}' -f [DateTimeOffset]::UtcNow.ToString('O'), $Message) -Encoding UTF8
}

function Test-TunnelProcess {
    if (-not (Test-Path -LiteralPath $pidPath)) { return $false }
    try {
        $record = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $process = Get-Process -Id $record.pid -ErrorAction Stop
        return ($process.StartTime.ToUniversalTime().Ticks -eq $record.start_ticks -and $process.Path -eq $record.executable)
    } catch {
        return $false
    }
}

if ($AtLogon) {
    Remove-Item -LiteralPath $manualStopPath -Force -ErrorAction SilentlyContinue
}

Write-AutoStartLog 'Automatic tunnel supervision started.'
while ($true) {
    if (-not (Test-Path -LiteralPath $manualStopPath) -and -not (Test-TunnelProcess)) {
        try {
            $startOutput = @(& (Join-Path $PSScriptRoot 'Start.ps1') -Supervised 2>&1)
            foreach ($line in $startOutput) { Write-AutoStartLog ([string]$line) }
        } catch {
            Write-AutoStartLog ('Tunnel start failed: ' + $_.Exception.Message)
        }
    }
    Start-Sleep -Seconds 15
}
