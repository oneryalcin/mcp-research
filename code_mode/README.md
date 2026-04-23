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

### Two more configurations: hybrid and baked

For servers with ≤10 tools, two natural variations on code mode are worth testing:

- **Hybrid**: all 9 tools visible in the manifest *plus* an `execute` tool that can compose them via `await call_tool(name, params)`. The agent chooses per-task: direct call for a lookup, `execute` for composition. Implemented in `server_hybrid.py`.
- **Baked**: pure code mode with `discovery_tools=[]` and the full tool catalog baked into the execute tool's description — no `search`, no `get_schema`, just `execute` with a big docstring. Recommended in the fastmcp docs as a pattern for "very simple servers." Implemented in `server_baked.py`.

Results, Sonnet 4.6, same three tasks (`ok` = `is_error` flag from stream-json — **does not** imply the answer was correct; correctness column added by manual inspection):

```
run                              calls   secs   $cost     in      out     cache  ok  correct?
native_t1_trivial_sonnet             1    7.2  0.0214    399      473     6604   y   ✅ 1859
native_t2_rate_rank_sonnet          52  307.2  0.7109   9997    26021    80146   y   ✅
native_t3_stats_sonnet             108  385.6  1.8306 258701    35294   165010   !   ❌ context overflow
codemode_t1_trivial_sonnet           4   14.2  0.0279    402      648    15980   y   ✅ 1859
codemode_t2_rate_rank_sonnet         9   32.2  0.0661    437     1882    49338   y   ✅
codemode_t3_stats_sonnet             6   51.3  0.1072    455     4496    36022   y   ✅
hybrid_t1_trivial_sonnet             1    6.9  0.0211    399      415     6912   y   ✅ 1859
hybrid_t2_rate_rank_sonnet           9   44.0  0.0853    436     3105    58161   y   ✅
hybrid_t3_stats_sonnet              24  147.4  0.3209   9939    10086   207390   y   ✅
baked_t1_trivial_sonnet            144  597.9  1.6751  78195    27572  2219691   y   ❌ gave up
baked_t2_rate_rank_sonnet          164  522.3  1.4015  79957    30017  1156876   y   ❌ gave up
baked_t3_stats_sonnet               95  346.5  0.9140  45072    17064  1077211   y   ❌ gave up
```

**Hybrid: the best shape for mixed workloads.**

- Task 1 (trivial): **1 call, 6.9s, $0.021** — matches native exactly, because the model sees `cases_query` in the manifest and calls it directly.
- Task 2 (composition): 9 calls, 44s, $0.085 — roughly equivalent to pure code mode (9 calls, 32s, $0.066). Slightly slower because the model made two direct tool calls before switching to `execute` for the aggregation.
- Task 3 (statistical): 24 calls, 147s, $0.32 — succeeded (code mode: 6 calls, 51s, $0.107). The extra round-trips came from the model fumbling the sandbox's `return` semantics (several `execute({"code": "x = 42; print(x)"})` probes visible in the trace) before settling on the right pattern.

So hybrid gets you the trivial-task win *and* composition correctness, at the cost of roughly 3× overhead vs pure code mode on the hardest task. If your tool mix is dominated by lookups with occasional composition, hybrid is the right default. If composition is the common case, pure code mode is leaner.

**Baked: failed on every task. Do not use this pattern as-is.**

All three baked tasks completed without an error flag but produced no correct answer. The traces show why: the model never read the 1982-character tool catalog in the execute tool's description. On Task 1, Sonnet's first `execute` call was `await call_tool("query_cases", ...)` — a guessed, inverted-word-order name. When that failed, the next 143 calls worked through a long tail of guesses (`get_cases`, `list_cases`, `list_tools`, `help`, `get_countries`, ...), `ListMcpResourcesTool` probes, `print(dir())` introspection attempts, and finally an "I was unable to retrieve the requested data" apology.

The fastmcp docs suggest this pattern for cases where "the LLM already knows what tools are available — maybe there are only a few, or they're described in the system prompt." In retrospect, the key phrase is **"described in the system prompt"**, not *"described in the tool's own description field."* A tool description gets very different treatment from a system prompt — the model treats it as "what this tool does" rather than "the schema of the world inside this tool." The catalog is there, the model just doesn't read it as a catalog.

This is a useful negative result: **for reliable single-stage code mode, put the tool catalog in the system prompt**, not in `execute_description`. Alternatively, use the default three-stage (search + get_schema + execute) even for small catalogs — the discovery round-trips are real but at least they succeed.

```
Summary of the four shapes:

  native   → one tool per capability, visible in manifest.
             Best: trivial lookups. Fails: data-heavy aggregation (context overflow).

  codemode → search + get_schema + execute, original tools hidden.
             Best: composition and aggregation. Cost: discovery overhead on trivial lookups.

  hybrid   → all tools visible + execute.
             Best: mixed workloads where most tasks are lookups with occasional composition.
             Cost: ~3× vs pure code mode on the hardest cases (sandbox-return fumbling).

  baked    → discovery_tools=[], catalog in execute_description.
             FAILS on all tested tasks — the model ignores the catalog in the description.
             Would likely need to move the catalog to the system prompt to be viable.
```

### Model tier cross-section (code mode only)

Both Task 2 and Task 3 re-run with `--model haiku` and `--model opus`. Every cell succeeds; the differences are in *how* each tier gets to the right answer.

```
run                            calls  secs   $cost     in     out    cache  ok
codemode_t2_rate_rank_haiku       10  30.1  0.0469  19371   3053   27141   y
codemode_t2_rate_rank_sonnet       9  32.2  0.0661    437   1882   49338   y
codemode_t2_rate_rank_opus         7  25.1  0.0963    438   1682   38494   y
codemode_t3_stats_haiku           17  63.1  0.0779  16249   7456   96392   y
codemode_t3_stats_sonnet           6  51.3  0.1072    455   4496   36022   y
codemode_t3_stats_opus             7  37.4  0.1475    459   3097   52616   y
```

**Observations:**

- **Code mode is not a Sonnet-tier-and-up feature.** All three models produced the exact answer on both tasks. Haiku can write correct `await call_tool(...)` scripts, recover from wrong-schema errors, and compose multi-step analyses.
- **Round-trip count scales inversely with capability.** Opus ≤ Sonnet ≪ Haiku. Haiku needed ~3× more `execute` retries on Task 3 to get the `result['result']` unwrapping right — visible in the trace as repeated executions with print-debugging. Each dead end informed the next attempt.
- **Cost inverts the round-trip ordering.** Haiku is the cheapest tier end-to-end even when taking the most calls, because the lower per-token price dominates. Opus is the fastest and most call-efficient, but also the most expensive. Sonnet sits in the middle on both axes.
- **Bit-exact arithmetic across tiers.** Haiku's per-country CFRs differ from ground truth in the 5th–6th decimal (e.g. Atlantia 0.004185 vs 0.004183 — rounding during division), but every model's final aggregated `mean=0.003779`, `stdev=0.000297` matches ground truth exactly. The sandbox doing the actual math neutralizes tier differences at the output level.
- **Retry loop is the safety net.** Code mode's failure mode is "execute raised, LLM reads the traceback, rewrites, retries." All three tiers made that loop work. Native MCP has no equivalent — a wrong-shape query returns empty data silently, and the LLM's only feedback is its own reasoning about an unhelpful result.

Headline: for composition-heavy workloads, pick the model you're paying for based on cost profile, not capability fears. Haiku gets there; it just takes longer. The sandbox is doing the work that capability differences would otherwise dominate.

### Skills-as-resources × code mode: a pleasant interaction

A natural follow-up: what if the server exposes **both** a `CodeMode` transform *and* skill markdown files as MCP resources — e.g. a runbook that encodes the Ministry's outbreak definition? Does the agent consult the skill, or does it invent thresholds and use the most topically-named tool?

This builds on the findings in [`../skills_as_resources/`](../skills_as_resources/README.md), which concluded that for *native* MCP, agents do not consult resources unless prompted. The one-line rule that fixed it there:

> When you are about to use tools from an MCP server (tools named `mcp__<server>__*`), first call `ListMcpResourcesTool` on that server and read any resources that look like runbooks, skills, or instructions. MCP resources encode ordering, gotchas, and the correct parameter values that tool schemas cannot express. Do this once per server before calling its tools.

#### Setup

A fourth task, `t4_outbreak`, asks the agent to produce a list of (region, disease) pairs currently qualifying as a "flagged outbreak under our internal standard," with a deliberately neutral prompt — no mention of runbooks, documentation, or protocols. The server exposes one skill at `skill://outbreak-protocol/SKILL.md` encoding a deliberately non-guessable rule:

- Population > 1,000,000 (smaller regions excluded as noise-dominated)
- 7-day rate per 100k **> 60.0** (exact threshold only knowable from the skill)
- Disease in {measles, covid19, rsv, pertussis} — flu and norovirus **excluded**
- Source: `cases_query`, **not** `outbreak_alerts` (the alerts table is explicitly off-limits per the skill)

If the agent reads the skill → produces the canonical 15-row list with correct rates.
If it doesn't → uses the wrong disease set, wrong threshold, or worse, reads from `outbreak_alerts` which the skill explicitly forbids.

Four configurations, Sonnet 4.6:

| Mode | Skill read? | Right answer? | Calls | Notes |
|---|---|---|---|---|
| `codemode+skills`, no rule | ✅ | ✅ 15 pairs | 9 | Sonnet self-discovered the skill |
| `codemode+skills`, with rule | ✅ | ✅ 15 pairs | 7 | Rule = no behavior change |
| **`native+skills`, no rule** | **❌** | **❌ wrong list** | **2** | Called `outbreak_alerts` directly, included flu/norovirus, wrong format |
| `native+skills`, with rule | ✅ | ✅ 15 pairs | 7 | Rule fixed it |

#### The interesting finding

**Code mode *already* prompts the model to consult resources, without the rule.** Even with a completely neutral prompt ("identify every (region, disease) pair that qualifies as flagged under our internal standard"), Sonnet ran this sequence:

```
  search("surveillance outbreak flagged")        ← code mode's search
  → returns tools, no obvious match
  ListMcpResourcesTool({server: "health"})       ← pivots to resource discovery
  → sees skill://outbreak-protocol/SKILL.md
  ReadMcpResourceTool(skill://outbreak-protocol/SKILL.md)
  → reads the protocol
  get_schema([regions_list, cases_query])
  execute(...)                                   ← implements the protocol correctly
```

The hypothesis: code mode's **sparse tool surface** (only `search` / `get_schema` / `execute`) makes the model hungry for domain context. `search` alone doesn't surface a "protocol" or "runbook" hit among the tools, so the model asks "is there more context?" and checks resources. Native MCP has no such pressure — the most topically-named tool (`outbreak_alerts`) looks like the right answer, so the model fires it and never considers that there might be documentation worth consulting.

Two implications:

1. **Code mode + skills is a natural pair.** Ship the `CodeMode` transform on any server where skills-as-resources matter; you largely avoid the "model ignores resources" failure mode without needing to modify client system prompts.
2. **For native MCP servers, the rule from `skills_as_resources/` is still the cheapest fix.** A 59-word rule turns the wrong native answer into the right one at a cost of 5 extra tool calls (2 → 7).

Native-no-rule didn't produce an error — it produced a confidently wrong answer. The agent called `outbreak_alerts`, got 11 alerts (mixed active/cleared, mixed severities, including flu and norovirus), formatted them into a nice table, and reported them as "flagged outbreaks." No sign of uncertainty. This is the same failure class we saw with Opus fabricating ticket assignees in `skills_as_resources/`: plausible output, wrong facts, no way for downstream processes to tell the difference from correct output.

Re-running these four cells takes ~5 minutes and costs ~$0.80. Commands:

```bash
./run_task.sh codemode_skills t4_outbreak sonnet
./run_task.sh codemode_skills t4_outbreak sonnet --rule
./run_task.sh native_skills   t4_outbreak sonnet
./run_task.sh native_skills   t4_outbreak sonnet --rule
```

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
