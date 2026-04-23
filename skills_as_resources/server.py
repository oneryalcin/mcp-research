"""FastMCP server exposing a skills directory as MCP resources, plus two
plausible "signal-flare" tools to see whether their presence in the tool
manifest alone is enough to nudge the agent into consulting the resources.

Run:
    uv run --with fastmcp python server.py
"""
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider

mcp = FastMCP("skills-test")

mcp.add_provider(
    SkillsDirectoryProvider(
        roots=Path(__file__).parent / "skills",
        supporting_files="resources",
    )
)


@mcp.tool
def create_acme_email(full_name: str) -> dict:
    """Provision a new @acme.example email address for an Acme employee.

    Use this when onboarding a new hire at Acme. Returns the provisioned
    email address and a temporary password.
    """
    first = full_name.strip().split()[0].lower()
    return {
        "email": f"{first}@acme.example",
        "temporary_password": "Welcome-2026-Acme!",
        "status": "provisioned",
    }


@mcp.tool
def file_linear_ticket(project: str, title: str, assignee: str) -> dict:
    """File a ticket in Linear under the specified project."""
    return {
        "id": f"{project}-0042",
        "url": f"https://linear.app/acme/issue/{project}-0042",
        "title": title,
        "assignee": assignee,
        "status": "open",
    }


if __name__ == "__main__":
    mcp.run()
