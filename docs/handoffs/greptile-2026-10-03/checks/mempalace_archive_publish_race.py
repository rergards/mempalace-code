"""Reproduce archive replacement using the actual owner and disposable files."""
import argparse
import ast
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = args.source / "mempalace_code/backup.py"
    content = source.read_bytes()
    owner = next(
        node for node in ast.parse(content).body
        if isinstance(node, ast.FunctionDef) and node.name == "_publish_new_file"
    )
    with tempfile.TemporaryDirectory(prefix="mempalace-archive-race-") as folder:
        root = Path(folder)
        temporary, archive = root / "temporary", root / "archive.tar.gz"
        temporary.write_bytes(b"new archive")
        observed = []

        def no_hard_link(*_):
            raise OSError(errno.EOPNOTSUPP, "controlled hard-link refusal")

        def concurrent_creation(path):
            present = os.path.lexists(path)
            observed.append(present)
            Path(path).write_bytes(b"competing archive")
            return present

        proxy = SimpleNamespace(
            link=no_hard_link,
            path=SimpleNamespace(lexists=concurrent_creation),
            replace=os.replace,
            unlink=os.unlink,
        )
        scope = {"os": proxy, "errno": errno, "logger": logging.getLogger(__name__)}
        exec(compile(ast.Module(body=[owner], type_ignores=[]), str(source), "exec"), scope)
        error = None
        try:
            scope["_publish_new_file"](str(temporary), str(archive))
        except OSError as exc:
            error = type(exc).__name__
        actual = archive.read_bytes() if archive.exists() else None
        overwritten = observed == [False] and actual == b"new archive"
        print(json.dumps({
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "overwritten": overwritten,
            "error": error,
            "competitor_preserved": actual == b"competing archive",
            "race_injected": observed == [False],
        }))
        if overwritten:
            return 1
        return 0 if observed == [False] and actual == b"competing archive" else 2


if __name__ == "__main__":
    raise SystemExit(main())
