#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/codex-review.sh [--dry-run] [--show-output] plan <task-slug> [plan-file]
  ./scripts/codex-review.sh [--dry-run] [--show-output] hardening <task-slug> "<feature name>" "<feature scope>" <round>
  ./scripts/codex-review.sh [--dry-run] [--show-output] entropy <task-slug> <report-file> "<scope>"

Modes:
  plan       Run Codex headless against an implementation plan and save evidence under .tasks/TASK-<slug>/
  hardening  Run Codex headless against a task-scoped diff and save evidence under .tasks/TASK-<slug>/
  entropy    Run Codex headless to validate an entropy-gc report and save evidence under .tasks/TASK-<slug>/

Notes:
  - The wrapper runs Codex in read-only, ephemeral mode.
  - Outputs are supporting evidence for Claude, not canonical repo artifacts.
  - If Codex returns 401/Missing bearer auth, run: codex login
  - --show-output prints the saved report contents after a successful run
  - Hardening prefers `.tasks/TASK-<slug>/codex-hardening-files.txt` or staged changes as explicit scope.
EOF
}

escape_sed() {
  printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g'
}

render_template() {
  local template_file="$1"
  shift
  local rendered
  rendered=$(cat "$template_file")
  while [ "$#" -gt 1 ]; do
    local key="$1"
    local value="$2"
    shift 2
    rendered=$(printf '%s' "$rendered" | sed -e "s|${key}|$(escape_sed "$value")|g")
  done
  printf '%s\n' "$rendered"
}

relative_repo_path() {
  local path="$1"
  if [[ "$path" == "$REPO_ROOT/"* ]]; then
    printf '%s\n' "${path#$REPO_ROOT/}"
  else
    printf '%s\n' "$path"
  fi
}

run_codex() {
  local stderr_file="$1"
  shift
  if ! "$@" 2>"$stderr_file"; then
    if [ -s "$stderr_file" ]; then
      cat "$stderr_file" >&2
    fi
    if grep -Eq '401 Unauthorized|Missing bearer or basic authentication' "$stderr_file"; then
      echo "Codex CLI is not authenticated. Run: codex login" >&2
    fi
    return 1
  fi
  if [ -s "$stderr_file" ]; then
    cat "$stderr_file" >&2
  fi
}

setup_codex_home() {
  local base_codex_home
  local real_codex_home

  base_codex_home="${CODEX_HOME:-${TMPDIR:-/tmp}/codex-home}"
  CODEX_HOME_RUN="$(mktemp -d "${base_codex_home}.XXXXXX")"
  export CODEX_HOME="$CODEX_HOME_RUN"

  mkdir -p "$CODEX_HOME"
  real_codex_home="${HOME}/.codex"
  if [ -f "$real_codex_home/auth.json" ]; then
    ln -sf "$real_codex_home/auth.json" "$CODEX_HOME/auth.json"
  fi
}

is_ignored_hardening_path() {
  local path="$1"
  case "$path" in
    .tasks/*|.protocols/*|docs/audits/*|docs/plans/*)
      return 0
      ;;
  esac
  return 1
}

append_unique_path() {
  local output_file="$1"
  local raw_path="$2"
  local path="${raw_path%$'\r'}"
  path="${path#./}"
  path="${path%%[[:space:]]}"
  if [ -z "$path" ]; then
    return
  fi
  if is_ignored_hardening_path "$path"; then
    return
  fi
  if ! grep -Fxq "$path" "$output_file" 2>/dev/null; then
    printf '%s\n' "$path" >> "$output_file"
  fi
}

append_filtered_paths_from_file() {
  local input_file="$1"
  local output_file="$2"
  if [ ! -f "$input_file" ]; then
    return
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      ""|\#*)
        continue
        ;;
    esac
    append_unique_path "$output_file" "$line"
  done < "$input_file"
}

collect_current_changed_files() {
  local output_file="$1"
  local tracked_file untracked_file
  tracked_file="$(mktemp)"
  untracked_file="$(mktemp)"
  trap 'rm -f "$tracked_file" "$untracked_file"' RETURN
  : > "$output_file"
  git diff --name-only --relative HEAD -- > "$tracked_file" || true
  git ls-files --others --exclude-standard > "$untracked_file" || true
  append_filtered_paths_from_file "$tracked_file" "$output_file"
  append_filtered_paths_from_file "$untracked_file" "$output_file"
  rm -f "$tracked_file" "$untracked_file"
  trap - RETURN
}

collect_staged_changed_files() {
  local output_file="$1"
  local staged_file
  staged_file="$(mktemp)"
  trap 'rm -f "$staged_file"' RETURN
  : > "$output_file"
  git diff --cached --name-only --relative -- > "$staged_file" || true
  append_filtered_paths_from_file "$staged_file" "$output_file"
  rm -f "$staged_file"
  trap - RETURN
}

write_skip_report() {
  local reason="$1"
  local details="$2"
  {
    echo "Status: SKIPPED"
    echo
    echo "Reason: $reason"
    echo
    echo "Details:"
    printf '%s\n' "$details"
  } > "$OUTPUT_FILE"
  echo "Skipped Codex review: $reason"
  if [ "$SHOW_OUTPUT" -eq 1 ] && [ -s "$OUTPUT_FILE" ]; then
    echo "--- Codex Review Output ---"
    cat "$OUTPUT_FILE"
  fi
}

prepare_hardening_scope() {
  local current_changed_file staged_changed_file
  current_changed_file="$(mktemp)"
  staged_changed_file="$(mktemp)"
  trap 'rm -f "$current_changed_file" "$staged_changed_file"' RETURN

  collect_current_changed_files "$current_changed_file"
  collect_staged_changed_files "$staged_changed_file"

  : > "$ROUND_SCOPE_FILE"

  if [ -f "$EXPLICIT_SCOPE_FILE" ] && [ -s "$EXPLICIT_SCOPE_FILE" ]; then
    append_filtered_paths_from_file "$EXPLICIT_SCOPE_FILE" "$ROUND_SCOPE_FILE"
    SCOPE_SOURCE="explicit scope manifest"
  elif [ -s "$staged_changed_file" ]; then
    append_filtered_paths_from_file "$staged_changed_file" "$ROUND_SCOPE_FILE"
    SCOPE_SOURCE="staged diff"
  elif [ -s "$current_changed_file" ]; then
    append_filtered_paths_from_file "$current_changed_file" "$ROUND_SCOPE_FILE"
    SCOPE_SOURCE="current working tree"
  else
    write_skip_report \
      "No current source diff is available for Codex hardening." \
      "- The working tree has no changed source files."
    rm -f "$current_changed_file" "$staged_changed_file"
    trap - RETURN
    return 1
  fi

  # Generate scoped diff
  : > "$SCOPED_DIFF_FILE"
  if [ ! -s "$ROUND_SCOPE_FILE" ]; then
    write_skip_report \
      "No task-scoped files were selected for Codex hardening." \
      "- Scope source: $SCOPE_SOURCE"
    rm -f "$current_changed_file" "$staged_changed_file"
    trap - RETURN
    return 1
  fi

  local -a scope_args
  scope_args=()
  while IFS= read -r path || [ -n "$path" ]; do
    scope_args+=("$path")
  done < "$ROUND_SCOPE_FILE"

  if [ "$SCOPE_SOURCE" = "staged diff" ]; then
    git diff --cached --relative -- "${scope_args[@]}" > "$SCOPED_DIFF_FILE" || true
  else
    git diff --relative HEAD -- "${scope_args[@]}" > "$SCOPED_DIFF_FILE" || true
  fi

  if [ ! -s "$SCOPED_DIFF_FILE" ]; then
    write_skip_report \
      "No task-scoped diff was found for Codex hardening." \
      "- Scope source: $SCOPE_SOURCE"
    rm -f "$current_changed_file" "$staged_changed_file"
    trap - RETURN
    return 1
  fi

  rm -f "$current_changed_file" "$staged_changed_file"
  trap - RETURN
  return 0
}

DRY_RUN=0
SHOW_OUTPUT=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --show-output)
      SHOW_OUTPUT=1
      shift
      ;;
    *)
      break
      ;;
  esac
done

MODE="${1:-}"
if [ -z "$MODE" ]; then
  usage
  exit 1
fi
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROMPTS_DIR="$REPO_ROOT/.claude/prompts"

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH." >&2
  exit 1
fi

export OTEL_SDK_DISABLED="${OTEL_SDK_DISABLED:-true}"
export NO_COLOR="${NO_COLOR:-1}"
CODEX_HOME_RUN=""
setup_codex_home

case "$MODE" in
  plan)
    TASK_SLUG="${1:-}"
    PLAN_FILE="${2:-}"
    if [ -z "$TASK_SLUG" ]; then
      usage
      exit 1
    fi
    if [ -z "$PLAN_FILE" ]; then
      PLAN_FILE="$REPO_ROOT/docs/plans/$TASK_SLUG.md"
    elif [[ "$PLAN_FILE" != /* ]]; then
      PLAN_FILE="$REPO_ROOT/$PLAN_FILE"
    fi
    if [ ! -f "$PLAN_FILE" ]; then
      echo "Plan file not found: $PLAN_FILE" >&2
      exit 1
    fi

    TASK_DIR="$REPO_ROOT/.tasks/TASK-$TASK_SLUG"
    OUTPUT_FILE="$TASK_DIR/codex-plan-review.md"
    TEMPLATE_FILE="$PROMPTS_DIR/codex-plan-review.md"
    mkdir -p "$TASK_DIR"
    ;;
  hardening)
    TASK_SLUG="${1:-}"
    FEATURE_NAME="${2:-}"
    FEATURE_SCOPE="${3:-}"
    ROUND="${4:-}"
    if [ -z "$TASK_SLUG" ] || [ -z "$FEATURE_NAME" ] || [ -z "$FEATURE_SCOPE" ] || [ -z "$ROUND" ]; then
      usage
      exit 1
    fi

    TASK_DIR="$REPO_ROOT/.tasks/TASK-$TASK_SLUG"
    OUTPUT_FILE="$TASK_DIR/codex-hardening-round-$ROUND.md"
    TEMPLATE_FILE="$PROMPTS_DIR/codex-hardening-review.md"
    EXPLICIT_SCOPE_FILE="$TASK_DIR/codex-hardening-files.txt"
    ROUND_SCOPE_FILE="$TASK_DIR/codex-hardening-round-$ROUND-files.txt"
    SCOPED_DIFF_FILE="$TASK_DIR/codex-hardening-round-$ROUND.diff"
    PLAN_FILE="$REPO_ROOT/docs/plans/$TASK_SLUG.md"
    mkdir -p "$TASK_DIR"
    if [ "$ROUND" -eq 1 ]; then
      ROUND_FOCUS="Review the scoped diff first. Use the previous audit and matching backlog items only to suppress duplicates."
      KNOWN_ISSUES_SCOPE="Read only backlog items that match the touched files or the feature name."
    else
      ROUND_FOCUS="Prioritize the scoped diff since the previous round. Re-check only prior findings and matching backlog items."
      KNOWN_ISSUES_SCOPE="Do not rescan the full backlog. Read only prior-audit items and backlog entries that match touched files."
    fi
    ;;
  entropy)
    TASK_SLUG="${1:-}"
    REPORT_FILE="${2:-}"
    ENTROPY_SCOPE="${3:-}"
    if [ -z "$TASK_SLUG" ] || [ -z "$REPORT_FILE" ] || [ -z "$ENTROPY_SCOPE" ]; then
      usage
      exit 1
    fi
    if [[ "$REPORT_FILE" != /* ]]; then
      REPORT_FILE="$REPO_ROOT/$REPORT_FILE"
    fi
    if [ ! -f "$REPORT_FILE" ]; then
      echo "Entropy report not found: $REPORT_FILE" >&2
      exit 1
    fi

    TASK_DIR="$REPO_ROOT/.tasks/TASK-$TASK_SLUG"
    OUTPUT_FILE="$TASK_DIR/codex-entropy-review.md"
    # Note: codex-entropy-review.md template would need to be created
    TEMPLATE_FILE="$PROMPTS_DIR/codex-plan-review.md"  # Fallback to plan template
    mkdir -p "$TASK_DIR"
    ;;
  *)
    usage
    exit 1
    ;;
esac

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "Prompt template not found: $TEMPLATE_FILE" >&2
  exit 1
fi

PROMPT_FILE="$(mktemp)"
STDERR_FILE="$(mktemp)"
trap 'rm -f "$PROMPT_FILE" "$STDERR_FILE"; rm -rf "$CODEX_HOME_RUN"' EXIT

case "$MODE" in
  plan)
    render_template \
      "$TEMPLATE_FILE" \
      "__TASK_SLUG__" "$TASK_SLUG" \
      "__PLAN_FILE__" "$PLAN_FILE" \
      "__OUTPUT_FILE__" "$OUTPUT_FILE" \
      > "$PROMPT_FILE"
    ;;
  hardening)
    SCOPED_DIFF_FILE_REL="$(relative_repo_path "$SCOPED_DIFF_FILE")"
    ROUND_SCOPE_FILE_REL="$(relative_repo_path "$ROUND_SCOPE_FILE")"
    SCOPE_SOURCE="${SCOPE_SOURCE:-task-scoped diff}"
    PREVIOUS_ROUND=$((ROUND - 1))
    render_template \
      "$TEMPLATE_FILE" \
      "__TASK_SLUG__" "$TASK_SLUG" \
      "__FEATURE_NAME__" "$FEATURE_NAME" \
      "__FEATURE_SCOPE__" "$FEATURE_SCOPE" \
      "__ROUND__" "$ROUND" \
      "__PREVIOUS_ROUND__" "$PREVIOUS_ROUND" \
      "__SCOPE_SOURCE__" "$SCOPE_SOURCE" \
      "__SCOPED_DIFF_FILE__" "$SCOPED_DIFF_FILE_REL" \
      "__SCOPED_FILES_FILE__" "$ROUND_SCOPE_FILE_REL" \
      "__ROUND_FOCUS__" "$ROUND_FOCUS" \
      "__KNOWN_ISSUES_SCOPE__" "$KNOWN_ISSUES_SCOPE" \
      "__OUTPUT_FILE__" "$OUTPUT_FILE" \
      > "$PROMPT_FILE"
    ;;
  entropy)
    render_template \
      "$TEMPLATE_FILE" \
      "__TASK_SLUG__" "$TASK_SLUG" \
      "__PLAN_FILE__" "$REPORT_FILE" \
      "__OUTPUT_FILE__" "$OUTPUT_FILE" \
      > "$PROMPT_FILE"
    ;;
esac

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Mode: $MODE"
  echo "Output file: $OUTPUT_FILE"
  echo "Prompt template: $TEMPLATE_FILE"
  if [ "$MODE" = "hardening" ]; then
    echo "Explicit scope manifest: $EXPLICIT_SCOPE_FILE"
    echo "Round scope file: $ROUND_SCOPE_FILE"
    echo "Scoped diff file: $SCOPED_DIFF_FILE"
  fi
  echo "--- Prompt Preview ---"
  cat "$PROMPT_FILE"
  exit 0
fi

if [ "$MODE" = "hardening" ]; then
  if ! prepare_hardening_scope; then
    exit 0
  fi
  SCOPED_DIFF_FILE_REL="$(relative_repo_path "$SCOPED_DIFF_FILE")"
  ROUND_SCOPE_FILE_REL="$(relative_repo_path "$ROUND_SCOPE_FILE")"
  render_template \
    "$TEMPLATE_FILE" \
    "__TASK_SLUG__" "$TASK_SLUG" \
    "__FEATURE_NAME__" "$FEATURE_NAME" \
    "__FEATURE_SCOPE__" "$FEATURE_SCOPE" \
    "__ROUND__" "$ROUND" \
    "__PREVIOUS_ROUND__" "$((ROUND - 1))" \
    "__SCOPE_SOURCE__" "$SCOPE_SOURCE" \
    "__SCOPED_DIFF_FILE__" "$SCOPED_DIFF_FILE_REL" \
    "__SCOPED_FILES_FILE__" "$ROUND_SCOPE_FILE_REL" \
    "__ROUND_FOCUS__" "$ROUND_FOCUS" \
    "__KNOWN_ISSUES_SCOPE__" "$KNOWN_ISSUES_SCOPE" \
    "__OUTPUT_FILE__" "$OUTPUT_FILE" \
    > "$PROMPT_FILE"
fi

cd "$REPO_ROOT"

run_codex \
  "$STDERR_FILE" \
  codex exec \
    -m gpt-5.4 \
    --sandbox workspace-write \
    --ephemeral \
    --skip-git-repo-check \
    --color never \
    -o "$OUTPUT_FILE" \
    - < "$PROMPT_FILE"

echo "Saved Codex review evidence to $OUTPUT_FILE"
if [ "$SHOW_OUTPUT" -eq 1 ] && [ -s "$OUTPUT_FILE" ]; then
  echo "--- Codex Review Output ---"
  cat "$OUTPUT_FILE"
fi
