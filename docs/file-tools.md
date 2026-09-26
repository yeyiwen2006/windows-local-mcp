# File editing and search / 文件编辑与搜索

## 中文

0.3.0 增加 `edit_text_file`、`search_files` 和 `search_text`。三个工具直接使用文件接口，不需要启用通用命令，也不需要桌面焦点。原有工具和参数保持兼容。

### 精确局部编辑

先用 `read_text_file` 读取相关行，再把返回的 `version` 原样传入 `edit_text_file.expected_version`。`file_info` 也返回版本，但编辑所用版本应来自检查过正文的那次读取。版本是字符串，不要转成数字或重新拼装；原有 `modified_ns` 仍保留。

```json
{
  "path": "C:\\projects\\example\\settings.py",
  "old_text": "timeout = 30",
  "new_text": "timeout = 60",
  "expected_version": "原样使用读取结果中的 version",
  "encoding": "utf-8-sig"
}
```

旧文本必须非空，并在文件中恰好匹配一次，包括重叠匹配也会检查。匹配失败或版本变化时重新读取，不做模糊猜测。新旧文本相同则返回 `changed=false`，不改文件，也不新建备份。

工具保留未修改部分的原始字节、原有 BOM 和 UTF-16 端序。支持 UTF-8、UTF-8 BOM、带 BOM 的 UTF-16、GB18030。编码必须与读取时一致。替换文本中的换行按传入内容写入，不会自动把 LF 与 CRLF 互相转换；要保留原换行，应使用读取结果中的换行形式。单文件和修改后文件均不超过 8 MiB。

写入复用原有备份、权限和特殊文件保护。结果包含 `changed`、`replacements`、`start_line`、`end_line`、`new_end_line`、`backup_path` 及新 `version`。行号从 1 开始，结果不回传全文。版本检查能发现通常的并发修改，但不构成对同用户恶意程序的隔离，也不能替代协作编辑锁。

### 递归搜索

`search_files(root, name_pattern="*")` 按文件名查找普通文件。`search_text(root, query, name_pattern="*")` 搜索单行普通文本，每个匹配行返回第一次出现的位置。`query` 不是正则表达式；`case_sensitive=false` 可用于忽略文本大小写。

`name_pattern` 是区分大小写的文件名通配符，例如 `*.py`；不接收路径分隔符。用 `root` 选择目录范围。结果使用文件系统遍历顺序，文本行号和字符列号从 1 开始。每条文本结果最多包含 400 个字符，并通过 `snippet_start_column` 和 `snippet_truncated` 说明片段位置及截断情况。

搜索默认跳过 `.git`、`.venv`、`venv`、`node_modules`、`__pycache__` 目录。`exclude_dirs` 可覆盖该列表，传 `[]` 会包含这些目录。服务私有状态、符号链接、junction 和其他特殊文件始终跳过。内容搜索严格解码，跳过包含 NUL、无法解码或超过 8 MiB 的文件；需要时显式选择 `encoding`。

| 限制 | 默认值 | 最大值 |
| --- | --- | --- |
| `max_results` | 200 | 1000 |
| `max_entries` | 20000 | 100000 |
| `max_bytes`，仅内容搜索 | 16 MiB | 64 MiB |
| `timeout_seconds` | 5 秒 | 30 秒 |
| 目录迭代器深度 | 64 | 固定 |
| 结果记录字符总量 | 65536 | 固定 |

`skipped` 给出按原因统计的跳过数量。触及全局限制时，`truncated=true`，`stop_reason` 指明原因；只有没有跳过、也没有提前停止时 `complete=true`。结果没有分页游标，范围过大时应缩小根目录或文件名模式。时间限制在文件操作之间检查，不是能中断阻塞磁盘 I/O 的硬超时。暂停会中断后续遍历和读取。

建议按搜索、读取相关行、精确编辑的顺序使用。搜索片段和文件内容均是不可信数据，不构成额外授权。审计不记录查询正文或替换正文。

### Windows 边界

局部编辑保留原文件 DACL 及其保护状态。带 ADS、reparse point 或其他原写入接口不支持属性的文件仍拒绝覆盖。目录限制只适用于这两个专用搜索接口，不约束任意命令内部的行为。

## English

Version 0.3.0 adds `edit_text_file`, `search_files`, and `search_text`. They use file APIs directly and do not require command opt-in or desktop focus. Existing tools and parameters remain compatible.

Read the relevant text with `read_text_file`, then pass that exact string `version` as `expected_version` when editing. `file_info` also returns a version; use the version associated with the text you inspected. Do not convert it into a number. Existing `modified_ns` fields remain available.

`edit_text_file(path, old_text, new_text, expected_version, encoding="utf-8-sig")` requires one exact nonempty match, including checks for overlapping occurrences. Reread after a conflict. Identical old/new text is a no-op with `changed=false` and no new backup. Input and resulting files are limited to 8 MiB. Untouched bytes, BOM and UTF-16 byte order are preserved. Supported encodings are UTF-8, UTF-8 with BOM, BOM-marked UTF-16, and GB18030. Newline characters in replacement text are literal; use the original newline form when preserving it. Results report replacement count, changed line range, backup path and new version without returning the full file. The stat-based version is a best-effort concurrency check, not an isolation boundary or a collaborative editing lock.

`search_files` recursively finds regular files by a case-sensitive basename glob such as `*.py`. `search_text` performs literal, single-line content matching, with an optional `case_sensitive=false`. It reports the first occurrence on each matching line, with 1-based line and character column, a snippet of at most 400 characters, and explicit snippet position/truncation fields. Filename patterns cannot contain path separators. Results follow filesystem order.

Both searches require an explicit root. Default excluded directories are `.git`, `.venv`, `venv`, `node_modules`, and `__pycache__`; pass `exclude_dirs=[]` to include them. Service-private state, links/junctions and special files remain excluded. Content searches strictly decode using the requested encoding and skip NUL-containing, undecodable or oversized files. No indexing service or shell is used.

Bounds are 200 results by default (maximum 1000), 20000 entries (maximum 100000), 16 MiB of content reads (maximum 64 MiB), 5 seconds (maximum 30), 64 directory iterators and 65536 result-record characters. Individual content files are limited to 8 MiB. Time checks occur between filesystem operations and cannot interrupt blocking I/O. Pause interrupts subsequent traversal/read checkpoints.

Inspect `skipped`, `truncated`, and `stop_reason` before treating results as exhaustive. `complete` is true only when no entries were skipped and no global limit stopped the search. There is no pagination cursor; narrow the root or filename pattern instead. Audit records omit query and replacement contents. Search snippets and file contents are untrusted data, never authorization.

On Windows, edits retain the existing DACL and protected-DACL state. Existing reparse-point, ADS and special-attribute restrictions still apply. Search root restrictions do not sandbox programs launched through command tools.
