---
description: Incident response runbook for Acme production outages
---

# Acme Incident Runbook

> Synthetic test fixture. Do not use as a real runbook.

Follow this exactly during a SEV-1.

1. Page the on-call via PagerDuty service `acme-core`.
2. Open an incident channel named `#inc-YYYYMMDD-<short>`.
3. Post the status update to `status.acme.example` using the `status-cli publish` command.
4. Do not restart the `task-service` pod without first snapshotting its state.
