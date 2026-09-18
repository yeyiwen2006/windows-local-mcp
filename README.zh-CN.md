# Windows Local MCP

[English](README.en.md) · **简体中文**

让 ChatGPT 在 Chat 模式中也可以通过 MCP 读取本机文件、写入文件、查看屏幕并操作 Windows 桌面，从而在完全符合 OpenAI 使用规范的前提下有效缓解 Codex 额度不足焦虑。默认允许访问当前 Windows 用户本来就有权限访问的本地磁盘位置，不需要额外配置目录白名单；服务不会自动获得管理员权限。

本机服务使用标准 MCP stdio，通过 OpenAI Secure MCP Tunnel 连接 ChatGPT。文件和桌面工具本身不监听 HTTP 端口；官方 Tunnel 客户端只在本机回环地址提供健康检查，端口自动分配。

## 项目状态

仓库包含完整源码、Windows 启停与安全控制脚本，以及自动化测试。虚拟环境、Tunnel 运行时、凭据、备份和审计记录不会提交到仓库。验证结果见 [VALIDATION.zh-CN.md](VALIDATION.zh-CN.md)。

首次使用时，需要在本机提供实际 Tunnel ID 和 runtime API key。密钥只应通过本机控制菜单输入，不要提交到 GitHub，也不要粘贴到聊天中。每台电脑和每个账号都应单独完成连接与验证。

Secure MCP Tunnel 用于把本地、私有或防火墙后的 MCP 服务连接到受支持的 OpenAI 产品；这个 GitHub 仓库只负责分发源码。ChatGPT 客户端、工作区和模型的可用能力会随产品更新而变化，请以 OpenAI 当前文档和界面为准。

## 权限与风险

这是一个**高权限本机工具**。一旦通过 MCP 暴露给模型，它可以在当前 Windows 用户本来拥有的权限范围内读取和修改文件，并通过普通桌面应用进行点击、滚动和键盘输入。

需要特别理解以下边界：

- 文件访问范围接近当前 Windows 用户自身的访问范围，而不是一个独立沙箱；
- 桌面控制可以接触当前用户会话中普通应用能够看到的数据，包括私人文件、聊天窗口和已登录网站；
- 目标窗口锁、一次性截图编号、暂停热键、备份和审计只能降低误操作与误输入风险，**不能把模型隔离成低权限进程**；
- 同一 Windows 用户下运行的其他软件仍可能读取、修改或干扰该用户的数据与前台窗口；
- 锁屏、UAC 安全桌面以及更高权限应用会被拒绝控制，但这不等于系统级安全边界；
- 已经发送给 Windows 的输入和已经完成的磁盘写入无法自动撤销；
- 不应把 runtime key、Tunnel 凭据、.local 目录、审计记录或私人截图提交到 GitHub 或粘贴到聊天中。

如果你不接受模型拥有当前用户级文件与桌面控制能力，就不应运行这个服务。建议使用普通用户权限、保留紧急暂停热键，并在处理敏感账号、支付、密码管理器或重要生产数据时主动暂停服务。

## 连接 ChatGPT

1. 打开 [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels)，创建 Tunnel 并关联你的 ChatGPT 工作区。创建 Tunnel 需要组织级 Tunnels Read 和 Manage 权限，运行需要 Read 和 Use。
2. 准备该组织的 runtime API key。不要使用管理员密钥。
3. 双击 Control.cmd，选择 1，按提示在本机输入 Tunnel ID 和 runtime key。密钥输入不回显，并使用 Windows DPAPI 加密保存，只对当前电脑的当前 Windows 用户有效。
4. 在控制菜单选择 2 启动，再选择 3 检查。看到 Tunnel readiness HTTP 200 才表示 Tunnel 已就绪；如果之前暂停过，选择 5 恢复。
5. 在 ChatGPT 中启用开发者模式，并按照当前产品界面创建使用 Tunnel 连接的自定义应用。服务自身不提供 OAuth；远程访问由 Secure MCP Tunnel 的账号与工作区权限控制。
6. 在支持插件/工具的 ChatGPT 客户端中进入同一工作区，添加这个应用。若当前客户端或模型没有插件入口，本机服务无法替客户端启用该能力。
7. 第一次连接建议先调用 service_status，再测试读取文件、创建测试文件和 desktop_screenshot，确认正常后再执行真实任务。

这个服务不需要单独调用 OpenAI 模型 API；runtime key 用于 Secure MCP Tunnel 连接。账号资格、权限与费用以 OpenAI 平台当前规则为准。

## 日常控制

| 控制菜单 | 动作 |
| --- | --- |
| 1 | 配置 Tunnel ID 和 runtime key |
| 2 | 后台启动 Tunnel 与本机 MCP |
| 3 | 检查暂停状态、进程和 Tunnel 健康状态 |
| 4 | 暂停后续文件与桌面操作 |
| 5 | 在本机恢复操作 |
| 6 | 暂停并停止 Tunnel 及其子进程 |
| 7 | 安装或修复依赖 |
| 8 | 显示说明 |
| 9 | 安装登录后自动连接，并在 Tunnel 异常退出时自动恢复 |
| 10 | 移除自动连接，但不打断当前已运行连接 |

运行时可按 **Ctrl + Alt + F11** 紧急暂停。也可以运行 Pause.ps1，或者让模型调用 service_pause。恢复只能由本机的 Resume.ps1 或控制菜单执行。

暂停会在动作检查点生效；已经发给 Windows 的输入和已经完成的磁盘写入无法撤回。复制备份、文字输入和拖动过程中会反复检查暂停状态。

选择自动连接后，项目会为当前用户创建计划任务：登录 Windows 后隐藏启动连接，并定期确认 Tunnel 进程仍是原先记录的进程。计划任务不会保存 Tunnel ID 或 API key。自动连接只在当前用户已登录的交互式会话中运行，不安装系统服务，也不提升权限。

## 文件与桌面工具

| 用途 | 工具 |
| --- | --- |
| 文件信息和目录 | file_info、list_directory |
| 文本和二进制读取 | read_text_file、read_binary_file |
| 创建、覆盖、目录、移动和回收 | write_file、create_directory、move_path、recycle_path |
| 显示器、窗口和截图 | desktop_monitors、desktop_windows、desktop_screenshot |
| 激活窗口并锁定输入目标 | desktop_focus_window |
| 鼠标 | desktop_click、desktop_move、desktop_drag、desktop_scroll |
| 键盘与中文输入 | desktop_keypress、desktop_type_text |
| 状态和暂停 | service_status、service_pause |

文本默认按 UTF-8 处理，也可明确指定 UTF-16 或 GB18030。二进制读取使用 base64 分块，每次最多 1 MiB；单次写入最多 8 MiB；文字输入每次最多 4000 个字符。

覆盖现有文件需要显式传入 overwrite=true。旧内容成功备份后，服务才会用同目录临时文件原子替换原文件，并尽量保留原文件 DACL。可传入 file_info 返回的 modified_ns，在覆盖前检测文件是否已经发生变化。

为减少不可逆损失，服务拒绝直接覆盖带备用数据流、加密、压缩、稀疏、只读、隐藏或系统属性的文件。链接和 junction 的变更也会被拒绝，需要明确指定真实路径。删除只进入回收站，失败时不会降级成永久删除。

服务自身源码不能通过 MCP 文件工具改写；.local 中的凭据、备份和审计同样不会暴露给模型。

## 桌面目标锁

从 0.1.3 开始，桌面输入采用显式目标锁：

1. 先通过 desktop_windows 找到目标窗口；
2. 调用 desktop_focus_window 显式锁定它；
3. 后续截图不会改变这个输入目标；
4. 如果你手动切到微信、浏览器或其他程序，ChatGPT 仍然可以截图观察，但鼠标、滚轮和键盘输入会被拒绝；
5. 只有再次显式调用 desktop_focus_window，才会切换输入目标。

目标身份会核对 PID、进程创建时间、可执行文件路径以及目标窗口的 root-owner 链。这样既能允许目标程序自己的模态对话框，又能阻止同一进程中的另一个无关顶层窗口被意外接管。

每次桌面输入仍必须携带刚取得的截图 observation_id。编号有效期 60 秒，并且一次性使用。输入前和输入过程中都会继续检查暂停状态、前台窗口和锁定目标。

如果检测到修饰键或鼠标按钮仍被按住，服务最多等待 1 秒，并要求连续 100 毫秒处于释放状态。超时后会报告具体按键或按钮，不会替用户强行释放。

## 备份、审计与权限边界

覆盖备份保存在 .local/backups。审计记录位于 .local/audit，记录时间、工具、路径、长度和成功/失败状态，但不记录文件正文、截图内容或键入文字。Tunnel 自身日志保存在 .local/tunnel.stdout.log 和 .local/tunnel.stderr.log。

完整桌面权限意味着模型可以通过普通应用接触当前 Windows 用户能够访问的数据。文件拒绝规则、本机暂停、目标锁和 DPAPI 都不是完整的操作系统安全沙箱；它们主要用于认证、降低误操作风险和提高恢复能力。

安全问题与敏感信息处理见 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。

## 安装与开发

要求 Windows 10 1703 以上或 Windows 11、Python 3.13 以上，以及能够访问 OpenAI 的出站 HTTPS 网络。

首次安装或迁移到新电脑时运行：

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
~~~

脚本的执行策略只对这一次 PowerShell 进程生效，不修改全局策略。标准 MCP 客户端也可以直接运行 .venv/Scripts/python.exe -m windows_local_mcp。这个 stdio 入口自身不做独立身份认证，因此调用者应当是受信任的本机客户端或官方 Tunnel 进程。

Python 包名仍保留为 windows-local-mcp，即使 GitHub 仓库名为 windows-local-mcp；这样可以避免破坏现有安装、命令和升级路径。

## 官方资料

- [ChatGPT 开发者模式](https://developers.openai.com/api/docs/guides/developer-mode)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [ChatGPT 插件说明](https://learn.chatgpt.com/docs/plugins)
- [官方 Tunnel 客户端](https://github.com/openai/tunnel-client/releases/latest)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Windows SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
