#!/usr/bin/env python3
"""
gen_code_intelligence_packet.py — Generate the code-intelligence demo packet.

Builds a synthetic polyglot fixture project, mines it into a disposable palace,
and emits committed docs/demo/code-intelligence-packet.{md,json} from real
CLI output.

Usage:
    python scripts/gen_code_intelligence_packet.py          # regenerate committed artifacts
    python scripts/gen_code_intelligence_packet.py --check  # validate committed artifacts

The script requires the embedding model to be pre-cached:
    mempalace-code fetch-model

It sets offline/version-check-disabled environment variables (HF_HUB_OFFLINE=1,
TRANSFORMERS_OFFLINE=1, MEMPALACE_VERSION_CHECK=0) so no network access is needed.

The check mode regenerates the packet into a temp directory, compares the JSON
structure against the committed artifacts, validates the JSON schema, and checks
for public-safety violations (no absolute paths, no secret-like tokens). It
requires the embedding model to be cached and takes 20-60 seconds.

Because of the model dependency, this check is wired into release verification
only — not into /verify or daily CI. Wire it manually before a release with:
    python scripts/gen_code_intelligence_packet.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────────

SCHEMA_VERSION = 1

PACKET_DIR = Path(__file__).resolve().parent.parent / "docs" / "demo"
PACKET_JSON = PACKET_DIR / "code-intelligence-packet.json"
PACKET_MD = PACKET_DIR / "code-intelligence-packet.md"

# CLI to invoke — use the same Python that is running this script.
_PYTHON = sys.executable

# Env vars for deterministic, offline, prompt-free operation.
_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "MEMPALACE_VERSION_CHECK": "0",
    "MEMPALACE_DISK_MIN_FREE_BYTES": "1",
}

# Known-answer queries: (query_text, expected_filename_fragment, exhibit_label)
KNOWN_ANSWER_QUERIES: list[tuple[str, str, str]] = [
    ("hash password with salt", "auth.py", "auth-hash-password"),
    ("fibonacci sequence nth number", "calculator.py", "calc-fibonacci"),
    ("serialize user to JSON safely", "models.py", "models-serialize-user"),
    ("API gateway authentication routing", "architecture.md", "arch-gateway"),
    ("factorial recursive calculation", "calculator.py", "calc-factorial"),
]

# Top-N to check for known-answer validation.
_KNOWN_ANSWER_TOP_N = 3


# ── Fixture project definition ─────────────────────────────────────────────────

_FIXTURE_FILES: dict[str, str] = {
    "src/calculator.py": '''\
"""Mathematical utility functions for the calcdemo application."""


def add(a: float, b: float) -> float:
    """Return the sum of two numbers."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference of two numbers."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of two numbers."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return the quotient. Raises ZeroDivisionError when b is 0."""
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b


def factorial(n: int) -> int:
    """Return n! using recursion. n must be a non-negative integer."""
    if n < 0:
        raise ValueError("Factorial undefined for negative numbers")
    if n == 0:
        return 1
    return n * factorial(n - 1)


def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed), iteratively."""
    if n < 0:
        raise ValueError("Fibonacci undefined for negative indices")
    if n == 0:
        return 0
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b
''',
    "src/auth.py": '''\
"""Authentication utilities: password hashing, token generation and validation."""

import hashlib
import hmac
import secrets
import time
from typing import Optional


def hash_password(password: str, salt: Optional[str] = None) -> tuple:
    """
    Hash a user password with a salt using PBKDF2-HMAC-SHA256.

    Returns (hashed_password, salt). Generates a random salt when none is given.
    Suitable for persisting passwords; use verify_password to check them.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return dk.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """
    Verify a password against its stored hash and salt.

    Uses constant-time comparison to prevent timing-based side-channel attacks.
    """
    expected, _ = hash_password(password, salt)
    return hmac.compare_digest(expected, hashed)


def generate_token(user_id: int, secret: str, expires_in: int = 3600) -> str:
    """
    Generate a signed authentication token for a user.

    Encodes user_id and expiry timestamp; signs with HMAC-SHA256.
    """
    expiry = int(time.time()) + expires_in
    payload = f"{user_id}:{expiry}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def validate_token(token: str, secret: str) -> Optional[int]:
    """
    Validate an authentication token; return user_id if valid, None otherwise.

    Returns None when the token is expired or carries an invalid HMAC signature.
    """
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id_str, expiry_str, sig = parts
        payload = f"{user_id_str}:{expiry_str}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(expiry_str) < int(time.time()):
            return None
        return int(user_id_str)
    except (ValueError, KeyError):
        return None
''',
    "src/models.py": '''\
"""Data models: User, Product, Order — and serialization helpers."""

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    """Application user with authentication credentials."""

    user_id: int
    username: str
    email: str
    hashed_password: str = ""
    salt: str = ""
    is_active: bool = True


@dataclass
class Product:
    """A product in the catalog."""

    product_id: int
    name: str
    price: float
    stock: int = 0
    category: str = "general"


@dataclass
class Order:
    """An order placed by a user."""

    order_id: int
    user_id: int
    items: list = field(default_factory=list)
    total: float = 0.0
    status: str = "pending"


def serialize_user(user: User) -> str:
    """
    Serialize a User to a JSON string, omitting sensitive fields.

    The hashed_password and salt fields are excluded from the output
    so that the serialized form is safe to return in API responses.
    """
    safe_dict = {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
    }
    return json.dumps(safe_dict)


def deserialize_user(data: str) -> User:
    """Deserialize a JSON string into a User dataclass."""
    obj = json.loads(data)
    return User(
        user_id=obj["user_id"],
        username=obj["username"],
        email=obj["email"],
        is_active=obj.get("is_active", True),
    )
''',
    "docs/architecture.md": """\
# System Architecture

The calcdemo application is a microservices system with three core layers.

## API Gateway

The API gateway handles all incoming HTTP requests and routes them to the
appropriate backend service. It enforces authentication, rate limiting, and
request validation before forwarding to downstream services.

Key responsibilities:
- Route requests to auth-service, calculator-service, or catalog-service
- Validate JWT tokens issued by the auth service
- Apply rate limiting per IP and per authenticated user
- Log structured request/response data for observability

## Auth Service

The auth service manages user authentication and session tokens. It exposes
endpoints for login, logout, token refresh, and password change.

Token validation uses HMAC-SHA256 signatures with a shared secret. Tokens
carry user_id and expiry timestamp. The gateway validates tokens on every
request to avoid database round-trips in the hot path.

## Calculator Service

Exposes a REST API for mathematical operations: add, subtract, multiply,
divide, factorial, and fibonacci. All inputs are validated; divide guards
against zero divisors and factorial requires non-negative integers.

## Data Layer

User accounts and product catalog are stored in PostgreSQL. Orders use an
event-sourced model in an append-only table. The models layer (User, Product,
Order) maps database rows to Python dataclasses.
""",
    "config.yaml": """\
# calcdemo application configuration

app:
  name: calcdemo
  version: "1.0.0"
  debug: false

server:
  host: "0.0.0.0"
  port: 8080
  workers: 4

database:
  host: "localhost"
  port: 5432
  name: calcdemo_db
  pool_size: 10

auth:
  token_expiry_seconds: 3600
  max_login_attempts: 5

calculator:
  max_factorial_n: 100
  max_fibonacci_n: 100
""",
    "Makefile": """\
# Build targets for calcdemo

.PHONY: install test lint clean

install:
\tpip install -e ".[dev]"

test:
\tpython -m pytest tests/ -x -q

lint:
\truff check src/

clean:
\tfind . -type d -name "__pycache__" -exec rm -rf {} +
\tfind . -name "*.pyc" -delete
""",
    "mempalace.yaml": """\
wing: calcdemo
rooms:
  - name: backend
    description: Python source files (auth, models, calculator)
  - name: docs
    description: Markdown documentation files
  - name: config
    description: Configuration and build files
""",
}


# ── Exceptions ─────────────────────────────────────────────────────────────────


class KnownAnswerError(Exception):
    """Raised when a known-answer search query does not find the expected file."""


class PublicSafetyError(Exception):
    """Raised when generated output contains absolute paths or secret-like tokens."""


# ── Normalization ──────────────────────────────────────────────────────────────

# Patterns that must not appear in normalized output (public-safety).
_PRIVATE_PATH_RE = re.compile(
    r"(?:"
    r"/Users/[^/\s\"']+"  # macOS home dirs
    r"|/home/[^/\s\"']+"  # Linux home dirs
    r"|/root/"  # root home
    r"|/private/var/folders/[^\s\"']+"  # macOS temp
    r"|/var/folders/[^\s\"']+"  # macOS temp (non-private)
    r"|C:\\Users\\[^\\\s\"']+"  # Windows user dirs
    r")"
)

# Timing patterns to strip.
_TIMING_INLINE_RE = re.compile(r"\(\d+\.\d+s\)")  # (1.2s)
_TIMING_DONE_RE = re.compile(r"\b\d+m \d+s\b")  # 0m 5s
_PROGRESS_BAR_RE = re.compile(r"\d+%\|[█░\s]+\|[^\n]*")  # tqdm progress bars
_BATCH_COUNT_RE = re.compile(r"(\()\d+( chunks\))")  # (47 chunks) → (<COUNT> chunks)


def normalize_output(text: str, fixture_dir: str, palace_dir: str) -> str:
    """Replace machine-specific values with stable placeholders.

    Removes absolute temp paths, timing values, HuggingFace noise, and
    progress bars so that output from different machines is identical.

    Accepts both the raw temp path and its canonical (symlink-resolved) form
    so that macOS /var → /private/var aliases are handled transparently.
    """
    # Resolve symlinks so macOS /var → /private/var aliases both get replaced.
    fixture_real = os.path.realpath(fixture_dir)
    palace_real = os.path.realpath(palace_dir)

    # Strip trailing whitespace from each line early (avoids space-only diffs).
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        # Drop HuggingFace noise and model loading lines.
        if any(
            pat in line
            for pat in (
                "Loading weights:",
                "modules.json:",
                "tokenizer_config.json:",
                "tokenizer.json:",
                "special_tokens_map.json:",
                "vocab.txt:",
                "config.json:",
                "sentence_bert_config.json:",
                "1_Pooling/config.json:",
            )
        ):
            continue
        if _PROGRESS_BAR_RE.search(line):
            continue
        if re.match(r"\s+\d+%\|", line):
            continue
        # Remove "Loading embedding model..." and "Model ready." lines.
        stripped = line.strip()
        if stripped in ("Loading embedding model...", "Model ready."):
            continue

        # Replace absolute paths — both the raw form and the canonical (realpath) form.
        line = line.replace(fixture_real, "<FIXTURE_DIR>")
        line = line.replace(palace_real, "<PALACE_DIR>")
        line = line.replace(fixture_dir, "<FIXTURE_DIR>")
        line = line.replace(palace_dir, "<PALACE_DIR>")

        # Normalize timing values.
        line = _TIMING_INLINE_RE.sub("(<TIMING>)", line)
        line = _TIMING_DONE_RE.sub("<TIMING>", line)
        line = _BATCH_COUNT_RE.sub(r"\1<COUNT>\2", line)

        cleaned.append(line.rstrip())

    # Drop trailing blank lines at document end.
    while cleaned and not cleaned[-1]:
        cleaned.pop()

    return "\n".join(cleaned)


def check_known_answer(
    code_search_result: dict,
    expected_file_fragment: str,
    query: str,
    top_n: int = _KNOWN_ANSWER_TOP_N,
) -> None:
    """Raise KnownAnswerError when expected_file_fragment is absent from top_n results.

    ``code_search_result`` is the dict returned by the ``mempalace_code_search``
    MCP tool (keys: query, filters, results) — or the CLI search output parsed
    into an equivalent structure.
    """
    results = code_search_result.get("results", [])
    hits = results[:top_n]
    found = any(expected_file_fragment in hit.get("source_file", "") for hit in hits)
    if not found:
        actual = [hit.get("source_file", "?") for hit in hits]
        raise KnownAnswerError(
            f"Known-answer check failed for query {query!r}: "
            f"expected {expected_file_fragment!r} in top-{top_n} results, "
            f"got: {actual}"
        )


def _public_safety_check(text: str) -> None:
    """Raise PublicSafetyError when text contains absolute paths or secret-like tokens."""
    hit = _PRIVATE_PATH_RE.search(text)
    if hit:
        raise PublicSafetyError(
            f"Public-safety violation: output contains an absolute path near: "
            f"...{text[max(0, hit.start() - 20) : hit.end() + 20]!r}..."
        )


def _compare_packets(fresh: Any, committed: Any, path: str = "") -> list[str]:
    """Return a list of diff descriptions between two packet dicts (empty = match).

    Compares recursively. Float values are compared with a small tolerance to
    accommodate minor floating-point differences across hardware.
    """
    diffs: list[str] = []
    if type(fresh) is not type(committed):
        diffs.append(f"{path}: type mismatch {type(fresh).__name__} vs {type(committed).__name__}")
        return diffs

    if isinstance(fresh, dict):
        all_keys = set(fresh) | set(committed)
        for k in sorted(all_keys):
            sub = f"{path}.{k}" if path else k
            if k not in committed:
                diffs.append(f"{sub}: key present in fresh but missing from committed")
            elif k not in fresh:
                diffs.append(f"{sub}: key present in committed but missing from fresh")
            else:
                diffs.extend(_compare_packets(fresh[k], committed[k], sub))
    elif isinstance(fresh, list):
        if len(fresh) != len(committed):
            diffs.append(f"{path}: list length {len(fresh)} vs {len(committed)}")
        else:
            for i, (f_item, c_item) in enumerate(zip(fresh, committed, strict=True)):
                diffs.extend(_compare_packets(f_item, c_item, f"{path}[{i}]"))
    elif isinstance(fresh, float) and isinstance(committed, float):
        if abs(fresh - committed) > 0.01:
            diffs.append(f"{path}: float {fresh} vs {committed}")
    else:
        if fresh != committed:
            # For long strings, show a short excerpt rather than the full value.
            if isinstance(fresh, str) and len(fresh) > 120:
                diffs.append(
                    f"{path}: string content differs (len {len(fresh)} vs {len(committed)})"
                )
            else:
                diffs.append(f"{path}: {fresh!r} vs {committed!r}")

    return diffs


def validate_packet_schema(data: dict) -> list[str]:
    """Return a list of schema violations (empty = valid)."""
    errors: list[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    require(isinstance(data.get("schema_version"), int), "schema_version must be int")
    require(
        data.get("schema_version") == SCHEMA_VERSION, f"schema_version must be {SCHEMA_VERSION}"
    )
    require(isinstance(data.get("generated_from"), str), "generated_from must be str")

    fixture = data.get("fixture", {})
    require(isinstance(fixture, dict), "fixture must be dict")
    require(isinstance(fixture.get("files"), list), "fixture.files must be list")
    require(len(fixture.get("files", [])) > 0, "fixture.files must be non-empty")

    exhibits = data.get("exhibits", {})
    require(isinstance(exhibits, dict), "exhibits must be dict")
    require("mine_output" in exhibits, "exhibits.mine_output must be present")

    sq = exhibits.get("search_queries", [])
    require(isinstance(sq, list) and len(sq) > 0, "exhibits.search_queries must be non-empty")
    for i, q in enumerate(sq):
        require(isinstance(q.get("query"), str), f"search_queries[{i}].query must be str")
        require(
            isinstance(q.get("expected_file"), str),
            f"search_queries[{i}].expected_file must be str",
        )
        require(isinstance(q.get("top_hits"), list), f"search_queries[{i}].top_hits must be list")

    re_ex = exhibits.get("read_exhibit", {})
    require(isinstance(re_ex, dict), "exhibits.read_exhibit must be dict")
    require(isinstance(re_ex.get("command"), str), "read_exhibit.command must be str")
    require(isinstance(re_ex.get("output"), str), "read_exhibit.output must be str")

    mcp = exhibits.get("mcp_exhibit", {})
    require(isinstance(mcp, dict), "exhibits.mcp_exhibit must be dict")
    for key in ("initialize", "tools_list", "code_search"):
        require(key in mcp, f"mcp_exhibit.{key} must be present")
        ex = mcp.get(key, {})
        require(isinstance(ex.get("request"), dict), f"mcp_exhibit.{key}.request must be dict")
        require(isinstance(ex.get("response"), dict), f"mcp_exhibit.{key}.response must be dict")

    return errors


# ── Fixture and palace helpers ─────────────────────────────────────────────────


def create_fixture_project(fixture_dir: Path) -> None:
    """Write the synthetic polyglot fixture project into fixture_dir."""
    for rel_path, content in _FIXTURE_FILES.items():
        dest = fixture_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def _make_env(extra: dict | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(_OFFLINE_ENV)
    if extra:
        env.update(extra)
    return env


def _run_cli(args: list[str], env: dict | None = None, timeout: int = 120) -> str:
    """Run mempalace-code via Python module and return combined stdout+stderr."""
    cmd = [_PYTHON, "-m", "mempalace_code.cli"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env or _make_env(),
        timeout=timeout,
    )
    # Combine stdout and stderr (the CLI mixes progress to both).
    output = result.stdout
    if result.stderr:
        # Filter out pure noise lines that do NOT help the exhibit.
        stderr_lines = [
            ln
            for ln in result.stderr.splitlines()
            if not any(
                noise in ln
                for noise in (
                    "INFO:mempalace_mcp",
                    "MemPalace MCP Server",
                    "huggingface/tokenizers",
                )
            )
        ]
        if stderr_lines:
            output += "\n".join(stderr_lines)
    return output


# ── MCP exhibit ────────────────────────────────────────────────────────────────


def _mcp_exchange(palace_dir: Path) -> dict:
    """Run a minimal MCP stdio exchange and return normalized request/response pairs.

    Spawns python -m mempalace_code.mcp_server --profile code with HOME pointed
    at a temp dir containing config.json that maps to palace_dir. Sends three
    JSON-RPC requests and collects responses.
    """
    # Write a temp HOME with config.json pointing to the mined palace.
    mcp_home = palace_dir.parent / "mcp_home"
    mcp_home.mkdir(exist_ok=True)
    palace_cfg = mcp_home / ".mempalace"
    palace_cfg.mkdir(exist_ok=True)
    config_data = {"palace_path": str(palace_dir)}
    (palace_cfg / "config.json").write_text(json.dumps(config_data), encoding="utf-8")

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "exhibit", "version": "1.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "mempalace_code_search",
                "arguments": {"query": "hash password authentication", "n_results": 3},
            },
        },
    ]

    stdin_data = "\n".join(json.dumps(req) for req in requests) + "\n"

    # Preserve the real HuggingFace model cache while redirecting HOME so the
    # MCP server finds the mined palace config but still loads the cached model.
    # HF_HUB_CACHE must point to the hub/ subdirectory (not the parent).
    real_home = os.path.expanduser("~")
    real_hf_hub_cache = os.path.join(real_home, ".cache", "huggingface", "hub")
    mcp_env = _make_env(
        {
            "HOME": str(mcp_home),
            "USERPROFILE": str(mcp_home),
            "HF_HUB_CACHE": real_hf_hub_cache,
        }
    )

    proc = subprocess.run(
        [_PYTHON, "-m", "mempalace_code.mcp_server", "--profile", "code"],
        input=stdin_data,
        capture_output=True,
        text=True,
        env=mcp_env,
        timeout=60,
    )

    responses = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    if len(responses) < 3:
        raise RuntimeError(
            f"MCP exchange returned {len(responses)} responses, expected 3. "
            f"stdout={proc.stdout!r}, stderr={proc.stderr!r}"
        )

    return {
        "initialize": {"request": requests[0], "response": responses[0]},
        "tools_list": {"request": requests[1], "response": responses[1]},
        "code_search": {"request": requests[2], "response": responses[2]},
    }


def _normalize_mcp_exhibit(exhibit: dict, palace_dir_str: str, fixture_dir_str: str) -> dict:
    """Normalize MCP exhibit: strip paths and simplify tools/list to just names."""
    normalized = json.loads(json.dumps(exhibit))
    palace_real = os.path.realpath(palace_dir_str)
    fixture_real = os.path.realpath(fixture_dir_str)

    # In tools/list: keep only tool names (the input_schema is very verbose).
    tl_result = normalized.get("tools_list", {}).get("response", {}).get("result", {})
    if "tools" in tl_result:
        tl_result["tools"] = sorted(t["name"] for t in tl_result["tools"])

    # In code_search result: normalize source_file paths, round similarity.
    cs_result = normalized.get("code_search", {}).get("response", {}).get("result", {})
    if "content" in cs_result:
        for item in cs_result["content"]:
            if isinstance(item.get("text"), str):
                try:
                    payload = json.loads(item["text"])
                    if isinstance(payload.get("results"), list):
                        for hit in payload["results"]:
                            if "source_file" in hit:
                                src = hit["source_file"]
                                src = src.replace(fixture_real, "<FIXTURE_DIR>")
                                src = src.replace(palace_real, "<PALACE_DIR>")
                                src = src.replace(fixture_dir_str, "<FIXTURE_DIR>")
                                src = src.replace(palace_dir_str, "<PALACE_DIR>")
                                hit["source_file"] = src
                            if "similarity" in hit:
                                hit["similarity"] = round(hit["similarity"], 2)
                            if "text" in hit:
                                hit["text"] = (
                                    hit["text"][:200] + "…"
                                    if len(hit.get("text", "")) > 200
                                    else hit["text"]
                                )
                    item["text"] = json.dumps(payload, ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass

    # Strip serverInfo version (changes across releases).
    init_result = normalized.get("initialize", {}).get("response", {}).get("result", {})
    if "serverInfo" in init_result:
        init_result["serverInfo"]["version"] = "<VERSION>"

    return normalized


# ── Search exhibit helpers ─────────────────────────────────────────────────────


def _run_search_exhibit(
    query: str,
    expected_file: str,
    label: str,
    palace_dir: Path,
    fixture_dir: Path,
    wing: str,
) -> dict:
    """Run one CLI search exhibit and return the exhibit dict with normalization."""
    cmd_args = [
        "--palace",
        str(palace_dir),
        "search",
        query,
        "--wing",
        wing,
        "--results",
        "5",
    ]
    cli_output = _run_cli(cmd_args)
    normalized = normalize_output(cli_output, str(fixture_dir), str(palace_dir))

    # Also collect structured search results for known-answer validation.
    structured = _run_structured_search(query, palace_dir, wing)
    check_known_answer(structured, expected_file, query)

    # Extract top hits for the packet (normalize paths, resolve macOS /var aliases).
    fixture_real = os.path.realpath(str(fixture_dir))
    top_hits = [
        {
            "source_file": h["source_file"]
            .replace(fixture_real, "<FIXTURE_DIR>")
            .replace(str(fixture_dir), "<FIXTURE_DIR>"),
            "symbol_name": h.get("symbol_name", ""),
            "similarity": round(h.get("similarity", 0.0), 2),
        }
        for h in structured.get("results", [])[:_KNOWN_ANSWER_TOP_N]
    ]

    return {
        "label": label,
        "query": query,
        "command": f"mempalace-code search {query!r} --wing {wing} --results 5",
        "expected_file": expected_file,
        "top_hits": top_hits,
        "output": normalized,
    }


def _run_structured_search(query: str, palace_dir: Path, wing: str) -> dict:
    """Return structured search results dict (for known-answer validation)."""
    from mempalace_code.searcher import code_search  # noqa: PLC0415

    return code_search(
        palace_path=str(palace_dir),
        query=query,
        wing=wing,
        n_results=_KNOWN_ANSWER_TOP_N + 2,
    )


# ── Packet rendering ───────────────────────────────────────────────────────────


def render_markdown(data: dict) -> str:
    """Render the packet dict to a human-readable Markdown document."""
    lines: list[str] = []
    fixture = data.get("fixture", {})
    exhibits = data.get("exhibits", {})

    lines.append("# Code-Intelligence Demo Packet")
    lines.append("")
    lines.append(
        "Deterministic, public-safe exhibit generated by "
        "`scripts/gen_code_intelligence_packet.py`. "
        "Regenerate with `python scripts/gen_code_intelligence_packet.py`. "
        "No timestamps, no absolute paths, no machine identifiers."
    )
    lines.append("")
    lines.append(f"Schema version: {data.get('schema_version', '?')}")
    lines.append("")

    # Fixture inventory
    lines.append("## 1. Fixture Inventory")
    lines.append("")
    lines.append(
        f"Synthetic polyglot project: **{fixture.get('wing', '?')}** "
        f"(`{fixture.get('description', '')}`)"
    )
    lines.append("")
    lines.append("| File | Language |")
    lines.append("|------|----------|")
    for f in fixture.get("files", []):
        ext = Path(f).suffix
        lang = {".py": "Python", ".md": "Markdown", ".yaml": "YAML", "": "Makefile"}.get(ext, ext)
        lines.append(f"| `{f}` | {lang} |")
    lines.append("")

    # Mine summary
    lines.append("### Mine Summary")
    lines.append("")
    lines.append("```")
    lines.append(exhibits.get("mine_output", ""))
    lines.append("```")
    lines.append("")

    # Known-answer search queries
    lines.append("## 2. Known-Answer Search Queries")
    lines.append("")
    for q in exhibits.get("search_queries", []):
        lines.append(f"### Query: `{q['query']}`")
        lines.append("")
        lines.append(f"**Command**: `{q['command']}`")
        lines.append(f"**Expected file in top-{_KNOWN_ANSWER_TOP_N}**: `{q['expected_file']}`")
        lines.append("")
        lines.append("**Top hits:**")
        for hit in q.get("top_hits", []):
            lines.append(
                f"- `{hit['source_file']}`"
                + (f" — `{hit['symbol_name']}`" if hit.get("symbol_name") else "")
                + f" (sim={hit.get('similarity', '?')})"
            )
        lines.append("")
        lines.append("<details><summary>Full CLI output</summary>")
        lines.append("")
        lines.append("```")
        lines.append(q.get("output", ""))
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Read exhibit
    re_ex = exhibits.get("read_exhibit", {})
    lines.append("## 3. Source Slice (Read Exhibit)")
    lines.append("")
    lines.append(f"**Command**: `{re_ex.get('command', '')}`")
    lines.append("")
    lines.append("```")
    lines.append(re_ex.get("output", ""))
    lines.append("```")
    lines.append("")

    # MCP exhibit
    mcp = exhibits.get("mcp_exhibit", {})
    lines.append("## 4. MCP stdio Exhibit (code profile)")
    lines.append("")
    lines.append(
        "Three JSON-RPC exchanges with `python -m mempalace_code.mcp_server --profile code`."
    )
    lines.append("")

    for key, label in (
        ("initialize", "4.1 initialize"),
        ("tools_list", "4.2 tools/list"),
        ("code_search", "4.3 tools/call — mempalace_code_search"),
    ):
        ex = mcp.get(key, {})
        lines.append(f"### {label}")
        lines.append("")
        lines.append("**Request:**")
        lines.append("```json")
        lines.append(json.dumps(ex.get("request", {}), indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
        lines.append("**Response:**")
        lines.append("```json")
        lines.append(json.dumps(ex.get("response", {}), indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    return "\n".join(lines) + "\n"


def render_json(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ── Main generation pipeline ───────────────────────────────────────────────────


def generate_packet(
    output_dir: Path | None = None,
    wing: str = "calcdemo",
) -> dict:
    """Build the fixture, mine it, capture exhibits, and return the packet dict.

    If output_dir is None, writes to docs/demo/. Otherwise writes to output_dir.
    Returns the packet data dict.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="mempalace_packet_"))
    try:
        fixture_dir = work_dir / "fixture"
        palace_dir = work_dir / "palace"
        fixture_dir.mkdir()
        palace_dir.mkdir()

        print("  Creating fixture project...", flush=True)
        create_fixture_project(fixture_dir)

        # ── Mine ──────────────────────────────────────────────────────────────
        print("  Mining fixture...", flush=True)
        mine_output_raw = _run_cli(
            [
                "--palace",
                str(palace_dir),
                "mine",
                str(fixture_dir),
                "--wing",
                wing,
                "--full",
            ]
        )
        mine_output = normalize_output(mine_output_raw, str(fixture_dir), str(palace_dir))

        # Extract mine summary counts from raw output.
        files_match = re.search(r"Files processed:\s+(\d+)", mine_output_raw)
        drawers_match = re.search(r"Drawers filed:\s+(\d+)", mine_output_raw)
        mine_summary = {
            "wing": wing,
            "files_processed": int(files_match.group(1)) if files_match else 0,
            "drawers_filed": int(drawers_match.group(1)) if drawers_match else 0,
        }

        # ── Known-answer search queries ───────────────────────────────────────
        print("  Running known-answer search queries...", flush=True)
        search_exhibits = []
        for query, expected_file, label in KNOWN_ANSWER_QUERIES:
            print(f"    {label}: {query!r}", flush=True)
            ex = _run_search_exhibit(query, expected_file, label, palace_dir, fixture_dir, wing)
            search_exhibits.append(ex)

        # ── Read exhibit ──────────────────────────────────────────────────────
        print("  Running read exhibit...", flush=True)
        read_file = str(fixture_dir / "src" / "auth.py")
        read_cmd_args = [
            "--palace",
            str(palace_dir),
            "read",
            read_file,
            "--start",
            "1",
            "--end",
            "25",
            "--wing",
            wing,
        ]
        read_output_raw = _run_cli(read_cmd_args)
        read_output = normalize_output(read_output_raw, str(fixture_dir), str(palace_dir))
        read_cmd_display = (
            f"mempalace-code read <FIXTURE_DIR>/src/auth.py --start 1 --end 25 --wing {wing}"
        )

        # ── MCP exhibit ───────────────────────────────────────────────────────
        print("  Running MCP stdio exhibit...", flush=True)
        mcp_raw = _mcp_exchange(palace_dir)
        mcp_exhibit = _normalize_mcp_exhibit(mcp_raw, str(palace_dir), str(fixture_dir))

        # ── Assemble packet ───────────────────────────────────────────────────
        packet = {
            "schema_version": SCHEMA_VERSION,
            "generated_from": "scripts/gen_code_intelligence_packet.py",
            "fixture": {
                "description": (
                    "synthetic polyglot project: Python source, Markdown docs, YAML config, Makefile"
                ),
                "wing": wing,
                "files": sorted(_FIXTURE_FILES.keys()),
                "mine_summary": mine_summary,
            },
            "exhibits": {
                "mine_output": mine_output,
                "search_queries": search_exhibits,
                "read_exhibit": {
                    "command": read_cmd_display,
                    "output": read_output,
                },
                "mcp_exhibit": mcp_exhibit,
            },
        }

        # ── Public-safety check ───────────────────────────────────────────────
        packet_json_str = render_json(packet)
        _public_safety_check(packet_json_str)

        # ── Write artifacts ───────────────────────────────────────────────────
        dest = output_dir or PACKET_DIR
        dest.mkdir(parents=True, exist_ok=True)

        (dest / "code-intelligence-packet.json").write_text(packet_json_str, encoding="utf-8")
        (dest / "code-intelligence-packet.md").write_text(render_markdown(packet), encoding="utf-8")

        return packet

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Check mode ─────────────────────────────────────────────────────────────────


def check_mode() -> int:
    """Regenerate packet into a temp dir and compare with committed artifacts.

    Returns 0 on success, 1 on failure.
    """
    if not PACKET_JSON.exists():
        print(f"  FAIL: committed artifact not found: {PACKET_JSON}", file=sys.stderr)
        return 1
    if not PACKET_MD.exists():
        print(f"  FAIL: committed artifact not found: {PACKET_MD}", file=sys.stderr)
        return 1

    committed_json_str = PACKET_JSON.read_text(encoding="utf-8")
    try:
        committed_data = json.loads(committed_json_str)
    except json.JSONDecodeError as exc:
        print(f"  FAIL: committed JSON is not valid: {exc}", file=sys.stderr)
        return 1

    # Schema validation on committed artifact.
    schema_errors = validate_packet_schema(committed_data)
    if schema_errors:
        print("  FAIL: schema errors in committed artifact:", file=sys.stderr)
        for err in schema_errors:
            print(f"    - {err}", file=sys.stderr)
        return 1

    # Public-safety on committed artifact.
    try:
        _public_safety_check(committed_json_str)
        _public_safety_check(PACKET_MD.read_text(encoding="utf-8"))
    except PublicSafetyError as exc:
        print(f"  FAIL: {exc}", file=sys.stderr)
        return 1

    # Regenerate and compare.
    print("  Regenerating packet for comparison...", flush=True)
    fresh_dir = Path(tempfile.mkdtemp(prefix="mempalace_check_"))
    try:
        fresh_data = generate_packet(output_dir=fresh_dir)
        diffs = _compare_packets(fresh_data, committed_data)
        if diffs:
            print("  FAIL: fresh packet differs from committed:", file=sys.stderr)
            for diff in diffs[:20]:
                print(f"    - {diff}", file=sys.stderr)
            if len(diffs) > 20:
                print(f"    ... and {len(diffs) - 20} more", file=sys.stderr)
            return 1
        print("  OK: committed artifacts match fresh generation.")
        return 0
    finally:
        shutil.rmtree(fresh_dir, ignore_errors=True)


# ── CLI entry point ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or validate the code-intelligence demo packet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate committed artifacts: regenerate and compare. "
            "Requires the embedding model to be cached. Takes 20-60s."
        ),
    )
    args = parser.parse_args(argv)

    if args.check:
        return check_mode()

    print("Generating code-intelligence packet...", flush=True)
    try:
        packet = generate_packet()
        ms = packet["fixture"]["mine_summary"]
        sq = packet["exhibits"]["search_queries"]
        print(
            f"  Done. "
            f"Files={ms['files_processed']}, "
            f"Drawers={ms['drawers_filed']}, "
            f"Queries={len(sq)}"
        )
        print(f"  Written to {PACKET_DIR}/")
        return 0
    except KnownAnswerError as exc:
        print(f"  FAIL: {exc}", file=sys.stderr)
        return 1
    except PublicSafetyError as exc:
        print(f"  FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"  FAIL: unexpected error: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.exit(main())
