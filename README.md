# mcp-research

Small, reproducible experiments on how LLM agents actually behave with Model Context Protocol (MCP) servers. Each subfolder is a self-contained investigation: a runnable server, a test harness, and a findings writeup with commands you can re-run.

## Experiments

- **[skills_as_resources/](skills_as_resources/)** — Can Claude Code consume [FastMCP "skills"](https://gofastmcp.com) exposed as MCP *resources*? What does it take for the agent to actually consult them before acting? Tests across Haiku 4.5, Sonnet 4.6, and Opus 4.7. Ends with a one-paragraph system-prompt rule that fixes the pattern across the whole model lineup.

## How to contribute

Open an issue with a question you want tested, or a PR with a new subfolder following the same shape: runnable code + commands + a distilled findings section with traces. No coverage theatre, no vibes — every claim should come with a command anyone can replay.

## License

MIT.
