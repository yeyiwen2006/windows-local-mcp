"""Bounded literal searches; no shell, indexing service or command permission needed."""
from __future__ import annotations

from collections import Counter
import fnmatch
import io
import json
import os
from pathlib import Path
import re
import stat
import time


DEFAULT_EXCLUDES = (".git", ".venv", "venv", "node_modules", "__pycache__")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_RESULT_CHARS = 65536
ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "gb18030")


def _version(st: os.stat_result) -> str:
    return "v1:" + ":".join(str(value) for value in (
        st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))


def _link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _content_state(st: os.stat_result) -> tuple:
    # Windows path stat and fstat can expose different ctime semantics.
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def _integer(value: int, name: str, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be {low}..{high}")


class _Limit(Exception):
    pass


class Search:
    def __init__(self, files, root: str, name_pattern: str, max_results: int,
                 max_entries: int, timeout_seconds: int, exclude_dirs: list[str] | None):
        _integer(max_results, "max_results", 1, 1000)
        _integer(max_entries, "max_entries", 1, 100000)
        _integer(timeout_seconds, "timeout_seconds", 1, 30)
        if (not isinstance(name_pattern, str) or not 1 <= len(name_pattern) <= 512
                or any(c in name_pattern for c in ("/", "\\", "\0"))):
            raise ValueError("name_pattern must be a basename glob, without path separators")
        excluded = DEFAULT_EXCLUDES if exclude_dirs is None else exclude_dirs
        if (not isinstance(excluded, (list, tuple)) or len(excluded) > 128
                or any(not isinstance(v, str) or not 1 <= len(v) <= 256
                       or v in (".", "..") or any(c in v for c in ("/", "\\", "\0"))
                       for v in excluded)):
            raise ValueError("exclude_dirs must contain at most 128 directory basenames")
        self.fs = files
        self.fs.guard.check()
        if _link(Path(root).expanduser().lstat()):
            raise ValueError("Search root must not be a symlink or junction")
        self.root = self.fs.path(root)
        if not self.root.is_dir():
            raise ValueError("Search root must be an existing local directory")
        self.pattern = name_pattern
        self.excluded = set(excluded)
        self.max_results = max_results
        self.max_entries = max_entries
        self.deadline = time.monotonic() + timeout_seconds
        self.results = []
        self.skipped = Counter()
        self.entries = self.files_scanned = self.bytes_read = self.result_chars = 0
        self.stop_reason = None

    def check(self):
        self.fs.guard.check()
        if time.monotonic() >= self.deadline:
            raise _Limit("time_limit")

    def safe_path(self, path: Path) -> Path:
        resolved = self.fs.path(str(path))
        if not resolved.is_relative_to(self.root):
            raise PermissionError("Path resolves outside the search root")
        return resolved

    def candidates(self):
        # Keep at most 64 open directory iterators instead of collecting a whole tree.
        stack = [os.scandir(self.root)]
        try:
            while stack:
                self.check()
                try:
                    entry = next(stack[-1])
                except StopIteration:
                    stack.pop().close()
                    continue
                except OSError:
                    self.skipped["directory_unreadable"] += 1
                    stack.pop().close()
                    continue
                if self.entries >= self.max_entries:
                    raise _Limit("entry_limit")
                self.entries += 1
                try:
                    # Windows DirEntry.stat omits the device/inode identity.
                    st = Path(entry.path).lstat()
                    if _link(st):
                        self.skipped["link"] += 1
                        continue
                    path = self.safe_path(Path(entry.path))
                    if stat.S_ISDIR(st.st_mode):
                        if entry.name in self.excluded:
                            self.skipped["excluded_directory"] += 1
                        elif len(stack) >= 64:
                            self.skipped["depth_limit"] += 1
                        else:
                            stack.append(os.scandir(path))
                    elif not stat.S_ISREG(st.st_mode):
                        self.skipped["special_file"] += 1
                    elif fnmatch.fnmatchcase(entry.name, self.pattern):
                        yield path, st
                except PermissionError:
                    self.fs.guard.check()
                    self.skipped["protected_or_inaccessible"] += 1
                except (OSError, ValueError):
                    self.fs.guard.check()
                    self.skipped["unavailable"] += 1
        finally:
            for iterator in stack:
                iterator.close()

    def add(self, result):
        size = len(json.dumps(result, ensure_ascii=False))
        if len(self.results) >= self.max_results:
            raise _Limit("result_limit")
        if self.result_chars + size > MAX_RESULT_CHARS:
            raise _Limit("output_limit")
        self.results.append(result)
        self.result_chars += size

    def read(self, path: Path, before: os.stat_result, max_bytes: int) -> bytes | None:
        if before.st_size > MAX_FILE_BYTES:
            self.skipped["file_too_large"] += 1
            return None
        if before.st_size > max_bytes - self.bytes_read:
            raise _Limit("byte_limit")
        self.check()
        if _link(path.lstat()) or self.safe_path(path) != path:
            self.skipped["changed"] += 1
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or _content_state(opened) != _content_state(before):
                self.skipped["changed"] += 1
                return None
            chunks = []
            remaining = before.st_size
            while remaining:
                self.check()
                block = stream.read(min(65536, remaining))
                if not block:
                    break
                self.bytes_read += len(block)
                remaining -= len(block)
                chunks.append(block)
            if (remaining or _version(os.fstat(stream.fileno())) != _version(opened)
                    or _link(path.lstat()) or self.safe_path(path) != path
                    or _version(path.stat()) != _version(before)):
                self.skipped["changed"] += 1
                return None
        self.files_scanned += 1
        return b"".join(chunks)

    def result(self):
        self.fs.guard.check()
        return {"root": str(self.root), "results": self.results,
                "entries_scanned": self.entries, "files_scanned": self.files_scanned,
                "bytes_read": self.bytes_read, "skipped": dict(self.skipped),
                "truncated": self.stop_reason is not None,
                "stop_reason": self.stop_reason,
                "complete": self.stop_reason is None and not self.skipped,
                "order": "filesystem", "excluded_directories": sorted(self.excluded)}


def search_files(files, root: str, name_pattern: str = "*", max_results: int = 200,
                 max_entries: int = 20000, timeout_seconds: int = 5,
                 exclude_dirs: list[str] | None = None) -> dict:
    search = Search(files, root, name_pattern, max_results, max_entries,
                    timeout_seconds, exclude_dirs)
    iterator = search.candidates()
    try:
        for path, st in iterator:
            search.check()
            search.files_scanned += 1
            search.add({"path": str(path), "bytes": st.st_size, "version": _version(st)})
    except _Limit as exc:
        search.stop_reason = str(exc)
    finally:
        iterator.close()
    return search.result()


def search_text(files, root: str, query: str, name_pattern: str = "*",
                encoding: str = "utf-8-sig", case_sensitive: bool = True,
                max_results: int = 200, max_entries: int = 20000,
                max_bytes: int = 16 * 1024 * 1024, timeout_seconds: int = 5,
                exclude_dirs: list[str] | None = None) -> dict:
    if (not isinstance(query, str) or not 1 <= len(query) <= 4096
            or any(c in query for c in ("\n", "\r", "\0"))):
        raise ValueError("query must be 1..4096 characters of literal, single-line text")
    if encoding not in ENCODINGS or type(case_sensitive) is not bool:
        raise ValueError("Unsupported encoding or invalid case_sensitive")
    _integer(max_bytes, "max_bytes", 1, 64 * 1024 * 1024)
    search = Search(files, root, name_pattern, max_results, max_entries,
                    timeout_seconds, exclude_dirs)
    matcher = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    iterator = search.candidates()
    try:
        for path, st in iterator:
            search.check()
            try:
                data = search.read(path, st, max_bytes)
                if data is None:
                    continue
                text = data.decode(encoding, errors="strict")
            except UnicodeError:
                search.skipped["decode_error"] += 1
                continue
            except (OSError, ValueError):
                search.fs.guard.check()
                search.skipped["unreadable"] += 1
                continue
            if "\0" in text:
                search.skipped["binary"] += 1
                continue
            with io.StringIO(text, newline="") as lines:
                for number, line in enumerate(lines, 1):
                    search.check()
                    line = line.rstrip("\r\n")
                    match = matcher.search(line)
                    if match:
                        start = max(0, match.start() - 100)
                        snippet = line[start:start + 400]
                        search.add({"path": str(path), "line": number,
                                    "column": match.start() + 1, "text": snippet,
                                    "snippet_start_column": start + 1,
                                    "snippet_truncated": start > 0 or start + len(snippet) < len(line),
                                    "version": _version(st)})
    except _Limit as exc:
        search.stop_reason = str(exc)
    finally:
        iterator.close()
    return search.result()
