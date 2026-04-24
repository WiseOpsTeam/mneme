## [2.2.2] - 2026-04-24
Changed directory logic creation. Now the permission change may fail. It might be normal on NFS-shares

## [2.2.1] - 2026-04-24
Added the dynamic disk space pre-check before backup start
Queries information_schema to determine actual MySQL data size (excludes binlogs, relay logs, redo logs) and verifies sufficient free space on backup and archive partitions before starting.
Supports same-partition and split-partition layouts with configurable thresholds (mneme_precheck_raw_percent, mneme_precheck_compressed_percent). On failure, writes Prometheus metric for instant alerting

## [2.2.0] - 2026-03-16

### Breaking Changes

* **Role Rename:** `wiseops_team.mneme.restore` role renamed to `wiseops_team.mneme.prepare`
  to eliminate naming conflict with the `wiseops_team.mneme.restore` module.
* **Role Rename:** `wiseops_team.mneme.verify` role renamed to `wiseops_team.mneme.drill`
  to eliminate naming conflict with the `wiseops_team.mneme.verify` module.
* **Role Split:** `wiseops_team.mneme.prepare` no longer accepts `tasks_from: cleanup`.
  Cleanup is now a separate role `wiseops_team.mneme.cleanup`.
* **Variable Rename:** Recovery variables renamed for consistency with the `prepare` role:
  * `mneme_restore_target_date` → `mneme_prepare_target_date`
  * `mneme_restore_type` → `mneme_prepare_type`
  * `mneme_restore_work_dir` → `mneme_prepare_work_dir`
  * `mneme_restore_prepare_timeout` → `mneme_prepare_timeout`

### New Roles

* **`wiseops_team.mneme.cleanup`:** Dedicated role for removing the working directory
  created by the `prepare` role. Replaces `include_role: tasks_from: cleanup` pattern.
* **`wiseops_team.mneme.recover`:** Full recovery orchestrator — wraps prepare → restore
  → cleanup in a single role call. Designed for `sidecar` and `direct` strategies.
  Supports `mneme_recover_skip_cleanup: true` to retain the workspace for inspection.

### Migration

Replace in your playbooks:
```yaml
# Prepare: tasks_from no longer needed
- include_role:
    name: wiseops_team.mneme.prepare
    tasks_from: prepare          # remove this line

# Cleanup: use dedicated role
- include_role:
    name: wiseops_team.mneme.prepare
    tasks_from: cleanup
  vars:
    mneme_restore_target_date: "..."
# becomes:
- include_role:
    name: wiseops_team.mneme.cleanup
  vars:
    mneme_prepare_target_date: "..."

# Or replace the entire prepare → restore → cleanup block with:
- role: wiseops_team.mneme.recover
  vars:
    mneme_recover_strategy: sidecar
    mneme_recover_target_date: "..."
    mneme_recover_database: my_db
    mneme_recover_table: [my_table]
```

For `copy_back` and `move_back` strategies, continue using the components
directly — `recover` does not support strategies that require stopping
MariaDB between prepare and restore.

Replace in your playbooks:
  - `include_role: name: wiseops_team.mneme.restore` → `include_role: name: wiseops_team.mneme.prepare`
  - `role: wiseops_team.mneme.verify` → `role: wiseops_team.mneme.drill`
Module calls (`wiseops_team.mneme.restore:` and `wiseops_team.mneme.verify:` as tasks) remain unchanged.

## [2.0.0] - 2026-02-22

This is a major architectural release. `mneme` has evolved from a simple cron-job configuration tool into a comprehensive **Disaster Recovery as Code** solution. 

### Major Features (New)
* **Declarative Recovery (`mneme_restore`):** Introduced a native custom Ansible module to handle database restoration. No more manual CLI scripts. Supports four recovery strategies: `sidecar`, `direct`, `copy_back`, and `move_back`.
* **Automated Verification Drills (`mneme_verify`):** Introduced a new module for CI/CD pipelines. It spins up an ephemeral, sandboxed MariaDB instance to safely restore and test data integrity without impacting production.
* **Smart Helpers:** Added `restore_prepare` and `restore_cleanup` tasks for auto-discovery, idempotent unarchiving, and automatic handling of `latest` backups with SHA256 integrity checks.
* **Observability:** Built-in support for Prometheus Node Exporter (Textfile Collector). Backups now generate `.prom` files exposing metrics like `last_status`, `duration_seconds`, and `size_bytes`.

### Infrastructure & Testing
* **Full CI/CD Pipeline:** Implemented comprehensive automated testing using Molecule and Docker (Sibling Containers architecture).
* **E2E Test Suite:** Tests now cover complex scenarios including partitioned tables restoration, idempotency, path traversal prevention, and MySQL schema parsing edge cases.
