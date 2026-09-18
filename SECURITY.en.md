# Security Policy

**English** · [简体中文](SECURITY.zh-CN.md)

ChatGPT Windows Local MCP can read and modify files available to the current Windows user and can operate the interactive desktop. Treat it as a high-trust local tool.

## Reporting a vulnerability

Use GitHub private vulnerability reporting when it is enabled for the repository.

Do not open a public issue containing API keys, Tunnel IDs, other credentials, local file contents, private screenshots, audit records, Tunnel logs, or other sensitive information that identifies a person, account, or local environment.

## Secrets and local state

Do not commit .local/, .env, runtime API keys, Tunnel credentials, backups, audit records, Tunnel logs, or virtual environments. The repository's .gitignore excludes the normal local-state paths, but contributors should still inspect the actual diff before every push.

## Desktop-control boundary

Starting with 0.1.3, desktop input must be explicitly locked with desktop_focus_window. The service verifies the PID, process creation time, executable path, and root-owner window chain. Screenshots do not automatically retarget input.

This reduces the risk of typing into another program after the user manually switches windows, but it is not a complete operating-system sandbox. Ordinary applications running as the same Windows user can still access data that user is allowed to access.

## Local pause

Ctrl + Alt + F11, Pause.ps1, and service_pause can stop future controlled actions. Resume is intentionally local-only so that a remote caller cannot simply undo a local emergency stop.

Input already sent to Windows and disk writes already completed cannot be rolled back, so sensitive actions should still follow least-privilege and explicit-confirmation practices.
