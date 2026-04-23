"""Hybrid mode: 9 native tools visible in the manifest PLUS one `execute`
tool that runs sandboxed Python with access to the others via `call_tool`.

Agent can choose: direct tool call for simple lookups, `execute` for composition.

Run:
    uv run --with 'fastmcp[code-mode]' python server_hybrid.py
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import (
    MontySandboxProvider,
    _unwrap_tool_result,
)
from fastmcp.server.context import Context

# Re-use the exact same tool implementations from server.py by importing it.
# server.py also registers its MODE transform, so we import the functions
# and re-register them on a fresh FastMCP instance for the hybrid mode.
import server as native_server  # noqa: E402

mcp = FastMCP("health-surveillance-hybrid")

# Register the same 9 tools on the hybrid mcp.
for tool_name in [
    "regions_list",
    "region_get",
    "cases_query",
    "deaths_query",
    "hospitalizations_query",
    "vaccinations_query",
    "outbreak_alerts",
    "time_series",
    "neighbor_regions",
]:
    mcp.tool(getattr(native_server, tool_name))

_sandbox = MontySandboxProvider(
    limits={
        "max_duration_secs": 15,
        "max_memory": 200_000_000,
        "max_recursion_depth": 100,
    }
)


@mcp.tool
async def execute(code: str, ctx: Context) -> Any:
    """Run Python code with access to every other tool on this server via
    `await call_tool(name, params)`. Use this for multi-step work that would
    otherwise require many round-trips (per-item loops, aggregations,
    statistics). For simple single-call lookups, prefer calling the relevant
    tool directly.

    The code runs in a sandbox with `await call_tool(name, params)` injected
    in scope. Return the final value with `return ...` (the sandbox expects
    an explicit return).
    """

    async def call_tool(tool_name: str, params: dict[str, Any]) -> Any:
        result = await ctx.fastmcp.call_tool(tool_name, params)
        return _unwrap_tool_result(result)

    return await _sandbox.run(code, external_functions={"call_tool": call_tool})


if __name__ == "__main__":
    mcp.run()
