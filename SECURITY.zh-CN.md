# 安全说明

[English](SECURITY.en.md) · **简体中文**

Windows Local MCP 可以读取和修改当前 Windows 用户有权访问的文件，也可以操作交互式桌面，因此应当把它视为高信任级别的本机工具。

## 报告安全问题

如果 GitHub 仓库启用了 Private vulnerability reporting，请优先通过该渠道报告漏洞。

不要在公开 Issue 中提交 API key、Tunnel ID、其他凭据、本地文件正文、私人截图、审计记录、Tunnel 日志，或其他能够识别个人、账号或本机环境的敏感信息。

## 密钥和本机状态

不要提交 .local/、.env、runtime API keys、Tunnel 凭据、备份、审计记录、Tunnel 日志或虚拟环境。仓库的 .gitignore 已排除常见本机状态，但每次 push 前仍应检查实际 diff。

## 桌面控制边界

从 0.1.3 开始，桌面输入必须通过 desktop_focus_window 显式锁定目标窗口，并核对 PID、进程创建时间、可执行文件路径和 root-owner 窗口链。截图不会自动改变输入目标。

这个机制用于降低用户手动切换窗口后误输入到其他程序的风险，但它不是完整的操作系统沙箱。任何获得当前 Windows 用户权限的普通程序仍可能接触该用户能够访问的数据。

## 本机暂停

Ctrl + Alt + F11、Pause.ps1 和 service_pause 可以停止后续受控动作。恢复被设计为本机操作，以避免远程调用自行解除暂停。

已经发给 Windows 的输入或已经完成的磁盘写入无法撤销，因此敏感操作仍应遵循最小权限和人工确认原则。
