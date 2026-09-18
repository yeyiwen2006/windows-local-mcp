$ErrorActionPreference = 'Stop'
$taskName = 'Windows Local MCP Tunnel'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host 'Automatic startup is not installed.'
    return
}
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host 'Automatic startup removed. The currently running tunnel, if any, is unchanged.'
