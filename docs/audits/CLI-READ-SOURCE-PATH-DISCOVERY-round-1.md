slug: CLI-READ-SOURCE-PATH-DISCOVERY
round: 1
date: 2026-05-24
commit_range: 4a7cdce..HEAD
findings:
  - id: F-1
    title: "not_found errors after successful resolution report original query instead of canonical path"
    severity: medium
    location: "mempalace_code/reader.py:184,187"
    claim: >
      After _resolve_source_file() returns a canonical stored path, the store.get() exception
      handler and the empty-results guard both returned {"error": "not_found", "source_file":
      source_file} using the original user-typed query rather than the resolved canonical path.
      This means a user who typed "auth.py" and had it resolve to "/project/src/auth.py" would
      see "Not found: no palace chunks for 'auth.py'" instead of the canonical path, making it
      impossible to distinguish a failed resolution from a resolved-but-missing chunk.
    decision: fixed
    fix: >
      Changed both not_found returns in the post-resolution block to use `canonical` instead of
      `source_file`: lines 184 and 187 now carry the resolved canonical path in the error dict.

  - id: F-2
    title: "alias_matches > 1 branch is unreachable dead code"
    severity: info
    location: "mempalace_code/reader.py:123"
    claim: >
      After the exact-match check in step 1 of _resolve_source_file(), source_file is known to
      not be in candidates. _macos_var_aliases() returns at most {source_file, alias}, and since
      source_file is already excluded from candidates, alias_matches can have at most one element.
      The `if len(alias_matches) > 1` branch can never be entered.
    decision: dismissed
    fix: ""

  - id: F-3
    title: "CLI not_found handler uses args.source_file instead of result source_file"
    severity: low
    location: "mempalace_code/cli_commands/query.py:176"
    claim: >
      The not_found handler printed args.source_file directly, inconsistent with the stale_pointer
      handler which uses result.get('source_file', args.source_file). After fix F-1, the not_found
      result now carries the canonical path; the CLI must read it from the result dict so the user
      sees the resolved canonical path in the error message.
    decision: fixed
    fix: >
      Changed the not_found print to use result.get('source_file', args.source_file), consistent
      with the stale_pointer handler pattern.

  - id: F-4
    title: "Weak assertions in basename and suffix discovery CLI tests"
    severity: low
    location: "tests/test_cli.py:2143,2171"
    claim: >
      test_read_command_source_path_discovery_unique_basename asserted only `"login" in out`,
      which would pass even if the line number or format was wrong. Similarly the suffix test
      asserted only `"authenticate" in out`. Neither test verified the numbered line format
      produced by cmd_read (`{line:6}: {text}`).
    decision: fixed
    fix: >
      Strengthened basename assertion to `"     1: def login(): pass" in out`. Strengthened
      suffix assertions to check both numbered lines: `"     1: def authenticate(user): validate"`
      and `"     2: def authorize(user): check role"`.

totals:
  fixed: 3
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "reader.py: not_found error dicts after successful resolution now carry canonical path"
  - "query.py: not_found CLI handler reads source_file from result dict like stale_pointer handler"
  - "tests/test_cli.py: basename and suffix discovery tests assert exact numbered-line format"

new_backlog: []
