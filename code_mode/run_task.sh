#!/usr/bin/env bash
# Usage: run_task.sh <mode> <task_key> <model> [--rule]
# Example: run_task.sh codemode_skills t4_outbreak sonnet --rule
#
# Modes are defined by mcp_<mode>.json files in this directory. Passing
# --rule appends the skills-consumption rule to the system prompt.
set -euo pipefail
MODE="$1"
TASK="$2"
MODEL="${3:-sonnet}"
RULE_FLAG="${4:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROMPT=$(python3 -c "import json; print(json.load(open('${HERE}/tasks.json'))['$TASK']['prompt'])")
CONFIG="${HERE}/mcp_${MODE}.json"
SUFFIX=""
EXTRA_ARGS=()
if [ "$RULE_FLAG" = "--rule" ]; then
  SUFFIX="_rule"
  EXTRA_ARGS+=(--append-system-prompt "When you are about to use tools from an MCP server (tools named mcp__<server>__*), first call ListMcpResourcesTool on that server and read any resources that look like runbooks, skills, or instructions. MCP resources encode ordering, gotchas, and the correct parameter values that tool schemas cannot express. Do this once per server before calling its tools.")
fi
OUT="${HERE}/out_${MODE}_${TASK}_${MODEL}${SUFFIX}.jsonl"

WORKDIR="$(mktemp -d)"
cd "$WORKDIR"

claude --bare --model "$MODEL" -p "$PROMPT" \
  --mcp-config "$CONFIG" \
  --strict-mcp-config \
  --permission-mode bypassPermissions \
  --disallowed-tools "Bash" "Read" "Glob" "Grep" "WebFetch" "WebSearch" "advisor" \
  "${EXTRA_ARGS[@]}" \
  --output-format stream-json --verbose \
  > "$OUT" 2>&1
echo "wrote $OUT"
