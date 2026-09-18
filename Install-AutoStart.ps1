$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$taskName = 'Windows Local MCP Tunnel'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$powerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$autoStartScript = Join-Path $PSScriptRoot 'AutoStart.ps1'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -AtLogon' -f $autoStartScript

$action = New-ScheduledTaskAction -Execute $powerShellExe -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Keeps the current user Windows Local MCP Secure MCP Tunnel available after sign-in.'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 200
        $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    } while ($existing -and $existing.State -eq 'Running' -and (Get-Date) -lt $deadline)
    if ($existing -and $existing.State -eq 'Running') { throw 'The previous automatic supervisor did not stop in time.' }
}
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
$deadline = (Get-Date).AddSeconds(10)
do {
    Start-Sleep -Milliseconds 200
    $registered = Get-ScheduledTask -TaskName $taskName
} while ($registered.State -ne 'Running' -and (Get-Date) -lt $deadline)
if ($registered.State -ne 'Running') { throw 'The automatic supervisor did not enter the running state.' }
Write-Host ('Automatic startup enabled for {0}. Scheduled task state: {1}' -f $identity, $registered.State)
Write-Host 'The task runs only while this user is signed in and stores no API key in Task Scheduler.'
