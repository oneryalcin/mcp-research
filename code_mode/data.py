"""Synthetic public-health surveillance data. Deterministic — the same
seed gives the same fixtures every time, so ground-truth values are
stable across runs."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

SEED = 20260424

COUNTRIES = ["Atlantia", "Borduria", "Cisneros", "Doravia"]
DISEASES = ["flu", "measles", "covid19", "rsv", "pertussis", "norovirus"]
VACCINES = ["flu_vax", "mmr", "covid_booster", "pertussis_combo"]

# 50 regions, 4 countries, seeded population in [150k, 8M]
NUM_REGIONS = 50
NUM_DAYS = 365
END_DATE = date(2026, 4, 24)
START_DATE = END_DATE - timedelta(days=NUM_DAYS - 1)


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    country: str
    population: int
    age_0_14_pct: float
    age_15_64_pct: float
    age_65_plus_pct: float
    density_per_km2: int


@dataclass
class DayRecord:
    date: str
    region_id: str
    disease: str
    cases: int
    deaths: int
    hospital_admissions: int
    current_in_hospital: int


@dataclass
class VaccDayRecord:
    date: str
    region_id: str
    vaccine: str
    doses_administered: int
    cumulative_coverage_pct: float


@dataclass
class OutbreakAlert:
    id: str
    region_id: str
    disease: str
    severity: str  # "low" | "moderate" | "high"
    started: str
    active: bool


@dataclass
class Dataset:
    regions: list[Region] = field(default_factory=list)
    day_records: list[DayRecord] = field(default_factory=list)
    vacc_records: list[VaccDayRecord] = field(default_factory=list)
    alerts: list[OutbreakAlert] = field(default_factory=list)
    _neighbors: dict[str, list[str]] = field(default_factory=dict)


def _build() -> Dataset:
    rng = random.Random(SEED)
    ds = Dataset()

    # Regions
    for i in range(NUM_REGIONS):
        country = COUNTRIES[i % len(COUNTRIES)]
        pop = rng.randint(150_000, 8_000_000)
        a0 = rng.uniform(14.0, 22.0)
        a65 = rng.uniform(14.0, 28.0)
        a15 = 100.0 - a0 - a65
        ds.regions.append(
            Region(
                id=f"R{i:03d}",
                name=f"{country}-District-{i + 1}",
                country=country,
                population=pop,
                age_0_14_pct=round(a0, 1),
                age_15_64_pct=round(a15, 1),
                age_65_plus_pct=round(a65, 1),
                density_per_km2=rng.randint(40, 4500),
            )
        )

    # For each region, per disease, a baseline daily incidence rate.
    disease_base = {}
    for r in ds.regions:
        disease_base[r.id] = {}
        for d in DISEASES:
            # expected daily cases per 100k, baseline
            base = rng.uniform(0.3, 8.0)
            disease_base[r.id][d] = base

    # Per-day records
    for day_idx in range(NUM_DAYS):
        cur = START_DATE + timedelta(days=day_idx)
        day_str = cur.isoformat()
        for r in ds.regions:
            for d in DISEASES:
                base = disease_base[r.id][d]
                # slight weekly seasonality
                seasonal = 1.0 + 0.25 * (1 if cur.weekday() < 5 else -1)
                expected = base * seasonal * (r.population / 100_000)
                cases = max(0, int(rng.gauss(expected, expected * 0.3)))
                # case-fatality varies by disease
                cfr = {
                    "flu": 0.001,
                    "measles": 0.002,
                    "covid19": 0.006,
                    "rsv": 0.0015,
                    "pertussis": 0.0008,
                    "norovirus": 0.0002,
                }[d]
                deaths = int(cases * cfr * rng.uniform(0.7, 1.3))
                hosp_rate = {
                    "flu": 0.03,
                    "measles": 0.05,
                    "covid19": 0.08,
                    "rsv": 0.09,
                    "pertussis": 0.04,
                    "norovirus": 0.01,
                }[d]
                admissions = int(cases * hosp_rate * rng.uniform(0.7, 1.3))
                ds.day_records.append(
                    DayRecord(
                        date=day_str,
                        region_id=r.id,
                        disease=d,
                        cases=cases,
                        deaths=deaths,
                        hospital_admissions=admissions,
                        current_in_hospital=admissions * rng.randint(3, 7),
                    )
                )

    # Vaccinations
    for r in ds.regions:
        for v in VACCINES:
            cum = rng.uniform(0.10, 0.45)  # starting coverage
            for day_idx in range(NUM_DAYS):
                cur = START_DATE + timedelta(days=day_idx)
                daily_doses = int(rng.gauss(r.population * 0.0008, r.population * 0.0002))
                daily_doses = max(0, daily_doses)
                cum = min(1.0, cum + daily_doses / r.population)
                ds.vacc_records.append(
                    VaccDayRecord(
                        date=cur.isoformat(),
                        region_id=r.id,
                        vaccine=v,
                        doses_administered=daily_doses,
                        cumulative_coverage_pct=round(cum * 100, 2),
                    )
                )

    # Outbreak alerts
    alert_id = 0
    for r in ds.regions:
        if rng.random() < 0.3:
            d = rng.choice(DISEASES)
            started_days_ago = rng.randint(3, 60)
            started = (END_DATE - timedelta(days=started_days_ago)).isoformat()
            sev = rng.choice(["low", "moderate", "high"])
            active = rng.random() < 0.7
            ds.alerts.append(
                OutbreakAlert(
                    id=f"ALT-{alert_id:04d}",
                    region_id=r.id,
                    disease=d,
                    severity=sev,
                    started=started,
                    active=active,
                )
            )
            alert_id += 1

    # Neighbors (random simple graph, ~3 neighbors per region)
    rids = [r.id for r in ds.regions]
    for r in ds.regions:
        others = [o for o in rids if o != r.id]
        rng.shuffle(others)
        ds._neighbors[r.id] = others[: rng.randint(2, 5)]

    return ds


_DATASET: Dataset | None = None


def get_dataset() -> Dataset:
    global _DATASET
    if _DATASET is None:
        _DATASET = _build()
    return _DATASET


if __name__ == "__main__":
    ds = get_dataset()
    print(f"regions={len(ds.regions)}")
    print(f"day_records={len(ds.day_records)}")
    print(f"vacc_records={len(ds.vacc_records)}")
    print(f"alerts={len(ds.alerts)} (active={sum(1 for a in ds.alerts if a.active)})")
    print(f"sample region: {ds.regions[0]}")
    print(f"sample day:    {ds.day_records[0]}")
