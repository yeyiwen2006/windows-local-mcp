"""Exact text replacement without re-encoding untouched bytes."""
from __future__ import annotations

import codecs


def _line_number(text: str, position: int) -> int:
    prefix = text[:position]
    line = 1 + prefix.count("\n") + prefix.count("\r") - prefix.count("\r\n")
    if prefix.endswith("\r") and position < len(text) and text[position] == "\n":
        line -= 1  # A position on the LF of CRLF still belongs to the prior line.
    return line


def _byte_span(data: bytes, text: str, start: int, end: int,
               encoding: str) -> tuple[int, int, str]:
    if encoding in ("utf-8", "utf-8-sig"):
        offset = 3 if encoding == "utf-8-sig" and data.startswith(codecs.BOM_UTF8) else 0
        return (offset + len(text[:start].encode("utf-8")),
                offset + len(text[:end].encode("utf-8")), "utf-8")
    if encoding == "utf-16":
        if data.startswith(codecs.BOM_UTF16_LE):
            codec = "utf-16-le"
        elif data.startswith(codecs.BOM_UTF16_BE):
            codec = "utf-16-be"
        else:
            raise ValueError("UTF-16 edits require an explicit byte-order mark")
        return (2 + len(text[:start].encode(codec)),
                2 + len(text[:end].encode(codec)), codec)

    # Some legacy encodings have multiple byte sequences for one character.
    # Locate boundaries in the original bytes instead of re-encoding a prefix.
    decoder = codecs.getincrementaldecoder("gb18030")(errors="strict")
    characters = 0
    byte_start = 0 if start == 0 else None
    for index, value in enumerate(data, 1):
        decoded = decoder.decode(bytes((value,)), final=False)
        if not decoded:
            continue
        characters += len(decoded)
        if characters == start:
            byte_start = index
        if characters == end:
            if byte_start is None:
                break
            return byte_start, index, "gb18030"
        if characters > end:
            break
    raise ValueError("The selected text does not align with encoded character boundaries")


def replace_text_bytes(data: bytes, old_text: str, new_text: str,
                       encoding: str) -> tuple[bytes, dict]:
    if encoding not in ("utf-8", "utf-8-sig", "utf-16", "gb18030"):
        raise ValueError("Supported encodings: utf-8, utf-8-sig, utf-16, gb18030")
    if not old_text:
        raise ValueError("old_text must not be empty")
    text = data.decode(encoding, errors="strict")
    start = text.find(old_text)
    if start < 0:
        raise ValueError("old_text was not found; read the file again")
    if text.find(old_text, start + 1) >= 0:
        raise ValueError("old_text must match exactly once, including overlapping matches")
    end = start + len(old_text)
    changed = old_text != new_text
    summary = {
        "changed": changed,
        "replacements": int(changed),
        "start_line": _line_number(text, start),
        "end_line": _line_number(text, end - 1),
        "new_end_line": _line_number(text[:start] + new_text, max(start, start + len(new_text) - 1)),
    }
    if not changed:
        return data, summary
    byte_start, byte_end, codec = _byte_span(data, text, start, end, encoding)
    replacement = new_text.encode(codec, errors="strict")
    updated = data[:byte_start] + replacement + data[byte_end:]
    if encoding in ("utf-8", "utf-8-sig") and (
            data.startswith(codecs.BOM_UTF8) != updated.startswith(codecs.BOM_UTF8)):
        raise ValueError("The original UTF-8 byte-order mark state must be preserved")
    if updated.decode(encoding, errors="strict") != text[:start] + new_text + text[end:]:
        raise ValueError("The replacement cannot round-trip in the original encoding")
    return updated, summary
