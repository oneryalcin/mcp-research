"""Compute canonical answers for the test tasks.
Run once, compare agent answers to these.
"""
import statistics
from datetime import date, timedelta

from data import END_DATE, get_dataset

ds = get_dataset()
regions_by_id = {r.id: r for r in ds.regions}

print("==" * 30)
print("GROUND TRUTH (data seed=20260424, end_date=2026-04-24)")
print("==" * 30)

# --- Task 1: Trivial lookup ------------------------------------------------
# "How many measles cases were reported in region R012 in the last 7 days
#  (2026-04-18 to 2026-04-24 inclusive)?"
since = (END_DATE - timedelta(days=6)).isoformat()
until = END_DATE.isoformat()
t1 = sum(
    r.cases
    for r in ds.day_records
    if r.region_id == "R012" and r.disease == "measles" and since <= r.date <= until
)
print(f"\nTASK 1 (trivial lookup)")
print(f"  region R012, measles, {since} to {until}")
print(f"  TRUE ANSWER: {t1} cases")

# --- Task 2: Filter + rate + rank ------------------------------------------
# "Top 5 regions by flu hospitalization rate per 100k population over the
#  last 30 days (2026-03-26 to 2026-04-24)."
since2 = (END_DATE - timedelta(days=29)).isoformat()
region_admissions = {}
for rec in ds.day_records:
    if rec.disease != "flu" or not (since2 <= rec.date <= until):
        continue
    region_admissions[rec.region_id] = region_admissions.get(rec.region_id, 0) + rec.hospital_admissions

rates = []
for rid, admissions in region_admissions.items():
    r = regions_by_id[rid]
    rate = admissions / r.population * 100_000
    rates.append((rid, r.name, rate, admissions, r.population))

rates.sort(key=lambda x: x[2], reverse=True)
print(f"\nTASK 2 (top 5 by flu hospitalization rate per 100k, last 30d)")
for rid, name, rate, adm, pop in rates[:5]:
    print(f"  {rid} {name}: {rate:.2f} per 100k  (admissions={adm}, pop={pop})")

# --- Task 3: Statistical aggregation (the mental-arithmetic target) --------
# "Compute the mean and standard deviation of per-country COVID-19
#  case-fatality ratio (deaths/cases) in Q1 2026 (2026-01-01 to 2026-03-31),
#  across countries with total population > 5_000_000."
q1_since = "2026-01-01"
q1_until = "2026-03-31"

country_pop = {}
for r in ds.regions:
    country_pop[r.country] = country_pop.get(r.country, 0) + r.population

eligible_countries = [c for c, p in country_pop.items() if p > 5_000_000]
print(f"\nTASK 3 (Q1 COVID CFR stats across countries with pop>5M)")
print(f"  eligible countries: {eligible_countries}")

country_cfrs = []
per_country_detail = {}
for c in eligible_countries:
    rids = [r.id for r in ds.regions if r.country == c]
    deaths = sum(
        r.deaths for r in ds.day_records
        if r.region_id in rids and r.disease == "covid19" and q1_since <= r.date <= q1_until
    )
    cases = sum(
        r.cases for r in ds.day_records
        if r.region_id in rids and r.disease == "covid19" and q1_since <= r.date <= q1_until
    )
    cfr = deaths / cases if cases else 0.0
    per_country_detail[c] = {"cases": cases, "deaths": deaths, "cfr": cfr}
    country_cfrs.append(cfr)
    print(f"  {c}: cases={cases}, deaths={deaths}, CFR={cfr:.6f}")

mean_cfr = statistics.mean(country_cfrs)
stdev_cfr = statistics.stdev(country_cfrs) if len(country_cfrs) > 1 else 0.0
print(f"  TRUE MEAN CFR:  {mean_cfr:.6f}  ({mean_cfr*100:.4f}%)")
print(f"  TRUE STDEV CFR: {stdev_cfr:.6f}")
