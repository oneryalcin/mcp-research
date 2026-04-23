# Code Mode: when should an MCP server expose 9 tools vs. 2 meta-tools?

**TL;DR.** [Cloudflare's code-mode pattern](https://blog.cloudflare.com/code-mode/), ported into FastMCP as `CodeMode`, collapses an entire tool catalog behind two meta-tools (`search` + `execute`) and runs agent-written code in a sandbox. Most teams have **≤10 tools**, so manifest-size compression isn't the headline. The headline is: **native MCP iterates in the LLM's head, code mode iterates in a Python sandbox**. For a 9-tool public-health surveillance server, tested with Sonnet 4.6:

| Task | Shape | Native MCP | Code mode |
|---|---|---|---|
| Trivial lookup | 1 data point | 1 call, 7s, $0.02 — **wins** | 4 calls, 14s, $0.03 (discovery overhead) |
| Per-region rate ranking | fan-out over 50 regions | 52 calls, 307s, $0.71 | **9 calls, 32s, $0.07** (≈10× everything) |
| Statistical aggregation | Q1 stats across countries | **108 calls, 386s, $1.83 — context overflow, failed** | **6 calls, 51s, $0.11 — exact answer** |

Native MCP can't even complete the stats task: the 90-day × 50-region × 6-disease intermediate data blows the context window. Code mode finishes in 6 calls because the intermediate arrays stay in the sandbox and only the final two numbers — mean CFR and stdev — cross the wire.

---

## The question

Cloudflare's headline is "2,594 endpoints in ~1K tokens" — a manifest-compression story. But the average MCP server has ≤10 tools, where that story shrinks to "saved ~2K tokens." **Is code mode still worth it below 10 tools?**

Our answer: **yes, but for a different reason**. The win at small catalog sizes is:

1. **Round-trip economics** — intermediate data stays in the sandbox, never passes through the context window
2. **Deterministic computation** — Python computes mean/stdev/ratios correctly; an LLM doing mental arithmetic on 100+ numbers will miscount
3. **One turn instead of N turns** — the LLM writes one script; the sandbox loops at interpreter speed instead of at inference speed

The benefit scales with **task complexity**, not **catalog size**. A 9-tool server where every task is a trivial lookup gets no win. A 9-tool server where tasks require composition gets a 10× win.

## Setup

A synthetic public-health surveillance server with **9 tools**:

```
  regions_list(country?)                    region_get(id)
  cases_query(region?, disease?, ...)       deaths_query(...)
  hospitalizations_query(...)               vaccinations_query(...)
  outbreak_alerts(severity?, active?)
  time_series(region, metric, window_days)
  neighbor_regions(region_id)
```

Deterministic seeded fixtures: 50 regions across 4 countries, 365 days of history, 6 diseases, 4 vaccines. ~109K day-records in memory. Ground truth precomputed in `ground_truth.py`.

Two server configurations, selected by env var `CODEMODE_MODE`:

- **`native`** — 9 tools exposed directly (classic MCP)
- **`codemode`** — same 9 tools, wrapped in `fastmcp.experimental.transforms.code_mode.CodeMode(sandbox_provider=MontySandboxProvider(...))`. The client sees **3 meta-tools**: `search`, `get_schema`, `execute`.

### Running it

```bash
git clone https://github.com/oneryalcin/mcp-research
cd mcp-research/code_mode

# patch the mcp.json configs
sed -i "s|REPLACE_WITH_ABSOLUTE_PATH|$PWD|" mcp_native.json mcp_codemode.json

# compute ground truth (optional, for sanity)
uv run --with 'fastmcp[code-mode]' python ground_truth.py

# run one task in each mode
./run_task.sh native   t3_stats sonnet
./run_task.sh codemode t3_stats sonnet

# compare all captured runs
python3 analyze.py 'out_*.jsonl'
```

Every invocation blocks filesystem/web tools (`--disallowed-tools Bash Read Glob Grep WebFetch WebSearch advisor`) so the agent has exactly one path to the data: MCP.

## Results

All three tasks run with Sonnet 4.6, advisor off, `/tmp/empty-cwd` as working directory:

```
run                                 calls    secs   $cost      in     out    cache  ok
---------------------------------- ------- ------ ------- ------- ------- -------- ----
native_t1_trivial_sonnet                 1    7.2  0.0214     399     473     6604  y
codemode_t1_trivial_sonnet               4   14.2  0.0279     402     648    15980  y
native_t2_rate_rank_sonnet              52  307.2  0.7109    9997   26021    80146  y
codemode_t2_rate_rank_sonnet             9   32.2  0.0661     437    1882    49338  y
native_t3_stats_sonnet                 108  385.6  1.8306  258701   35294   165010  !   ← context overflow
codemode_t3_stats_sonnet                 6   51.3  0.1072     455    4496    36022  y
```

`$cost` from Claude Code's own `modelUsage.costUSD`. Tokens are sums across the entire session (haiku auxiliary + sonnet main). `!` = error (`is_error=true`). Column `calls` counts every `tool_use` entry in the stream-json trace.

### Task 1 — trivial lookup (native wins)

*"How many measles cases in region R012 from 2026-04-18 through 2026-04-24?"* — ground truth **1859**.

- **Native**: 1 call to `cases_query` with the right filters. Model sums 7 daily numbers in a table, emits **1859**. ✅
- **Code mode**: `search` → tries `execute` with guessed param names (`region`, `date_start`) → fails → `get_schema` → corrects to (`region_id`, `since`) → `execute` works. 4 calls, correct answer. ✅

The discovery overhead (one wrong-schema round-trip) is exactly the tradeoff the fastmcp docs warn about. For one-shot lookups, classic MCP's ambient tool manifest is cheaper than code mode's progressive discovery.

### Task 2 — fan-out + rate calculation (code mode wins ~10×)

*"Top 5 regions by flu hospitalization rate per 100k over the last 30 days."*

- **Native**: fetches all regions, then calls `hospitalizations_query(region_id=RX, disease="flu", ...)` once per region. That's 50 round-trips plus 2 setup calls = **52 tool calls**. Each intermediate list flows through the context window. Answer correct, but it took 5 minutes and $0.71.
- **Code mode**: `search` → tries `execute` (wrong param names again) → `get_schema` → writes a single `execute` with a nested dict comprehension that computes all rates server-side → returns the top-5 list. **9 tool calls**, 32s, $0.07.

The ~10× improvement on every axis (calls, time, cost, tokens) comes from one fact: in native MCP, each `hospitalizations_query` result is a JSON list that passes back through the LLM's context to inform the next call; in code mode, those 50 lists exist only as variables in the sandbox and only the final top-5 summary leaves.

### Task 3 — statistical aggregation (native can't complete)

*"Across countries with pop >5M, compute each country's Q1 2026 COVID-19 case-fatality ratio, then report the mean and stdev of those per-country CFRs."* Ground truth: **mean 0.003779, stdev 0.000297**.

- **Native**: tries to query 90 days × 50 regions × cases + deaths. Issues 53 `cases_query` calls and 52 `deaths_query` calls. After 108 total calls and 6 minutes, the accumulated context exceeds the model's limit — the next turn's prompt is rejected. **The run fails** with `"Prompt is too long"`, `is_error=true`, **$1.83 spent on a non-answer**.
- **Code mode**: writes one `execute` that does `cases = await call_tool("cases_query", {...})` + same for deaths, groups by country in a dict, computes the per-country CFR, calls `statistics.mean` and `statistics.stdev`, returns two floats. **6 calls total** (including false starts on schema), 51s, $0.11. Exact match on both statistics.

This is the clearest case. Native MCP isn't slow-but-correct; it's **structurally incapable** of this shape of task at this data size. Code mode makes it routine.

### Sandbox safety

FastMCP's default `MontySandboxProvider` enforces runtime limits. `sandbox_abuse.py` in this folder tests three runaway patterns against a sandbox configured with `max_duration_secs=2`, `max_memory=50MB`, `max_recursion_depth=50`:

```
--- infinite_loop ---      while True: pass
  raised: ToolError: TimeoutError: time limit exceeded: 2.000000083s > 2s

--- memory_hog ---         x = [0] * 10**9
  raised: ToolError: MemoryError: memory limit exceeded: 16000000112 bytes > 50000000 bytes

--- deep_recursion ---     def f(n): return f(n+1); f(0)
  raised: ToolError: RecursionError: maximum recursion depth exceeded

--- benign ---             return await call_tool("echo", {"x": 42})
  returned: 42
```

All three limits fire cleanly. The sandbox catches the abuse, the server returns a `ToolError` that the agent can reason about, and the next turn continues. This is not a security boundary against a determined adversary (don't expose it to the public internet), but it is a robust defense against model-generated runaway code during normal agentic operation.

## Why this works: the mechanism

```
  Native MCP composition                  Code mode composition
  ──────────────────────                  ──────────────────────
  turn 1:  call regions_list()            turn 1:  call execute({code: """
  ← list of 50 regions (JSON)                          regions = await call_tool("regions_list", {})
  turn 2:  reason, pick R000                           hosp = await call_tool("hospitalizations_query", {
  turn 3:  call hospitalizations_query(R000)                    "disease": "flu", "since": ..., "until": ...})
  ← daily records (JSON)                               rates = {}
  turn 4:  reason, pick R001                           for r in regions:
  turn 5:  call hospitalizations_query(R001)              rates[r["id"]] = sum(
  ← daily records (JSON)                                     h["admissions"] for h in hosp
  ... (47 more region turns)                                 if h["region_id"] == r["id"]
  turn 52: sum admissions per region,                    ) / r["population"] * 100_000
          divide by population,                        return sorted(rates.items(), key=lambda x: -x[1])[:5]
          sort, pick top 5                         """})
  ← produce answer                        ← top-5 list
```

Two costs disappear in the right column:

1. **Per-call round-trip** — each native call is one LLM inference pass (seconds) just to decide which tool to fire next. In code mode, all 50 region lookups happen in one sandbox call (milliseconds each).
2. **Intermediate context tokens** — each native tool result is JSON that passes through the LLM's context on the next turn, where it's re-encoded and billed. In code mode, those 50 JSON results live as Python variables and only the final 5-element list leaves.

The second cost is what actually killed Task 3's native run. The 90-day × 50-region COVID case history exceeded the context limit once enough of it accumulated.

**The arithmetic angle** is a separate lift. LLMs are not calculators; they predict tokens that look like calculators' outputs. Given *"compute the average of these 80 numbers"*, an LLM's default path is to emit a plausible-shaped number — often correct to within 10%, rarely exact. Code mode removes the temptation entirely: `statistics.mean(xs)` is shorter than talking about the mean, and Python can't be wrong about it. For Task 3, code mode returned the exact 0.003779 / 0.000297 figures; there is no realistic native path that would have matched that precision even if it had completed.

## When to use each

```
  ┌──────────────────────────────────────────────────────────────┐
  │                                                              │
  │  small catalog (<10 tools)                                   │
  │     tasks = simple lookups       → native MCP                │
  │     tasks = composition / stats  → code mode                 │
  │                                                              │
  │  medium catalog (10-100 tools)                               │
  │     → code mode (manifest savings start to matter too)       │
  │                                                              │
  │  large catalog (100+ tools, e.g. Cloudflare, AWS, K8s)       │
  │     → code mode, full stop                                   │
  │                                                              │
  └──────────────────────────────────────────────────────────────┘
```

Secondary considerations:

- **Latency matters more than tokens for interactive use** — 5 minutes vs. 30 seconds on a routine query is the difference between usable and unusable, independent of cost.
- **Deterministic computation matters more for numbers than for text** — if your agent is summarizing threads, native is fine. If it's reporting a percentage to stakeholders, code mode's guarantee of correct arithmetic is a hard requirement.
- **Model tier cross-cuts this** — Haiku is more likely to miscount in native mode; it's also more likely to write subtly wrong sandbox code. We only ran Sonnet here; a model-tier cross-section (Haiku/Sonnet/Opus × native/code-mode × trivial/composition/stats) would be a valuable follow-up.

## Caveats

- **Sonnet 4.6 only.** Extended-reasoning variants, Haiku, and Opus all have different composition habits. Needs retesting.
- **Synthetic fixtures.** The ~2× population inflator and disease base rates produce unrealistically high case counts. The comparative result (native vs. code mode) is unaffected; absolute numbers are fixture artifacts.
- **One seed.** The top-5 ranking in Task 2 is stable across the ground-truth recomputation; the statistical values in Task 3 are deterministic for this seed. Running with a different seed would produce different planted-truth numbers but should preserve the relative behavior.
- **Headless `-p` only.** Interactive mode has different cost profiles (streaming, partial tool responses, user interjections).
- **`pydantic-monty` sandbox.** FastMCP's default. A remote Cloudflare-Workers sandbox, a gVisor-backed container, or any custom `SandboxProvider` would produce similar task-level results with different security and performance envelopes.
- **Claude Code specifically.** The `ListMcpResourcesTool` / `ReadMcpResourceTool` built-ins weren't used here (code mode exposes its own discovery path), but the general cross-client portability of these findings is untested.

## Reproducing yourself

All three tasks can be replayed from the command line. Total wall-clock for all six runs: ~20 minutes. Cost: ~$3 (dominated by the Task 3 native failure at $1.83). If you swap in a different task in `tasks.json`, add its ground-truth computation to `ground_truth.py` and you're set.

PRs welcome — especially for model-tier cross-sections, GPT-5 / Gemini adaptations, and other sandbox backends.
