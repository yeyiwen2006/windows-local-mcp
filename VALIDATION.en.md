# Validation Notes

**English** · [简体中文](VALIDATION.zh-CN.md)

This document records the main validation results for Windows Local MCP. It is not a security certification and does not claim coverage of every Windows environment.

## 0.3.0 file editing and search (2026-09-26)

The isolated Windows 11 / Python 3.13.5 suite recorded **119 passed, 32 subtests passed, 1 skipped**. The skipped case requires local symbolic-link creation privileges.

The same source passed [GitHub Actions Windows regression](https://github.com/yeyiwen2006/windows-local-mcp/actions/runs/36217317468) with **120 passed, 32 subtests passed, no skips**, including the symbolic-link case.

New cases cover unique exact matching and overlapping ambiguity, Chinese/emoji, UTF-8 BOM, UTF-16 byte order, GB18030, newlines, version conflicts, backup failure, external mutation, pause, protected paths, search result/byte/entry/time limits, and content-free audit records. A real MCP stdio workflow covers discovery, search, read, edit, backup, stale-version rejection and pause; its macOS entry point runs only on a native runner.

Independent static code review completed. Tests use separate checkouts and synthetic temporary files and do not upgrade a running installation. See [file tool contracts](docs/file-tools.md).

The 0.2.0 command results are retained in [command validation](docs/command-validation.md).

## 0.1.3: desktop target lock

On September 18, 2026, the project was updated to address a failure mode in which desktop input could follow the user to a newly foregrounded application after a manual window switch.

Key changes:

- desktop_focus_window now explicitly locks the desktop input target;
- later desktop_screenshot calls do not retarget input;
- input validation checks PID, process creation time, executable path, and the root-owner window chain;
- modal dialogs owned by the target application can still receive input;
- an unrelated top-level window in the same process does not automatically become the input target;
- after the user switches to another application, screenshots may still be taken, but mouse, wheel, and keyboard input is rejected unless desktop_focus_window is explicitly called again.

Regression results on the open-source worktree:

- Python syntax checks passed;
- 44 tests passed;
- 32 parameterized subtests also passed;
- the automated tests did not send real keyboard or mouse input to ordinary desktop applications.

## 0.1.2: auto-connect after sign-in

On September 18, 2026, auto-connect for the current Windows user was validated.

The scheduled task runs without elevation and does not store the Tunnel ID or API key in task arguments. The supervisor verifies the Tunnel process using its PID, process start time, and executable path. During testing, terminating the Tunnel process caused the supervisor to recreate the connection; using the normal stop flow created a manual-stop marker that prevented immediate restart.

The 0.1.2 Python regression suite reported 38 passing tests plus 32 parameterized subtests.

## 0.1.1: held-input handling

Earlier testing found that an instantaneous modifier-key or mouse-button check could be too sensitive when user input overlapped with automation.

Version 0.1.1 changed the behavior to:

- wait for up to one second;
- require 100 ms of continuously released modifier keys and mouse buttons;
- continue checking pause state and focus while waiting;
- report the specific held input on timeout;
- never force-release a user's input state.

These behaviors are covered by simulated tests.

## Core MCP and file behavior

Validation has covered:

- MCP stdio initialization and tool discovery;
- Chinese text and emoji reads/writes;
- backups before replacement;
- concurrent modification detection;
- invalid-path and protected-directory rejection;
- protections around alternate data streams, special file attributes, and DACL handling;
- pause behavior;
- audit records that exclude file bodies;
- display, window, and screenshot metadata;
- the Ctrl + Alt + F11 emergency pause hotkey;
- baseline PowerShell syntax checks;
- UTF-8 Chinese documentation.

## Test boundaries

Automated keyboard, mouse, drag, scroll, and text-entry tests primarily use simulated objects and do not operate ordinary desktop applications. Real desktop behavior still depends on Windows foreground focus, UIPI, lock state, UAC secure desktop, monitor configuration, and third-party software.

Recycle Bin tests focus on verifying that failures never fall back to permanent deletion rather than performing broad real-world deletion tests.

Credentials are not committed to the repository. .local, virtual environments, backups, audit data, and Tunnel logs are excluded.

## Current version

Source version: 0.3.0

See [SECURITY.en.md](SECURITY.en.md) for security guidance.
