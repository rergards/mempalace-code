//go:build tools

// Package tools pins the Gitleaks CLI and its audited security dependencies.
//
// The blank import keeps github.com/zricethezav/gitleaks/v8 a *direct* requirement
// of this module, so `go.sum` locks the exact module checksums and Dependabot's
// gomod ecosystem (.github/dependabot.yml) can open version-bump pull requests.
// The security imports retain intentional minimum versions during go mod tidy,
// including dependencies that the current scanner does not import itself.
// CI installs the binary with `go install github.com/zricethezav/gitleaks/v8`
// from this directory, which resolves the version from go.mod — never a mutable
// `@tag` reference typed into a workflow.
package tools

import (
	_ "github.com/go-jose/go-jose/v4"
	_ "github.com/zricethezav/gitleaks/v8/cmd"
	_ "go.opentelemetry.io/otel"
	_ "go.opentelemetry.io/otel/sdk/trace"
	_ "golang.org/x/net/http2"
	_ "google.golang.org/grpc"
)
