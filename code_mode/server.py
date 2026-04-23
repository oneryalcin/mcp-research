"""Public-health surveillance MCP server.

Two modes, selected by env var CODEMODE_MODE:
  - "native"    → expose 9 tools directly (the classic MCP shape)
  - "codemode"  → same 9 tools, but wrapped in fastmcp's CodeMode transform
                  so clients see only search + get_schema + execute

Run:
  CODEMODE_MODE=native   uv run --with 'fastmcp[code-mode]' python server.py
  CODEMODE_MODE=codemode uv run --with 'fastmcp[code-mode]' python server.py
"""
from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from data import DISEASES, VACCINES, get_dataset

mcp = FastMCP("health-surveillance")


@mcp.tool
def regions_list(country: str | None = None) -> list[dict]:
    """List surveillance regions with basic demographics.

    Args:
        country: optional filter by country name.
    """
    ds = get_dataset()
    out = []
    for r in ds.regions:
        if country and r.country != country:
            continue
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "country": r.country,
                "population": r.population,
            }
        )
    return out


@mcp.tool
def region_get(region_id: str) -> dict:
    """Full demographic profile for a single region."""
    ds = get_dataset()
    for r in ds.regions:
        if r.id == region_id:
            return {
                "id": r.id,
                "name": r.name,
                "country": r.country,
                "population": r.population,
                "age_0_14_pct": r.age_0_14_pct,
                "age_15_64_pct": r.age_15_64_pct,
                "age_65_plus_pct": r.age_65_plus_pct,
                "density_per_km2": r.density_per_km2,
            }
    raise ValueError(f"no such region: {region_id}")


def _filter_days(
    region_id: str | None,
    disease: str | None,
    since: str | None,
    until: str | None,
) -> list:
    ds = get_dataset()
    out = []
    for rec in ds.day_records:
        if region_id and rec.region_id != region_id:
            continue
        if disease and rec.disease != disease:
            continue
        if since and rec.date < since:
            continue
        if until and rec.date > until:
            continue
        out.append(rec)
    return out


@mcp.tool
def cases_query(
    region_id: str | None = None,
    disease: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Daily case counts, filterable by region, disease, and date range.

    Dates are ISO strings (YYYY-MM-DD). Returns one record per (day, region, disease).
    Diseases: flu, measles, covid19, rsv, pertussis, norovirus.
    """
    return [
        {"date": r.date, "region_id": r.region_id, "disease": r.disease, "cases": r.cases}
        for r in _filter_days(region_id, disease, since, until)
    ]


@mcp.tool
def deaths_query(
    region_id: str | None = None,
    disease: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Daily death counts, same filters as cases_query."""
    return [
        {"date": r.date, "region_id": r.region_id, "disease": r.disease, "deaths": r.deaths}
        for r in _filter_days(region_id, disease, since, until)
    ]


@mcp.tool
def hospitalizations_query(
    region_id: str | None = None,
    disease: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Daily hospital admissions + current inpatient counts, same filters."""
    return [
        {
            "date": r.date,
            "region_id": r.region_id,
            "disease": r.disease,
            "admissions": r.hospital_admissions,
            "current_in_hospital": r.current_in_hospital,
        }
        for r in _filter_days(region_id, disease, since, until)
    ]


@mcp.tool
def vaccinations_query(
    region_id: str | None = None,
    vaccine: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Daily vaccination doses + cumulative coverage percent.

    Vaccines: flu_vax, mmr, covid_booster, pertussis_combo.
    """
    ds = get_dataset()
    out = []
    for rec in ds.vacc_records:
        if region_id and rec.region_id != region_id:
            continue
        if vaccine and rec.vaccine != vaccine:
            continue
        if since and rec.date < since:
            continue
        if until and rec.date > until:
            continue
        out.append(
            {
                "date": rec.date,
                "region_id": rec.region_id,
                "vaccine": rec.vaccine,
                "doses_administered": rec.doses_administered,
                "cumulative_coverage_pct": rec.cumulative_coverage_pct,
            }
        )
    return out


@mcp.tool
def outbreak_alerts(severity: str | None = None, active: bool | None = None) -> list[dict]:
    """Current outbreak alerts. Severities: low, moderate, high."""
    ds = get_dataset()
    out = []
    for a in ds.alerts:
        if severity and a.severity != severity:
            continue
        if active is not None and a.active != active:
            continue
        out.append(
            {
                "id": a.id,
                "region_id": a.region_id,
                "disease": a.disease,
                "severity": a.severity,
                "started": a.started,
                "active": a.active,
            }
        )
    return out


@mcp.tool
def time_series(region_id: str, metric: str, window_days: int = 30) -> dict:
    """Daily time series for a region and metric over the last N days.

    metric: 'cases:<disease>', 'deaths:<disease>', 'admissions:<disease>',
            'vacc_doses:<vaccine>', 'coverage:<vaccine>'.
    Returns {"dates": [...], "values": [...]} with len == window_days.
    """
    ds = get_dataset()
    kind, _, key = metric.partition(":")
    dates, values = [], []
    if kind in ("cases", "deaths", "admissions"):
        recs = [r for r in ds.day_records if r.region_id == region_id and r.disease == key]
    elif kind in ("vacc_doses", "coverage"):
        recs = [r for r in ds.vacc_records if r.region_id == region_id and r.vaccine == key]
    else:
        raise ValueError(f"unknown metric kind: {kind}")
    recs = sorted(recs, key=lambda r: r.date)[-window_days:]
    for r in recs:
        dates.append(r.date)
        if kind == "cases":
            values.append(r.cases)
        elif kind == "deaths":
            values.append(r.deaths)
        elif kind == "admissions":
            values.append(r.hospital_admissions)
        elif kind == "vacc_doses":
            values.append(r.doses_administered)
        elif kind == "coverage":
            values.append(r.cumulative_coverage_pct)
    return {"dates": dates, "values": values}


@mcp.tool
def neighbor_regions(region_id: str) -> list[str]:
    """IDs of regions that share a border with the given region."""
    ds = get_dataset()
    return list(ds._neighbors.get(region_id, []))


# Optional: apply CodeMode transform
MODE = os.environ.get("CODEMODE_MODE", "native").lower()
if MODE == "codemode":
    from fastmcp.experimental.transforms.code_mode import CodeMode, MontySandboxProvider

    sandbox = MontySandboxProvider(
        limits={
            "max_duration_secs": 15,
            "max_memory": 200_000_000,
            "max_recursion_depth": 100,
        }
    )
    mcp.add_transform(CodeMode(sandbox_provider=sandbox))
elif MODE != "native":
    raise SystemExit(f"CODEMODE_MODE must be 'native' or 'codemode', got {MODE!r}")


if __name__ == "__main__":
    mcp.run()
