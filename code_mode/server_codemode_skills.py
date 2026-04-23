"""Code mode + skills: same 9-tool health surveillance server, wrapped in
CodeMode AND exposing skill markdown files as MCP resources.

Run:
    uv run --with 'fastmcp[code-mode]' python server_codemode_skills.py
"""
from __future__ import annotations

from pathlib import Path

from fastmcp.experimental.transforms.code_mode import CodeMode, MontySandboxProvider
from fastmcp.server.providers.skills import SkillsDirectoryProvider

import server as native_server  # noqa: E402 — registers the 9 tools

mcp = native_server.mcp

# Expose the skill directory as MCP resources
mcp.add_provider(
    SkillsDirectoryProvider(
        roots=Path(__file__).parent / "skills",
        supporting_files="resources",
    )
)

# Wrap the tools with CodeMode (default three-stage discovery)
mcp.add_transform(
    CodeMode(
        sandbox_provider=MontySandboxProvider(
            limits={
                "max_duration_secs": 15,
                "max_memory": 200_000_000,
                "max_recursion_depth": 100,
            }
        )
    )
)

if __name__ == "__main__":
    mcp.run()
