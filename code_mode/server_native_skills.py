"""Native MCP + skills: 9 tools visible, skills directory exposed as MCP
resources. No code-mode wrapping. Paired experiment against
server_codemode_skills.py.
"""
from __future__ import annotations

from pathlib import Path

from fastmcp.server.providers.skills import SkillsDirectoryProvider

import server as native_server  # noqa: E402 — registers the 9 tools

mcp = native_server.mcp

mcp.add_provider(
    SkillsDirectoryProvider(
        roots=Path(__file__).parent / "skills",
        supporting_files="resources",
    )
)

if __name__ == "__main__":
    mcp.run()
