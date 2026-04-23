---
description: Ministry of Health definition of a region-level outbreak and the canonical analysis procedure
---

# Outbreak Detection Protocol (Ministry of Health, internal)

> Synthetic test fixture. The specific thresholds below are planted so we can
> tell whether the agent actually read this skill or hallucinated a generic
> outbreak definition.

This is the **only** authoritative definition of a region-level outbreak for analytical reporting. Do not substitute a generic "cases are high" heuristic — use the rule below.

## Definition — "region in active outbreak"

A region R counts as being in active outbreak for disease D when ALL of the following hold:

1. **Eligible population**: `population(R) > 1,000,000`.
   Smaller regions are too noisy for reliable trend detection; they are handled by a separate manual follow-up process.
2. **Rate threshold**: over the last 7 days (2026-04-18 through 2026-04-24 inclusive), the total number of cases of disease D in region R satisfies:

   `sum_of_7_day_cases × 100000 / population(R) > 60.0`

3. **Disease scope**: disease D must be one of `measles`, `covid19`, `rsv`, or `pertussis`. Flu and norovirus are **excluded** — flu follows a separate seasonal protocol, and norovirus thresholds are set by a different team.

## What NOT to do

- **Do NOT** use the `outbreak_alerts` tool for this report. That table contains historical alerts including cleared ones, plus low/moderate severity items that do not meet the population threshold. Computing fresh from `cases_query` is the only correct path.
- **Do NOT** include flu or norovirus.
- **Do NOT** include regions with population ≤ 1,000,000 even if the per-100k rate is dramatic; they are noise-dominated.

## Reporting format

For each qualifying (region, disease) pair, report:
- region id
- disease
- 7-day total cases
- 7-day rate per 100k (to 2 decimals)
- population

Sort rows by rate per 100k, descending. Produce the list as a Markdown table.
