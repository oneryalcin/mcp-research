"""Ground truth for the outbreak-protocol task (t4).

Applies the exact rules from skills/outbreak-protocol/SKILL.md:
- population > 1,000,000
- 7-day (2026-04-18..2026-04-24) rate per 100k > 8.0
- disease in {measles, covid19, rsv, pertussis}
- sort by rate descending
"""
from datetime import date, timedelta

from data import END_DATE, get_dataset

ALLOWED_DISEASES = {"measles", "covid19", "rsv", "pertussis"}
MIN_POP = 1_000_000
RATE_THRESHOLD = 60.0

ds = get_dataset()
since = (END_DATE - timedelta(days=6)).isoformat()
until = END_DATE.isoformat()

regions_by_id = {r.id: r for r in ds.regions}
sum_by_region_disease: dict[tuple[str, str], int] = {}
for rec in ds.day_records:
    if rec.disease not in ALLOWED_DISEASES:
        continue
    if not (since <= rec.date <= until):
        continue
    key = (rec.region_id, rec.disease)
    sum_by_region_disease[key] = sum_by_region_disease.get(key, 0) + rec.cases

rows = []
for (rid, disease), total in sum_by_region_disease.items():
    r = regions_by_id[rid]
    if r.population <= MIN_POP:
        continue
    rate = total * 100_000 / r.population
    if rate <= RATE_THRESHOLD:
        continue
    rows.append((rid, disease, total, rate, r.population))

rows.sort(key=lambda x: -x[3])

print("TASK 4 — Regions in active outbreak per Ministry protocol")
print(f"  window: {since} to {until}")
print(f"  rule: pop>{MIN_POP}, rate/100k>{RATE_THRESHOLD}, disease in {sorted(ALLOWED_DISEASES)}")
print()
print(f"{'rank':>4}  {'region':6}  {'disease':10}  {'cases':>6}  {'rate/100k':>9}  {'pop':>10}")
for i, (rid, disease, total, rate, pop) in enumerate(rows, 1):
    print(f"{i:4d}  {rid:6}  {disease:10}  {total:6d}  {rate:9.2f}  {pop:10d}")
print(f"\nTotal qualifying rows: {len(rows)}")
