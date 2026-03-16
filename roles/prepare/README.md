# wiseops_team.mneme.prepare

Backup artifact preparation role. Handles auto-discovery, unarchiving, checksum verification, and `mariabackup --prepare --export`.

The `wiseops_team.mneme.restore` module is called separately by the user after preparation.

See the [Recovery Runbook](../../docs/RECOVERY_RUNBOOK.md) for full details.

For artifact cleanup after recovery, use the
[`wiseops_team.mneme.cleanup`](../cleanup/README.md) role.
