# Windows Local MCP

[简体中文](README.zh-CN.md) · [English](README.en.md)

**中文：** 让 ChatGPT 在 Chat 模式中也可以通过 MCP 读取本机文件、写入文件、查看屏幕并操作 Windows 桌面，从而在完全符合 OpenAI 使用规范的前提下有效缓解 Codex 额度不足焦虑。

**English:** Give ChatGPT in Chat mode MCP-based access to local files, file writes, screen viewing, and Windows desktop control, helping ease concerns about running short on Codex quota while operating within OpenAI's usage policies.

- 中文完整说明：[README.zh-CN.md](README.zh-CN.md)
- Full English documentation: [README.en.md](README.en.md)
- 安全说明 / Security: [SECURITY.zh-CN.md](SECURITY.zh-CN.md) · [SECURITY.en.md](SECURITY.en.md)
- 验证记录 / Validation: [VALIDATION.zh-CN.md](VALIDATION.zh-CN.md) · [VALIDATION.en.md](VALIDATION.en.md)
- License: MIT

## 权限与风险 / Permissions and risk

**中文：** 这是高权限本机工具，不是操作系统沙箱。启用后，模型可在当前 Windows 用户本来拥有的权限范围内读取/修改文件，并在获得桌面工具权限后向普通应用发送鼠标和键盘输入。目标锁、一次性截图编号、暂停、备份和审计只能降低误操作风险，不能把模型变成低权限进程。处理密码管理器、支付、敏感账号或重要生产数据时应暂停服务；不要把 Tunnel 凭据、私密截图或本机状态提交到仓库。

**English:** This is a high-privilege local tool, not an operating-system sandbox. A connected model can read or modify files within the current Windows user's permissions and can send mouse/keyboard input to ordinary applications through the desktop tools. Target locking, one-use screenshot IDs, pause controls, backups, and audit logs reduce mistakes but do not create a low-privilege security boundary. Pause the service around password managers, payments, sensitive accounts, or important production data, and never commit Tunnel credentials, private screenshots, or local state.

See [SECURITY.zh-CN.md](SECURITY.zh-CN.md) / [SECURITY.en.md](SECURITY.en.md) for details.
