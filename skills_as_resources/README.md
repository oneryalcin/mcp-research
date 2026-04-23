# Skills-as-Resources: Does Claude Code actually read them?

**TL;DR.** [FastMCP](https://gofastmcp.com) lets you publish agent "skills" (markdown runbooks with YAML frontmatter) as MCP *resources* under a `skill://` URI scheme. Claude Code can technically read them via its built-in `ListMcpResourcesTool` / `ReadMcpResourceTool`, but **no model — Haiku 4.5, Sonnet 4.6, or Opus 4.7 — will consult them on its own in headless mode**. Without explicit guidance, Opus 4.7 is the *most* dangerous offender: it confidently fabricates plausible tool arguments and triggers real side-effects. A 59-word, server-agnostic system-prompt rule fixes the behavior across the entire model lineup.

---

## The question

MCP has two kinds of things servers can publish:

- **Tools** — advertised in the model's tool manifest. The model sees them automatically, decides when to call them, and passes structured arguments.
- **Resources** — addressable by URI, listed on demand. They are *not* in the tool manifest. The model can reach them only through the generic `ListMcpResourcesTool(server)` / `ReadMcpResourceTool(server, uri)` pair, and only if it thinks to.

FastMCP's `SkillsDirectoryProvider` exposes each skill folder as a pair of resources (`skill://<name>/SKILL.md` + a synthetic `skill://<name>/_manifest`), with supporting files reachable via a resource template. Our question: **given a task whose correct execution depends on information inside a skill, will the agent discover and read the skill on its own?**

Short answer: no, not without help. Long answer: what does "help" look like, and how cheap can we make it?

## Setup

The experiment ships a FastMCP server exposing two synthetic skill folders plus two plausible "real work" tools:

```
skills_as_resources/
├── server.py                          # FastMCP, skills provider + 2 tools
├── mcp.json                           # Claude Code --mcp-config pointing at server.py
└── skills/
    ├── acme-onboarding/SKILL.md       # has planted, non-guessable details
    └── incident-runbook/SKILL.md      # second skill, acts as distractor
```

### The planted facts

The `acme-onboarding/SKILL.md` runbook says things no model could guess:

- File the onboarding ticket in Linear project **`ENG-ONB`** (not the generic "Onboarding")
- Assign it to **Priya**, the IT lead
- The new hire's first PR **must** touch `docs/hello.md`
- Schedule the 30-day architecture review on **day 28**, not day 30
- Grant registry access via the `with-adc` wrapper, never raw GCS credentials
- Acme is GCP-only — do **not** provision AWS IAM

If the agent's answer mentions these, it read the skill. If it talks generically about "provisioning laptops" and "SSO access", it didn't.

### The tools

`create_acme_email(full_name)` and `file_linear_ticket(project, title, assignee)`. They are deliberately present to act as *signal flares* — a tool with a company-specific name in the model's manifest that advertises "this server has Acme-domain work to do." We want to see whether that alone is enough to make the model then go look for accompanying context.

### The task

A user prompt a human would plausibly send:

> A new engineer named Ayşe Kaya starts at Acme tomorrow morning. Give me a precise day-one plan and actually execute the things you can. Be concrete about names and order of operations. Don't invent anything you don't actually know.

No mention of MCP, resources, URIs, or skills. No mention of the runbook. We want the model to find the context itself.

### Running it

```bash
# 1. clone
git clone https://github.com/oneryalcin/mcp-research
cd mcp-research/skills_as_resources

# 2. patch mcp.json to use an absolute path to server.py
sed -i "s|REPLACE_WITH_ABSOLUTE_PATH|$PWD|" mcp.json

# 3. sanity-check the server lists resources correctly
uv run --with fastmcp python -c "
import asyncio
from pathlib import Path
from fastmcp import Client, FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
mcp = FastMCP('t')
mcp.add_provider(SkillsDirectoryProvider(roots=Path('./skills'), supporting_files='resources'))
async def m():
    async with Client(mcp) as c:
        for r in await c.list_resources(): print(r.uri)
asyncio.run(m())
"
# expected:
#   skill://acme-onboarding/SKILL.md
#   skill://acme-onboarding/_manifest
#   skill://incident-runbook/SKILL.md
#   skill://incident-runbook/_manifest

# 4. run the experiment headless (empty cwd + filesystem tools blocked so the
#    agent can't sidestep MCP by reading SKILL.md as a local file)
mkdir -p /tmp/empty-cwd && cd /tmp/empty-cwd

claude --bare --model opus -p "A new engineer named Ayşe Kaya starts at Acme tomorrow morning. Give me a precise day-one plan and actually execute the things you can. Be concrete about names and order of operations. Don't invent anything you don't actually know." \
  --mcp-config /absolute/path/to/mcp.json \
  --strict-mcp-config \
  --permission-mode bypassPermissions \
  --disallowed-tools Bash Read Glob Grep WebFetch WebSearch advisor \
  --output-format stream-json --verbose
```

Two switches worth calling out:

- **`--disallowed-tools ... advisor`** — Claude Code can invoke a server-side `advisor` tool that routes the conversation to a reviewer model (Opus 4.7 in our harness). When on, it nudges the main model to check available context before acting. That behavior muddles "did the model reason its way here?" with "was it told to?" — disabling it isolates the intrinsic behavior of the main model. The user-level `/advisor off` toggle only affects the parent session; the child `claude -p` subprocess must block it explicitly.
- **`--disallowed-tools Bash Read Glob Grep`** — without these, the agent happily `ls`'s around and reads `SKILL.md` as a plain file, never touching MCP. Blocking them forces it through the MCP pathway (or through hallucination, which is the interesting failure mode).

## Findings

### 1. Without guidance, every model fails — and they fail differently

Same task, same server, same prompt. `--model` is the only thing that changes. Advisor off. No system-prompt hint.

| Model | `ListMcpResourcesTool` called? | Skill read? | Tools called | Outcome |
|---|---|---|---|---|
| Haiku 4.5 | ✗ | ✗ | 1 (`create_acme_email`) | Generic onboarding plan — fabricated hardware/badge steps, no runbook details |
| Sonnet 4.6 | ✗ | ✗ | 1 (`create_acme_email`) | Generic plan, asks user for missing info |
| **Opus 4.7** | **✗** | **✗** | **5** (1 email + **4 fabricated tickets**) | Confidently invents `project="Onboarding"`, `assignee="IT"`, files four bogus tickets, even rationalizes the backend returning the same ID four times as a "backend quirk" |

Capability does *not* imply caution. Opus's stronger priors make it *more* willing to fill gaps with plausible invention. In production, this is the worst outcome — confident actions on wrong parameters.

### 2. The advisor is a partial fix but it's a confound

An earlier Sonnet run without the `advisor` block produced a clean, correct flow. Inspecting the trace revealed that Sonnet had invoked `server_tool_use: advisor`, whose review (performed by Opus 4.7) came back with the advice "list available MCP resources before executing substantive work." That advice, dropped into Sonnet's context, triggered the correct behavior.

So the advisor works — but it's a) expensive (Opus second-opinion pass), b) not always on, c) not available outside Claude Code's runtime. Relying on it for skills discovery is not portable.

### 3. A generic per-server rule fixes the whole lineup

Append this to the system prompt via `--append-system-prompt`:

> When you are about to use tools from an MCP server (tools named `mcp__<server>__*`), first call `ListMcpResourcesTool` on that server and read any resources that look like runbooks, skills, or instructions. MCP resources encode ordering, gotchas, and the correct parameter values that tool schemas cannot express. Do this once per server before calling its tools.

With this rule in place, advisor off:

| Model | Listed resources? | Read skill? | Tools called | Ticket params |
|---|---|---|---|---|
| Haiku 4.5 | ✅ scoped to `skills` server | ✅ onboarding skill | 4 (correct sequence) | `project="ENG-ONB"`, `assignee="Priya"` |
| Sonnet 4.6 | ✅ | ✅ | 4 | correct |
| Opus 4.7 | ✅ | ✅ | 4 (no fabrication) | correct |

All three models produced runbook-grounded answers citing Priya, day 28, `with-adc`, `docs/hello.md`, and the GCP-only callout. Zero fabricated tickets. Haiku — which failed hardest without the rule — needed no auxiliary model; the entire run was served by Haiku alone.

### Why the rule works

```
  "When you are about to use tools from an MCP server"
     ← triggered by tool intent, not per-turn cost

  "first call ListMcpResourcesTool on that server"
     ← names the exact tool → no invention required

  "resources encode ordering, gotchas, and correct parameter values
   that tool schemas cannot express"
     ← explains the WHY → motivates genuine engagement, not just compliance

  "Do this once per server"
     ← caps the tax: one list call per distinct server per session
```

The rule is server-agnostic (works for `skills`, `sentry`, `gmail`, any future server), tool-triggered (fires only when MCP is actually in play), and cheap (one list call per server, not per turn).

## Design implications for skills servers

If you're publishing skills via FastMCP and want them consumed at inference time rather than synced to local disk via `sync_skills()`:

1. **Don't assume the model will find resources.** It won't, across all three tiers of Claude we tested. You need at least one of: a system-prompt rule (cheapest, portable), the advisor loop (expensive, Claude-Code-specific), or wrapping the skill content behind a tool.
2. **Tools are the self-advertising surface, resources aren't.** Adding a tool to your server isn't enough to get resources noticed (see Opus fabrication case). The tool's presence signals "this server exists," but the jump to "so let me check its resources" is not free.
3. **The skill itself should encode what the tool schema can't** — ordering, gotchas, the magic values, negative rules. That's exactly where hallucination happens and where a read genuinely pays off.

## Caveats and what this doesn't test

- **Claude Code only.** Other MCP clients (Cursor, VS Code Copilot, Gemini CLI, custom SDK-based agents) have their own tool manifests and may or may not expose `ListMcpResourcesTool`/`ReadMcpResourceTool` equivalents. The portability of the rule is untested.
- **Headless `-p` mode only.** Interactive mode has `@server:uri` mentions; humans drive discovery there, the model doesn't have to.
- **Synthetic runbook.** The Acme onboarding is a fixture designed to be non-guessable. Real-world skills with more industry-standard content (code review, PDF processing) might be partially inferable from model priors, making the "did it read it" signal weaker.
- **Temperature effects not measured.** All runs at defaults. A lower-temperature pass on Opus-no-rule might reduce fabrication counts; it would not change the core finding (no resource check).
- **One skill-shape only.** We tested the `SKILL.md` + `_manifest` layout with `supporting_files="resources"`. The default `supporting_files="template"` mode hides reference files from `list_resources()`; we did not test whether the rule still leads the model to templated URIs correctly.
- **`advisor` semantics may change.** What the advisor returns depends on the reviewer model's behavior and the current harness. Our characterization of its effect is based on this single run and should not be treated as a specification.

## Reproducing the full matrix

Every cell in the matrices above corresponds to one `claude -p` invocation. Diff the commands by changing `--model {haiku,sonnet,opus}` and adding or removing `--append-system-prompt` with the rule above. All runs use `--permission-mode bypassPermissions`, `--disallowed-tools "Bash Read Glob Grep WebFetch WebSearch advisor"`, and `--strict-mcp-config` for isolation. Traces in `stream-json` format capture every tool call.

Pull requests welcome — especially for other MCP clients, other providers (GPT, Gemini), and more skill shapes.
