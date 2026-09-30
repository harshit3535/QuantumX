"""Turn model/agent markdown into typed segments (text / code / math / table / list).

This is what stops code and equations from being "mixed blindly into normal text":
they leave the parser as their own segment types, with language, filename and
indentation preserved byte for byte.
"""
from __future__ import annotations

import re

from ..models import Segment

_EXT_LANG = {
    "py": "python", "js": "javascript", "ts": "typescript", "jsx": "jsx", "tsx": "tsx", "html": "html", "css": "css",
    "json": "json", "md": "markdown", "sh": "bash", "bash": "bash", "c": "c", "cpp": "cpp", "cc": "cpp", "h": "c",
    "java": "java", "kt": "kotlin", "go": "go", "rs": "rust", "rb": "ruby", "php": "php", "sql": "sql", "yml": "yaml",
    "yaml": "yaml", "xml": "xml", "cs": "csharp", "swift": "swift", "txt": "text",
}
_LANG_ALIAS = {"py": "python", "js": "javascript", "ts": "typescript", "sh": "bash", "shell": "bash", "c++": "cpp",
               "c#": "csharp", "yml": "yaml", "golang": "go", "rs": "rust", "text": "text", "plaintext": "text"}

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^\n]*)$")
_FILENAME_TOKEN = re.compile(r"^[\w\-./]+\.[A-Za-z0-9]{1,6}$")
_COMMENT_FILENAME = re.compile(r"^\s*(?:#|//|--|/\*|<!--)\s*(?:file(?:name)?|path)\s*[:=]\s*([\w\-./]+\.\w{1,6})", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:([-*•])|(\d+)[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _normalize_lang(lang: str | None) -> str | None:
    if not lang:
        return None
    l = lang.strip().lower()
    return _LANG_ALIAS.get(l, l)


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _parse_info(info: str) -> tuple[str | None, str | None]:
    """Fence info string -> (language, filename)."""
    lang = None
    filename = None
    for tok in info.replace(",", " ").split():
        low = tok.lower()
        if low.startswith(("title=", "filename=", "file=", "name=")):
            filename = tok.split("=", 1)[1].strip("\"'")
        elif _FILENAME_TOKEN.match(tok) and filename is None:
            filename = tok
        elif lang is None and re.match(r"^[\w+#.\-]+$", tok):
            lang = tok
    lang = _normalize_lang(lang)
    if not lang and filename and "." in filename:
        lang = _EXT_LANG.get(filename.rsplit(".", 1)[1].lower())
    return lang, filename


def markdown_to_segments(text: str) -> list[Segment]:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    segs: list[Segment] = []
    para: list[str] = []

    def flush_para() -> None:
        content = "\n".join(para).strip("\n")
        para.clear()
        if content.strip():
            segs.append(Segment(type="text", content=content.strip()))

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # ---- fenced code -------------------------------------------------
        m = _FENCE.match(line)
        if m:
            flush_para()
            indent, fence, info = m.group(1), m.group(2), m.group(3).strip()
            lang, filename = _parse_info(info)
            body: list[str] = []
            i += 1
            while i < n and not re.match(rf"^\s*{re.escape(fence[0])}{{{len(fence)},}}\s*$", lines[i]):
                body.append(lines[i][len(indent):] if lines[i].startswith(indent) else lines[i])
                i += 1
            i += 1  # closing fence (or EOF)
            code = "\n".join(body).rstrip("\n")
            if not filename and body:
                fm = _COMMENT_FILENAME.match(body[0])
                if fm:
                    filename = fm.group(1)
                    lang = lang or _EXT_LANG.get(filename.rsplit(".", 1)[1].lower())
            segs.append(Segment(type="code", content=code, language=lang, filename=filename))
            continue

        # ---- block math: $$ ... $$  or \[ ... \] ------------------------
        stripped = line.strip()
        if stripped.startswith("$$") or stripped.startswith("\\["):
            opener = "$$" if stripped.startswith("$$") else "\\["
            closer = "$$" if opener == "$$" else "\\]"
            rest = stripped[len(opener):]
            if closer in rest:                       # single line
                flush_para()
                segs.append(Segment(type="math", content=rest.split(closer, 1)[0].strip(), display=True))
                after = rest.split(closer, 1)[1].strip()
                if after:
                    para.append(after)
                i += 1
                continue
            buf = [rest] if rest.strip() else []
            j = i + 1
            found = False
            while j < n:
                if closer in lines[j]:
                    buf.append(lines[j].split(closer, 1)[0])
                    found = True
                    break
                buf.append(lines[j])
                j += 1
            if found:
                flush_para()
                segs.append(Segment(type="math", content="\n".join(buf).strip(), display=True))
                i = j + 1
                continue
            # unclosed -> fall through as plain text

        # ---- table --------------------------------------------------------
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and line.count("|") >= 1:
            flush_para()
            header = _split_row(line)
            rows: list[list[str]] = []
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                cells = _split_row(lines[j])
                rows.append((cells + [""] * len(header))[: len(header)])
                j += 1
            segs.append(Segment(type="table", header=header, rows=rows))
            i = j
            continue

        # ---- list ---------------------------------------------------------
        lm = _LIST_ITEM.match(line)
        if lm:
            flush_para()
            ordered = lm.group(2) is not None
            items: list[str] = []
            j = i
            while j < n:
                m2 = _LIST_ITEM.match(lines[j])
                if m2 and (m2.group(2) is not None) == ordered:
                    items.append(m2.group(3).strip())
                    j += 1
                elif lines[j].startswith("  ") and lines[j].strip() and items:   # continuation line
                    items[-1] += " " + lines[j].strip()
                    j += 1
                else:
                    break
            segs.append(Segment(type="list", items=items, ordered=ordered))
            i = j
            continue

        # ---- paragraph ------------------------------------------------------
        if not stripped:
            flush_para()
        else:
            para.append(line)
        i += 1

    flush_para()
    return segs


def guess_kind(segments: list[Segment]) -> str:
    kinds = {s.type for s in segments}
    non_text = kinds - {"text"}
    if not non_text:
        return "text"
    if len(non_text) == 1 and "text" not in kinds:
        only = next(iter(non_text))
        return only if only in {"code", "math", "table"} else "mixed"
    return "mixed"
