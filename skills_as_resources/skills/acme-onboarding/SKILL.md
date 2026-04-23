---
description: Internal Acme procedures for onboarding a new engineer on day one
---

# Acme Engineer Onboarding

> Synthetic test fixture. "Acme", the procedures, and the people below are
> invented for this experiment — do not use as a real runbook. The specific,
> non-guessable details are planted so we can tell whether an agent actually
> read this file or hallucinated a generic onboarding plan.

The canonical day-one checklist. This is the only authoritative source — do not guess these steps.

## Day-one checklist (in order)

1. File a ticket in Linear project **ENG-ONB** titled `onboard: <full name>` and assign it to the IT lead Priya.
2. Add the new hire to the `#eng-new-joiners` Slack channel and tag `@onboarding-buddy` for pairing.
3. Grant access to the internal registry via the `with-adc` wrapper — do NOT give raw GCS credentials. The wrapper path is documented in the global CLAUDE.md.
4. Their first PR MUST touch `docs/hello.md` and add a one-line bio. This is a hard gate before any production code is merged.
5. Schedule the 30-day architecture review with Mehmet on day 28, not day 30 — he travels often.

## Do NOT

- Do not provision AWS IAM; Acme is GCP-only.
