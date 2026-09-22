# Windows Local MCP

[简体中文](README.zh-CN.md) · [English](README.en.md)

**中文：** 让 ChatGPT 在 Chat 模式中通过 MCP 读取和写入本机文件、查看并操作 Windows 桌面，并在本机明确授权后直接运行 Git、构建、测试等命令，无需依赖终端窗口焦点。命令以当前 Windows 用户权限运行，不自动提权，也不是操作系统沙箱。

**English:** Give ChatGPT in Chat mode MCP-based access to local file reads/writes and Windows desktop control, plus opt-in direct execution of Git, build, test, and other local commands without terminal focus. Commands run with the current Windows user's permissions, do not elevate automatically, and are not an OS sandbox.

- 中文完整说明：[README.zh-CN.md](README.zh-CN.md)
- Full English documentation: [README.en.md](README.en.md)
- 安全说明 / Security: [SECURITY.zh-CN.md](SECURITY.zh-CN.md) · [SECURITY.en.md](SECURITY.en.md)
- 验证记录 / Validation: [VALIDATION.zh-CN.md](VALIDATION.zh-CN.md) · [VALIDATION.en.md](VALIDATION.en.md)
- License: MIT

## 权限与风险 / Permissions and risk

**中文：** 这是高权限本机工具，不是操作系统沙箱。启用后，模型可在当前 Windows 用户本来拥有的权限范围内读取/修改文件，并在获得桌面工具权限后向普通应用发送鼠标和键盘输入。目标锁、一次性截图编号、暂停、备份和审计只能降低误操作风险，不能把模型变成低权限进程。处理密码管理器、支付、敏感账号或重要生产数据时应暂停服务；不要把 Tunnel 凭据、私密截图或本机状态提交到仓库。

**English:** This is a high-privilege local tool, not an operating-system sandbox. A connected model can read or modify files within the current Windows user's permissions and can send mouse/keyboard input to ordinary applications through the desktop tools. Target locking, one-use screenshot IDs, pause controls, backups, and audit logs reduce mistakes but do not create a low-privilege security boundary. Pause the service around password managers, payments, sensitive accounts, or important production data, and never commit Tunnel credentials, private screenshots, or local state.

See [SECURITY.zh-CN.md](SECURITY.zh-CN.md) / [SECURITY.en.md](SECURITY.en.md) for details.

## Local command execution / 本机命令执行

Version 0.2.0 adds opt-in `command_start`, `command_poll`, and `command_cancel` tools. They do not require desktop focus and do not elevate privileges. Commands have current-user access, not sandbox isolation. Enable only through local operator controls; see [command tools and limits](docs/commands.md).

0.2.0 新增默认禁用的本机命令工具。开启后可直接运行 Git、构建和测试，不必保持终端前台；不自动提权，也不是系统沙箱。只能在本机确认开启，运行中的 MCP 不得自行修改许可或安装目录。详见[使用方法、限制与升级要求](docs/commands.md)。
