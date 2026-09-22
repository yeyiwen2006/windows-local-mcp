# Command tool validation (0.2.0)

Validation date: 2026-09-22. This record covers an independent development checkout, not activation of a running user installation.

## Executed locally

Windows 11 build 26200, Python 3.13.5, pytest 9.1.1, pywin32 312. The full suite completed with **78 passed, 32 subtests passed, zero failures and zero skips**. Tests used dedicated new temporary directories and synthetic files. No production project data or installed service state was modified by these tests.

The tests start real Windows processes and a separate MCP stdio server. They cover:

- Git and PowerShell execution without a desktop window, Unicode arguments and working directories, separate stdout/stderr, actual nonzero exit codes, closed stdin, and bounded output with continued pipe draining.
- Timeouts, explicit cancellation, pause, local permission revocation, orderly shutdown, abrupt host death, and cleanup of ordinary child/grandchild processes. A process whose creation consumed its entire timeout is killed before it can run.
- Fail-closed process creation: job assignment failure, watchdog/reader startup failure, resume failure, malformed executables, and restoration of the calling thread's error mode after a native launch error.
- Disabled-by-default permission, required local acknowledgement, protected working directories, concurrency and history limits, audit failures, omission of command contents from audit, and omission of service-specific credential environment variables from children.
- Real MCP discovery, start/poll/cancel/pause calls, plus all existing file, desktop-target, screenshot, input-release and backup regressions.

The malformed executable regression previously exposed a Windows dialog that could stall headless startup. The implementation now rejects obviously invalid PE images before native launch and temporarily suppresses system error dialogs in the launching thread, restoring its previous mode afterwards. Anonymous Job Object creation uses the native NULL-name API because the tested pywin32 version rejects `None` as a name.

## Boundaries

This is not a sandbox or a claim that every Windows executable runs unattended. Commands retain current-user access. External service/WMI/scheduled-task process creation is outside ordinary Job Object descendant tracking and must not be used to detach work.

A passing source test suite does not establish that an existing ChatGPT connection has reloaded the tools. Installation, local enablement, refreshed tool discovery and a command round trip through that live connection remain separate deployment checks. Raw local logs and temporary data are not committed. GitHub Actions provides a separate Windows run for each published change.
