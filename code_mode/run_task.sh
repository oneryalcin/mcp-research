#!/usr/bin/env bash
# Usage: run_task.sh <native|codemode> <task_key> <model>
# Example: run_task.sh codemode t3_stats sonnet
#
# Assumes you're running from the code_mode/ directory, with mcp_*.json already
# edited to contain absolute paths to this directory's server.py.
set -euo pipefail
MODE="$1"
TASK="$2"
MODEL="${3:-sonnet}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROMPT=$(python3 -c "import json; print(json.load(open('${HERE}/tasks.json'))['$TASK']['prompt'])")
CONFIG="${HERE}/mcp_${MODE}.json"
OUT="${HERE}/out_${MODE}_${TASK}_${MODEL}.jsonl"

WORKDIR="$(mktemp -d)"
cd "$WORKDIR"

claude --bare --model "$MODEL" -p "$PROMPT" \
  --mcp-config "$CONFIG" \
  --strict-mcp-config \
  --permission-mode bypassPermissions \
  --disallowed-tools "Bash" "Read" "Glob" "Grep" "WebFetch" "WebSearch" "advisor" \
  --output-format stream-json --verbose \
  > "$OUT" 2>&1
echo "wrote $OUT"
