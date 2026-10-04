"""Compare actual indexing policy against equivalent parsed YAML with inert content."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    path = args.source / "mempalace_code/mining/source_text.py"
    spec = importlib.util.spec_from_file_location("audited_source_text", path)
    owner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = owner
    spec.loader.exec_module(owner)
    canonical = "apiVersion: v1\nkind: Secret\nmetadata:\n  name: inert-fixture\ndata:\n  example: ZGVtby12YWx1ZQ==\n"
    canonical_data = yaml.safe_load(canonical)
    control = owner.decode_source(canonical.encode(), "manifest.yaml")
    assert control.skip_reason == owner.SKIP_SECRET
    results = {}
    for label, text in {
        "spaced_kind": canonical.replace("kind:", "kind :"),
        "spaced_data": canonical.replace("data:\n  token", "data :\n  token"),
        "both_spaced": canonical.replace("kind:", "kind :").replace("data:\n  token", "data :\n  token"),
    }.items():
        assert yaml.safe_load(text) == canonical_data
        observed = owner.decode_source(text.encode(), "manifest.yaml")
        assert observed.skip_reason is None and observed.text == text
        results[label] = {"semanticYamlEquivalent": True, "skipReason": observed.skip_reason, "contentEligibleForIndex": True}
    assert owner.decode_source(canonical.encode(), "manifest.yaml", force_include=True).skip_reason is None
    ordinary = canonical.replace("kind: Secret", "kind: ConfigMap")
    assert owner.decode_source(ordinary.encode(), "manifest.yaml").skip_reason is None
    print(json.dumps({"defectReproduced": True, "parserVersion": yaml.__version__, "canonicalControl": control.skip_reason, "cases": results, "forceIncludeControl": "preserved", "configMapControl": "indexable"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
