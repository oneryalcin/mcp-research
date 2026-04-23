"""Code mode variant: discovery_tools=[] (no search / get_schema), with the
full tool catalog baked into the execute tool's description.

The client sees a single tool (`execute`). The description enumerates all 9
underlying tools and their signatures, so the LLM can write code against
them immediately — no discovery round-trips.

Run:
    uv run --with 'fastmcp[code-mode]' python server_baked.py
"""
from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode, MontySandboxProvider

import server as native_server  # noqa: E402 — registers the 9 tools

mcp = native_server.mcp

TOOL_CATALOG = """\
Available tools (call via `await call_tool(name, params)` inside the Python sandbox):

- regions_list(country: str | None = None) -> list[dict]
    List surveillance regions. Fields per record: id, name, country, population.

- region_get(region_id: str) -> dict
    Full demographics for one region: id, name, country, population,
    age_0_14_pct, age_15_64_pct, age_65_plus_pct, density_per_km2.

- cases_query(region_id: str | None, disease: str | None, since: str | None, until: str | None) -> list[dict]
    Daily case counts. Fields: date, region_id, disease, cases.
    Dates are ISO (YYYY-MM-DD); `since`/`until` are inclusive.
    Diseases: flu, measles, covid19, rsv, pertussis, norovirus.

- deaths_query(region_id, disease, since, until) -> list[dict]
    Same signature as cases_query. Fields: date, region_id, disease, deaths.

- hospitalizations_query(region_id, disease, since, until) -> list[dict]
    Fields: date, region_id, disease, admissions, current_in_hospital.

- vaccinations_query(region_id: str | None, vaccine: str | None, since: str | None, until: str | None) -> list[dict]
    Fields: date, region_id, vaccine, doses_administered, cumulative_coverage_pct.
    Vaccines: flu_vax, mmr, covid_booster, pertussis_combo.

- outbreak_alerts(severity: str | None, active: bool | None) -> list[dict]
    Current outbreak alerts. Severities: low, moderate, high.
    Fields: id, region_id, disease, severity, started, active.

- time_series(region_id: str, metric: str, window_days: int = 30) -> dict
    Daily time series for a region. metric shapes:
    'cases:<disease>', 'deaths:<disease>', 'admissions:<disease>',
    'vacc_doses:<vaccine>', 'coverage:<vaccine>'.
    Returns {"dates": [...], "values": [...]}.

- neighbor_regions(region_id: str) -> list[str]
    IDs of regions that share a border with the given region.

Return the final answer from your code with `return <value>`.
"""

_sandbox = MontySandboxProvider(
    limits={
        "max_duration_secs": 15,
        "max_memory": 200_000_000,
        "max_recursion_depth": 100,
    }
)

# discovery_tools=[] removes search/get_schema. The catalog lives in
# execute_description, so the LLM sees everything it needs in one shot.
mcp.add_transform(
    CodeMode(
        sandbox_provider=_sandbox,
        discovery_tools=[],
        execute_description=(
            "Execute a Python script with access to the health-surveillance API.\n\n"
            + TOOL_CATALOG
        ),
    )
)


if __name__ == "__main__":
    mcp.run()
