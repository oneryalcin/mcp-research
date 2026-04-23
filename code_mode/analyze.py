"""Extract metrics from stream-json traces and print a comparison table.

Usage:
    python analyze.py out_*.jsonl
"""
import glob
import json
import sys
from collections import Counter


def summarize(path: str) -> dict:
    tool_counts: Counter[str] = Counter()
    final = None
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        c = d.get("message", {}).get("content") or []
        if isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_use":
                    tool_counts[b["name"]] += 1
        if d.get("type") == "result":
            final = d
    if not final:
        return {"path": path, "error": "no result line"}
    mu = final.get("modelUsage") or {}
    tot_in = sum(m.get("inputTokens", 0) for m in mu.values())
    tot_out = sum(m.get("outputTokens", 0) for m in mu.values())
    tot_cache = sum(
        m.get("cacheCreationInputTokens", 0) + m.get("cacheReadInputTokens", 0)
        for m in mu.values()
    )
    return {
        "path": path,
        "duration_ms": final.get("duration_ms"),
        "cost_usd": final.get("total_cost_usd"),
        "tokens_in": tot_in,
        "tokens_out": tot_out,
        "tokens_cache": tot_cache,
        "tool_calls": sum(tool_counts.values()),
        "tool_breakdown": dict(tool_counts),
        "is_error": final.get("is_error", False),
        "result_head": (final.get("result") or "")[:160],
    }


def main(argv: list[str]) -> int:
    paths = []
    for a in argv[1:]:
        paths.extend(sorted(glob.glob(a)))
    if not paths:
        print("usage: analyze.py out_*.jsonl", file=sys.stderr)
        return 2
    rows = [summarize(p) for p in paths]
    hdr = f"{'run':45s} {'calls':>6s} {'secs':>7s} {'$cost':>7s} {'in':>7s} {'out':>7s} {'cache':>8s} {'ok':>3s}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        name = r["path"].rsplit("/", 1)[-1].replace("out_", "").replace(".jsonl", "")
        ok = "!" if r.get("is_error") else "y"
        print(
            f"{name:45s} {r['tool_calls']:6d} {r['duration_ms']/1000:7.1f} {r['cost_usd']:7.4f}"
            f" {r['tokens_in']:7d} {r['tokens_out']:7d} {r['tokens_cache']:8d} {ok:>3s}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
