---
name: release
description: Prepare and publish a PyPI release - version bump, changelog, tag, publish
disable-model-invocation: false
---

# Release Workflow

Prepare and optionally publish a new version to PyPI.

## When to Use

- Ready to cut a new release
- After completing a set of features
- User says "release", "publish", "bump version"

## Steps

### Step 1: Pre-flight Check

Run `/verify` to ensure all tests pass.

Check current version:

```bash
grep -E "^version\s*=" pyproject.toml
git tag --list 'v*' | tail -5
```

### Step 2: Determine Version Bump

Based on changes since last release:

| Change Type | Version Bump |
|-------------|--------------|
| Breaking changes (API, CLI, storage format) | Major (X.0.0) |
| New features (languages, MCP tools) | Minor (0.X.0) |
| Bug fixes, docs, internal | Patch (0.0.X) |

Ask user to confirm version if unclear.

### Step 3: Update Version

Edit `pyproject.toml`:

```bash
# Example: bump to 1.1.0
sed -i '' 's/^version = .*/version = "1.1.0"/' pyproject.toml
```

### Step 4: Update Changelog

Add entry to `CHANGELOG.md` with today's date:

```markdown
## vX.Y.Z — YYYY-MM-DD

### Added
- ...

### Fixed
- ...

### Changed
- ...
```

### Step 5: Commit Release

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release vX.Y.Z"
```

### Step 6: Tag

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

### Step 7: Push (with user confirmation)

**Ask user before pushing:**

```
Ready to push release vX.Y.Z to origin?
- git push origin main
- git push origin vX.Y.Z

Proceed? [y/n]
```

### Step 8: Publish to PyPI (with user confirmation)

**Ask user before publishing:**

```
Ready to publish vX.Y.Z to PyPI?
- Requires: TWINE_USERNAME/TWINE_PASSWORD or ~/.pypirc

Command: python -m build && twine upload dist/*

Proceed? [y/n]
```

If user confirms:

```bash
rm -rf dist/ build/
python -m build
twine upload dist/* --repository publish
```

Note: Uses `publish` remote per project feedback.

## Output

```
## Release vX.Y.Z

Version: X.Y.Z
Tag: vX.Y.Z
Pushed: [yes/no]
Published: [yes/no/skipped]

Next steps:
- [any remaining manual steps]
```
