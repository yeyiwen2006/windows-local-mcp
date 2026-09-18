# ChatGPT Windows Local MCP

**English** · [简体中文](README.zh-CN.md)

Give ChatGPT in Chat mode MCP-based access to local files, file writes, screen viewing, and Windows desktop control, helping ease concerns about running short on Codex quota while operating within OpenAI's usage policies. By default, the service can access local disk locations that the current Windows user can already access. It does not require a separate directory allowlist and does not automatically gain administrator privileges.

The local service speaks standard MCP over stdio and connects to ChatGPT through OpenAI Secure MCP Tunnel. The file and desktop tools do not expose their own HTTP listener. The official Tunnel client only exposes a loopback health endpoint with an automatically assigned port.

## Project status

This repository contains the source code, Windows startup and safety-control scripts, and automated tests. Virtual environments, Tunnel runtime state, credentials, backups, and audit logs are excluded from version control. See [VALIDATION.en.md](VALIDATION.en.md) for validation results.

First-time setup requires a real Tunnel ID and runtime API key from your account. Enter secrets only through the local control menu. Do not commit them to GitHub or paste them into chat. Each computer and account should be connected and validated separately.

Secure MCP Tunnel is used to connect local, private, or firewalled MCP servers to supported OpenAI products. This GitHub repository only distributes the source code. Available ChatGPT clients, workspace features, and model/tool combinations may change over time; follow the current OpenAI documentation and product UI.

## Connect to ChatGPT

1. Open [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels), create a Tunnel, and associate it with your ChatGPT workspace. Creating a Tunnel requires organization-level Tunnels Read and Manage permissions; running it requires Read and Use.
2. Prepare a runtime API key for that organization. Do not use an administrator key.
3. Double-click Control.cmd, choose 1, and enter the Tunnel ID and runtime key locally. The key is entered without echo and stored using Windows DPAPI, bound to the current Windows user on the current computer.
4. Choose 2 to start and 3 to check status. Tunnel readiness HTTP 200 means the Tunnel is ready. If the service was paused, choose 5 to resume it.
5. Enable developer mode in ChatGPT and create a custom app using a Tunnel connection according to the current product UI. The local service does not implement OAuth itself; remote access is constrained by Secure MCP Tunnel account and workspace permissions.
6. In a ChatGPT client that supports plugins/tools, open the same workspace and add the app. If the current client or model does not expose the tool entry point, the local service cannot enable it on the client's behalf.
7. For the first connection, call service_status, then test reading a dedicated file, creating a test file, and taking a desktop_screenshot before using the service for real work.

The service does not need to call an OpenAI model API separately. The runtime key is used for the Secure MCP Tunnel connection. Eligibility, permissions, and billing follow the current OpenAI platform rules.

## Daily controls

| Menu | Action |
| --- | --- |
| 1 | Configure Tunnel ID and runtime key |
| 2 | Start the Tunnel and local MCP in the background |
| 3 | Check pause state, processes, and Tunnel health |
| 4 | Pause future file and desktop actions |
| 5 | Resume actions locally |
| 6 | Pause and stop the Tunnel process tree |
| 7 | Install or repair dependencies |
| 8 | Show documentation |
| 9 | Enable auto-connect after sign-in and restart the Tunnel after unexpected exits |
| 10 | Remove auto-connect without interrupting the currently running connection |

Press **Ctrl + Alt + F11** for an emergency pause. You can also run Pause.ps1 or ask the model to call service_pause. Resume is intentionally local-only through Resume.ps1 or the control menu.

Pause checks take effect at action checkpoints. Input already sent to Windows and file writes already completed cannot be undone. Backup copying, text entry, and dragging re-check the pause state while they run.

Auto-connect installs a scheduled task for the current user. After Windows sign-in, it starts the connection hidden and periodically verifies that the Tunnel process still matches the recorded process identity. The scheduled task does not store the Tunnel ID or API key. It runs only in the signed-in interactive user session, does not install a Windows service, and does not elevate privileges.

## File and desktop tools

| Purpose | Tools |
| --- | --- |
| File metadata and directories | file_info, list_directory |
| Text and binary reads | read_text_file, read_binary_file |
| Create, replace, mkdir, move, recycle | write_file, create_directory, move_path, recycle_path |
| Displays, windows, screenshots | desktop_monitors, desktop_windows, desktop_screenshot |
| Focus a window and lock the input target | desktop_focus_window |
| Mouse | desktop_click, desktop_move, desktop_drag, desktop_scroll |
| Keyboard and Unicode text | desktop_keypress, desktop_type_text |
| Status and pause | service_status, service_pause |

Text defaults to UTF-8 and can also be read explicitly as UTF-16 or GB18030. Binary reads use base64 chunks up to 1 MiB per call. A single write is limited to 8 MiB, and a text-entry call is limited to 4,000 characters.

Replacing an existing file requires overwrite=true. The old contents are backed up before an atomic replacement is attempted, and the implementation preserves the original DACL where supported. Pass the modified_ns returned by file_info to reject a replacement if the file changed after it was read.

To reduce irreversible damage, the service refuses direct overwrite of files with alternate data streams or special encrypted, compressed, sparse, read-only, hidden, or system attributes. Mutating links and junctions is also rejected; specify the real target path explicitly. Deletion goes to the Recycle Bin and never falls back to permanent deletion.

The MCP file tools cannot modify the service's own source tree. Credentials, backups, and audit state under .local are also hidden from the model.

## Desktop target lock

Starting with 0.1.3, desktop input uses an explicit target lock:

1. Find the intended window with desktop_windows.
2. Call desktop_focus_window to lock that target explicitly.
3. Later screenshots never retarget desktop input.
4. If you manually switch to WeChat, a browser, or another application, ChatGPT may still observe the screen, but mouse, wheel, and keyboard input is blocked.
5. Only another explicit desktop_focus_window call can change the target.

The target identity validates the PID, process creation time, executable path, and the target window's root-owner chain. This allows modal dialogs owned by the target application while rejecting an unrelated top-level window, even when it belongs to the same process.

Every desktop input must still include a fresh one-use observation_id from desktop_screenshot. It expires after 60 seconds. Pause state, foreground focus, and target identity are re-checked before and during input.

If a modifier key or mouse button is still held, the service waits for up to one second and requires 100 ms of stable release. On timeout it reports the specific held input and does not force-release it.

## Backups, audit, and security boundary

Overwrite backups are stored under .local/backups. Audit records are stored under .local/audit and contain timestamps, tool names, paths, lengths, and success/failure status, but not file bodies, screenshot pixels, or typed text. Tunnel logs are stored locally in .local/tunnel.stdout.log and .local/tunnel.stderr.log.

Full desktop access means the model can interact with data available to ordinary applications running as the current Windows user. File guards, local pause, target locking, and DPAPI are not a complete operating-system sandbox; they are safeguards for authentication, error reduction, and recovery.

See [SECURITY.en.md](SECURITY.en.md) for sensitive-data and vulnerability-reporting guidance.

## Installation and development

Requires Windows 10 version 1703 or later, or Windows 11; Python 3.13 or later; and outbound HTTPS access to OpenAI.

For a first installation or a move to another computer:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
~~~

The execution-policy flag applies only to that PowerShell process and does not change the global policy. A standard MCP client can also run .venv/Scripts/python.exe -m windows_local_mcp directly. That stdio entry point has no independent identity layer, so it should only be invoked by a trusted local client or the official Tunnel process.

The Python distribution name remains windows-local-mcp even though the GitHub repository is named chatgpt-windows-local-mcp. Keeping the package name stable avoids breaking existing installs, commands, and upgrade paths.

## Official references

- [ChatGPT developer mode](https://developers.openai.com/api/docs/guides/developer-mode)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [ChatGPT plugins](https://learn.chatgpt.com/docs/plugins)
- [Official Tunnel client releases](https://github.com/openai/tunnel-client/releases/latest)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Windows SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

## License

MIT License. See [LICENSE](LICENSE).
