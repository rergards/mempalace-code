"""mining.source_text — Decode source bytes and decide whether a file is indexable.

One owner for the mining read policy:

* UTF-8 first; a UTF-8 byte-order mark is consumed, not stored. Text that starts
  with a UTF-16 or UTF-32 byte-order mark (common for Windows-saved .sql, .cs, and
  .xaml files) is decoded with that codec instead.
* Bytes that are not valid UTF-8 are decoded with a declared ``coding:`` cookie
  (PEP 263 style, first two lines) when one names a known codec; otherwise the
  undecodable bytes are replaced with U+FFFD and counted so the miner can warn.
* NUL bytes or a high share of replacement/control characters mean binary content.
* Files above the byte cap, and minified or generated single-line bundles
  (scripts, stylesheets, JSON, HTML, XML), are skipped unless the caller
  force-includes that exact file.
* Kubernetes ``kind: Secret`` manifests with ``data``/``stringData`` hold credentials
  and are skipped unless force-included (other secret-bearing files are not
  detected; exclude them with .gitignore or ``scan_skip_globs``).
* Whitespace-only files have nothing to index.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass

DEFAULT_MAX_FILE_BYTES = 1_000_000
"""Default per-file size cap for project mining (override: ``max_file_bytes`` in mempalace.yaml)."""

_SNIFF_BYTES = 8192
_BINARY_CHAR_RATIO = 0.10
_MINIFIED_SUFFIXES = (".min.js", ".min.mjs", ".min.cjs", ".min.css")
# Formats that build tools emit as single-line bundles or data dumps. Prose and
# source formats are never classified as minified: their long lines are split.
_GENERATED_LINE_SUFFIXES = frozenset(
    {".js", ".mjs", ".cjs", ".css", ".json", ".html", ".xml", ".map"}
)
_MINIFIED_LINE_CHARS = 4000
_MINIFIED_AVERAGE_LINE_CHARS = 1000
_CODING_COOKIE_RE = re.compile(rb"^[ \t\f]*(?:#|//|--|;|%|/\*).*?coding[:=][ \t]*([-\w.]+)")
_ALLOWED_CONTROL = frozenset("\t\n\r\f\v\x1b")

SKIP_EMPTY = "empty"
SKIP_BINARY = "binary"
SKIP_TOO_LARGE = "too_large"
SKIP_MINIFIED = "minified"
SKIP_SECRET = "secret"

SKIP_REASON_LABELS = {
    SKIP_EMPTY: "empty",
    SKIP_BINARY: "binary content",
    SKIP_TOO_LARGE: "too large",
    SKIP_MINIFIED: "minified or generated",
    SKIP_SECRET: "Kubernetes Secret manifest",
}

_YAML_SUFFIXES = (".yaml", ".yml")
_K8S_SECRET_KIND_RE = re.compile(
    r"^kind[ \t]*:[ \t]*[\"']?Secret[\"']?[ \t]*(?:#.*)?$", re.MULTILINE
)
_K8S_SECRET_DATA_RE = re.compile(r"^(?:data|stringData)[ \t]*:", re.MULTILINE)
_YAML_DOCUMENT_SEPARATOR_RE = re.compile(r"^---[ \t]*(?:#.*)?$", re.MULTILINE)


@dataclass(frozen=True)
class SourceText:
    """Decoded text of one source file and whether mining should index it."""

    text: str
    skip_reason: str | None = None
    encoding: str = "utf-8"
    replaced_bytes: int = 0


def _declared_encoding(data: bytes) -> str | None:
    for line in data.split(b"\n", 2)[:2]:
        match = _CODING_COOKIE_RE.match(line)
        if match:
            try:
                return codecs.lookup(match.group(1).decode("ascii")).name
            except (LookupError, UnicodeDecodeError):
                return None
    return None


# UTF-32 marks first: the UTF-32-LE mark begins with the UTF-16-LE one.
_WIDE_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _wide_bom_encoding(data: bytes) -> str | None:
    for bom, encoding in _WIDE_BOMS:
        if data.startswith(bom):
            return encoding
    return None


def _decode(data: bytes) -> tuple[str, str, int]:
    """Return (text, encoding, replaced_byte_count) for raw source bytes."""
    wide = _wide_bom_encoding(data)
    if wide is not None:
        try:
            return data.decode(wide), wide, 0
        except UnicodeDecodeError:
            pass  # not really UTF-16/32 text; classify the raw bytes below
    if data.startswith(codecs.BOM_UTF8):
        body = data[len(codecs.BOM_UTF8) :]
        try:
            return body.decode("utf-8"), "utf-8-sig", 0
        except UnicodeDecodeError:
            text = body.decode("utf-8", errors="replace")
            return text, "utf-8-sig", text.count("�")
    try:
        return data.decode("utf-8"), "utf-8", 0
    except UnicodeDecodeError:
        pass
    declared = _declared_encoding(data)
    if declared and declared != "utf-8":
        try:
            return data.decode(declared), declared, 0
        except UnicodeDecodeError:
            pass
    text = data.decode("utf-8", errors="replace")
    return text, "utf-8", text.count("�")


def _looks_binary(data: bytes, text: str, encoding: str) -> bool:
    # NUL bytes are ordinary in UTF-16/32 text, so only a byte-oriented decode uses them.
    if encoding not in ("utf-16", "utf-32") and b"\x00" in data[:_SNIFF_BYTES]:
        return True
    sample = text[:_SNIFF_BYTES]
    if not sample:
        return False
    suspicious = sum(
        1 for ch in sample if ch == "�" or (ord(ch) < 32 and ch not in _ALLOWED_CONTROL)
    )
    return suspicious / len(sample) > _BINARY_CHAR_RATIO


def looks_minified(filename: str, text: str) -> bool:
    """Return True for minified bundles and one-line generated data files.

    ``*.min.js``/``*.min.css`` always count. Script, stylesheet, JSON, HTML, and XML
    files count when lines over 4,000 characters dominate them; prose (Markdown,
    text) and other source never do.
    """
    lowered = filename.lower()
    if lowered.endswith(_MINIFIED_SUFFIXES):
        return True
    suffix = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    if f".{suffix}" not in _GENERATED_LINE_SUFFIXES or len(text) <= _MINIFIED_LINE_CHARS:
        return False
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines or max(len(line) for line in lines) <= _MINIFIED_LINE_CHARS:
        return False
    return len(text) / len(lines) > _MINIFIED_AVERAGE_LINE_CHARS


def looks_like_k8s_secret(filename: str, text: str) -> bool:
    """Return True for YAML holding a Kubernetes ``kind: Secret`` document that carries data.

    Both markers must sit in the same ``---``-separated document, so a ConfigMap's
    ``data:`` next to a data-less Secret does not hide the whole file.
    """
    if not filename.lower().endswith(_YAML_SUFFIXES):
        return False
    # Detection only: CRLF/CR endings must not hide the markers from the line anchors.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return any(
        _K8S_SECRET_KIND_RE.search(document) is not None
        and _K8S_SECRET_DATA_RE.search(document) is not None
        for document in _YAML_DOCUMENT_SEPARATOR_RE.split(text)
    )


def decode_source(
    data: bytes,
    filename: str,
    *,
    max_bytes: int | None = DEFAULT_MAX_FILE_BYTES,
    force_include: bool = False,
) -> SourceText:
    """Decode *data* and classify it for project mining.

    *max_bytes* of None or 0 disables the size cap. *force_include* (an exact
    ``--include-ignored`` path) bypasses the size, minified, and Kubernetes Secret
    checks, never the binary check.
    """
    if not force_include and max_bytes and len(data) > max_bytes:
        return SourceText("", SKIP_TOO_LARGE)
    text, encoding, replaced = _decode(data)
    if _looks_binary(data, text, encoding):
        return SourceText("", SKIP_BINARY, encoding, replaced)
    if not text.strip():
        return SourceText(text, SKIP_EMPTY, encoding, replaced)
    if not force_include and looks_minified(filename, text):
        return SourceText(text, SKIP_MINIFIED, encoding, replaced)
    if not force_include and looks_like_k8s_secret(filename, text):
        return SourceText(text, SKIP_SECRET, encoding, replaced)
    return SourceText(text, None, encoding, replaced)
