"""Verify MontySandboxProvider limits fire on malicious/runaway code."""
import asyncio

from fastmcp import Client, FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode, MontySandboxProvider

ABUSE_CASES = [
    ("infinite_loop", "while True: pass"),
    ("memory_hog", "x = [0] * 10**9"),
    ("deep_recursion", "def f(n): return f(n+1)\nf(0)"),
]


async def main():
    mcp = FastMCP("abuse-test")

    @mcp.tool
    def echo(x: int) -> int:
        """Echo input."""
        return x

    sandbox = MontySandboxProvider(
        limits={
            "max_duration_secs": 2,
            "max_memory": 50_000_000,
            "max_recursion_depth": 50,
        }
    )
    mcp.add_transform(CodeMode(sandbox_provider=sandbox))

    async with Client(mcp) as c:
        for name, code in ABUSE_CASES:
            print(f"\n--- {name} ---")
            print(f"code: {code!r}")
            try:
                result = await c.call_tool("execute", {"code": code})
                print(f"returned: {str(result)[:200]}")
            except Exception as e:
                print(f"raised: {type(e).__name__}: {str(e)[:200]}")

        # positive control
        print("\n--- benign ---")
        result = await c.call_tool("execute", {"code": 'return await call_tool("echo", {"x": 42})'})
        print(f"returned: {str(result)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
