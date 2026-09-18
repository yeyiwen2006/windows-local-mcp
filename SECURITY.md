# Security Policy

Windows Local MCP can read and modify files available to the current Windows user and can operate the interactive desktop. Treat it as a high-trust local tool.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting when available. Do not open a public issue containing API keys, Tunnel IDs, local file contents, screenshots, audit records, or other sensitive information.

## Secrets and local state

Do not commit `.local/`, `.env`, runtime API keys, Tunnel credentials, backups, audit records, or tunnel logs. The repository's `.gitignore` excludes the normal local-state paths, but review every commit before pushing.
