# Windows Local MCP

让 ChatGPT 通过 MCP 读取本机文件、写入文件、查看屏幕并操作 Windows 桌面。默认允许访问当前 Windows 用户有权访问的本地磁盘位置，无需配置目录白名单。服务不会自动取得管理员权限。

本机服务使用标准 MCP stdio，通过 OpenAI Secure MCP Tunnel 连接 ChatGPT。文件和桌面工具没有 HTTP 监听端口。官方隧道客户端会在本机回环地址提供健康检查，端口自动分配。

## 目前完成到哪里

此仓库包含完整源码、Windows 启停与安全控制脚本，以及自动化测试。虚拟环境、Tunnel 运行时、凭据、备份和审计记录不会提交到仓库。文件与 MCP 协议测试结果见 `验证记录.md`。

首次使用需要你的账号提供实际 Tunnel ID 和 runtime API key。密钥只应在本机控制菜单中输入，不要提交到 GitHub，也不要粘贴到聊天中。每台电脑和每个账号都应按下面步骤单独连接和验证。

Secure MCP Tunnel 用于把私有、本地或防火墙后的 MCP 服务连接到受支持的 OpenAI 产品；它不是公开插件目录的分发通道。本仓库的开源发布仅用于分发源代码。实际可用的 ChatGPT 客户端、工作区与模型能力会随产品更新而变化，请以 OpenAI 当前文档和界面为准。

## 连接你的账号

1. 打开 [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels)，创建隧道并关联你的 ChatGPT 工作区。创建需要组织级 Tunnels Read 和 Manage 权限，运行需要 Read 和 Use。个人账号使用自己的 Platform 组织。
2. 准备该组织的 runtime API key。不要使用管理员密钥，也不要在聊天中粘贴密钥。
3. 双击本目录的 `Control.cmd`。选择 `1`，按提示输入 Tunnel ID 和密钥。密钥输入不回显，保存时使用 Windows DPAPI 加密，绑定当前电脑的当前 Windows 用户。
4. 在控制菜单选择 `2` 启动，再选择 `3` 检查。看到 `Tunnel readiness HTTP 200` 才表示隧道就绪。若之前暂停过，选择 `5` 恢复。
5. 在 ChatGPT 网页端进入 Settings → Security and login，开启 Developer mode。打开 [ChatGPT Plugins](https://chatgpt.com/plugins)，点加号创建自定义应用，Connection 选择 Tunnel，选择你的隧道。服务自身没有 OAuth，认证方式选 No authentication。远程访问由官方隧道的账号和工作区权限约束。
6. 回到支持插件/工具的 ChatGPT 客户端，在同一工作区新建对话，检查能否添加这个应用。若当前客户端或模型没有插件入口，本机服务无法替客户端启用该能力；可先在网页版按当前产品界面验证。
7. 先让 ChatGPT 调用 `service_status`，再读取一个专用测试文件、创建一个新测试文件，随后调用 `desktop_screenshot`。确认结果正常后再进行实际任务。

服务不需要单独调用 OpenAI 模型 API。这里的 runtime key 用于隧道连接，具体账号资格、权限和费用以 OpenAI 平台为准。

## 日常控制

| 控制菜单 | 动作 |
| --- | --- |
| 1 | 配置账号连接 |
| 2 | 在后台启动隧道及本机 MCP |
| 3 | 查看暂停标记、进程及隧道就绪状态 |
| 4 | 暂停后续文件和桌面操作 |
| 5 | 在本机恢复操作 |
| 6 | 暂停并停止隧道和它的子进程 |
| 7 | 安装或修复依赖 |
| 8 | 显示本说明 |
| 9 | 安装登录后自动连接，并在 Tunnel 意外退出时重新启动 |
| 10 | 移除自动连接，保留当前已运行的连接 |

运行时可按 **Ctrl + Alt + F11** 紧急暂停。也可运行 `Pause.ps1`，或者让模型调用 `service_pause`。恢复只能由本机的 `Resume.ps1` 或菜单执行。热键注册状态通过 `service_status` 查看，如果热键被其他软件占用，要使用本机暂停或停止脚本。

暂停在动作检查点生效，已经发送给 Windows 的输入、已经完成的写入无法撤回。复制备份、文字输入和拖动会多次检查暂停状态。磁盘写入失败时，热键仍会设置内存停止标记；这种情况修复磁盘后需要重启服务。

选择控制菜单的 `9` 后，项目会为当前用户创建计划任务，在登录 Windows 后隐藏启动连接，并每 15 秒检查 Tunnel 进程是否仍在运行。计划任务不含 Tunnel ID 或 API key；启动脚本仍从当前用户的 DPAPI 加密配置读取连接信息。它只在当前用户已登录的交互式会话中运行，不安装 Windows 系统服务，也不取得管理员权限。

手动选择菜单 `6` 停止连接后，自动监控在本次登录期间不会重新启动 Tunnel。下一次登录会恢复自动连接；也可以在当前会话中选择菜单 `2` 手动恢复。选择菜单 `10` 可移除计划任务，当前已运行的 Tunnel 不会因此中断。电脑需要保持登录且解锁，锁屏、UAC 安全桌面和更高权限应用不在可控制范围内。不要以管理员身份运行本项目。

## 文件与桌面工具

| 用途 | 工具 |
| --- | --- |
| 文件信息和目录 | `file_info`、`list_directory` |
| 文本和二进制读取 | `read_text_file`、`read_binary_file` |
| 创建、覆盖、目录、移动和回收 | `write_file`、`create_directory`、`move_path`、`recycle_path` |
| 显示器、窗口、截图 | `desktop_monitors`、`desktop_windows`、`desktop_screenshot` |
| 激活窗口 | `desktop_focus_window` |
| 鼠标 | `desktop_click`、`desktop_move`、`desktop_drag`、`desktop_scroll` |
| 键盘与中文输入 | `desktop_keypress`、`desktop_type_text` |
| 状态和暂停 | `service_status`、`service_pause` |

文本默认按 UTF-8 处理，读取时也可明确指定 UTF-16 或 GB18030。二进制使用 base64 分块读取，每次最多 1 MiB。单次写入最多 8 MiB，目录列表可分页，文字输入每次最多 4000 个字符。当前版本不提供追加写入、大文件分块上传或跨磁盘目录移动。

覆盖现有文件需要显式传入 `overwrite=true`。旧文件内容成功写入本机备份后，服务才用同目录临时文件替换原文件，并保留原文件 DACL。可以传入 `file_info` 返回的 `modified_ns` 检查文件是否已被其他程序修改；这是尽力而为的并发检查，编辑时仍应避免让多个程序同时改同一文件。

为避免丢失特殊元数据，服务拒绝直接覆盖带备用数据流、加密、压缩、稀疏、只读、隐藏或系统属性的文件。对链接和 junction 的变更也会拒绝，需明确指定真实路径。网络共享、设备路径、备用数据流路径和含歧义的 Windows 路径不作为文件工具入口。

删除工具只进入回收站，回收失败不会改成永久删除。驱动器根目录、用户主目录、主要系统目录及服务目录不能整体移动或回收。服务自身的源码禁止通过文件工具改写，`.local` 中的凭据、备份和审计也不向模型开放。

桌面输入必须携带刚取得的截图编号。编号有效期 60 秒，使用一次即失效。工具核对前台窗口后才输入，并在输入过程中检查暂停和焦点。截图缩小时，要按元数据把图像坐标换算成屏幕物理坐标；多显示器坐标可能为负。每次输入后重新截图再决定下一步。执行期间尽量不要人工切换窗口或移动鼠标。

如果检测到修饰键或鼠标按钮按住，服务最多等待 1 秒，并要求连续 100 毫秒都已释放。仍不能继续时，错误会列出具体按键或按钮；服务不会代替你强行释放。松开后让模型重新截图再重试。这个检查适用于所有桌面输入，`Win+R` 也受同一规则约束。

## 备份、记录与权限边界

覆盖备份位于 `.local/backups`，每份包含原始内容 `original.bin` 和记录原路径的 `metadata.json`。需要恢复时先暂停服务，再由你在本机复制回原位置。备份和审计不会自动清理，可在停机后按自己的保留需要处理。

服务审计位于 `.local/audit`，记录时间、工具名称、路径、长度及成功或失败，不记录文件正文、截图或键入内容。路径和窗口内容仍可能含私人信息，授权给模型读取的文件与屏幕内容会通过 ChatGPT 处理。隧道自己的日志在 `.local/tunnel.stdout.log` 和 `.local/tunnel.stderr.log`，同样只在本机检查。

完整桌面权限意味着模型可以通过普通应用访问本机数据。文件工具的拒绝规则、暂停文件和 DPAPI 都不构成对当前 Windows 用户或全桌面操作的隔离。同一用户下的恶意程序，或者获得广泛操作权限的错误指令，仍可能造成损失。这里的保护主要用于连接认证、减少误操作和恢复文件。不要把它当成能抵御一切提示词注入的沙箱。

## 重新安装和开发

需要 Windows 10 1703 以上或 Windows 11、Python 3.13 以上，以及可访问 OpenAI 的出站 HTTPS 网络。首次安装或迁移到另一台电脑时运行 `Setup.ps1`，并重新配置密钥；虚拟环境和 DPAPI 密钥不适合直接搬到另一台电脑。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
```

脚本的执行策略只对该次进程生效，不修改全局策略。标准 MCP 客户端也可直接运行 `.venv/Scripts/python.exe -m windows_local_mcp`。这条 stdio 入口没有独立身份认证，调用者应当是你信任的本机客户端或官方隧道进程。

源码使用 Git 管理。`.local`、虚拟环境、密钥和运行记录均已排除。依赖版本记录在 `requirements.lock`。自动化测试只操作临时测试文件，并用模拟输入测试鼠标键盘逻辑；不会向日常应用发送输入。

## 官方资料

- [ChatGPT 开发者模式](https://developers.openai.com/api/docs/guides/developer-mode)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [ChatGPT 插件说明](https://learn.chatgpt.com/docs/plugins)
- [官方隧道客户端发布](https://github.com/openai/tunnel-client/releases/latest)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Windows SendInput 权限与行为](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
\n\n## 许可证\n\n本项目采用 MIT License，详见 `LICENSE`。\n