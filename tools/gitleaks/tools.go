//go:build tools

// Package tools pins the Gitleaks CLI that scripts/gitleaks_scan.py shells out to.
//
// The blank import keeps github.com/zricethezav/gitleaks/v8 a *direct* requirement
// of this module, so `go.sum` locks the exact module checksums and Dependabot's
// gomod ecosystem (.github/dependabot.yml) can open version-bump pull requests.
// CI installs the binary with `go install github.com/zricethezav/gitleaks/v8`
// from this directory, which resolves the version from go.mod — never a mutable
// `@tag` reference typed into a workflow.
package tools

import _ "github.com/zricethezav/gitleaks/v8/cmd"
