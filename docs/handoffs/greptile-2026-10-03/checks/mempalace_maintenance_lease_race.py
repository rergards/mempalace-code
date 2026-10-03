"""Check actual lease exclusion with isolated lock paths and two threads."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = args.source / "mempalace_code/operation_lock.py"
    spec = importlib.util.spec_from_file_location("audited_operation_lock", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.fcntl is None:
        print(json.dumps({"result": "unsupported platform"}))
        return 2
    with tempfile.TemporaryDirectory(prefix="mempalace-lease-race-") as folder:
        root = Path(folder)
        install = module.OperationLock(root / "install.lock")
        module.OperationLock.default = classmethod(lambda cls: install)
        module.OperationLock.for_palace = classmethod(
            lambda cls, palace: module.OperationLock(root / "palace.lock")
        )
        entered = threading.Event()
        errors = []
        control = []

        def direct_shared():
            try:
                with install.acquire_shared("control", wait=0):
                    control.append("entered")
            except module.OperationLockedError:
                control.append("blocked")

        def writer():
            try:
                with module.palace_write_lease(str(root / "palace"), "writer", wait=0):
                    entered.set()
            except module.OperationLockedError:
                errors.append("blocked")

        with install.acquire_exclusive("maintenance"):
            direct = threading.Thread(target=direct_shared, daemon=True)
            direct.start()
            direct.join(timeout=3)
            thread = threading.Thread(target=writer, daemon=True)
            thread.start()
            thread.join(timeout=3)
            completed = not direct.is_alive() and not thread.is_alive()
            overlap = entered.is_set()
        print(json.dumps({
            "direct_shared": control,
            "palace_write_entered_during_maintenance": overlap,
            "writer_errors": errors,
            "threads_completed": completed,
        }))
        if not completed or control != ["blocked"]:
            return 2
        if overlap:
            return 1
        return 0 if errors == ["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
