# wiseops_team.mneme.recover

Single-role recovery orchestrator. Runs the full cycle:
prepare artifacts → restore data → cleanup workspace.

Internally uses the `wiseops_team.mneme.prepare` role,
the `wiseops_team.mneme.restore` module,
and the `wiseops_team.mneme.cleanup` role.

## When to use this role vs components directly

Use `recover` for **sidecar** and **direct** strategies — these run
with MariaDB online and need no manual steps between prepare and restore.

For **copy_back** and **move_back**, use the components directly:
you need to stop MariaDB between prepare and restore, which requires
explicit tasks in your playbook.

## Variables

| Variable | Default | Description |
|---|---|---|
| `mneme_recover_target_date` | `latest` | Date of the backup to restore (`YYYY-MM-DD` or `latest`). |
| `mneme_recover_type` | `daily` | Backup contour: `daily`, `weekly`, or `monthly`. |
| `mneme_recover_strategy` | `sidecar` | Restore strategy: `sidecar` or `direct`. |
| `mneme_recover_database` | `""` | Target database name. Required for `sidecar` and `direct`. |
| `mneme_recover_table` | `[]` | List of tables to restore. If empty, auto-discovery is used (`direct` only). |
| `mneme_recover_schema_file` | `""` | Path to schema `.sql` dump. Required by `direct` when tables were dropped. |
| `mneme_recover_force` | `false` | Required for `direct` strategy. |
| `mneme_recover_skip_cleanup` | `false` | If `true`, skips cleanup. Useful when you need `mneme_prepared_backup_dir` after the role. |


See the [Recovery Runbook](../../docs/RECOVERY_RUNBOOK.md) for full details.
