# Disaster Recovery Runbook

This document is the operational guide for restoring MariaDB from backups created by the
`wiseops_team.mneme` collection. Read section 0 before an incident occurs.

---

## 0. Before an Incident: Prepare Now

The best time to test your recovery process is now, not during an outage.

**1. Run a drill.** Verify that your backups are valid and data restores correctly:

```yaml
- role: wiseops_team.mneme.drill
  vars:
    mneme_verify_database: production_db
    mneme_verify_random_tables_count: 5
```

> The drill has zero impact on production data. It spins up an ephemeral MariaDB instance,
> restores tables into a temporary database, runs validation queries, and cleans up after itself.

**2. Keep ready-made playbooks in your repository.** Do not copy YAML from documentation
during an incident — that is a source of errors under stress. Create the files now:

```
restore_table.yml      # Scenario A — lost a table
restore_database.yml   # Scenario B — lost a database
restore_full.yml       # Scenario C — full disaster recovery
```

**3. Add `async`/`poll` to all restore playbooks upfront if your database is larger than
~100 GB.** See section 2 for details.

---

## 1. Choose Your Scenario

Find your situation in the table and jump to the corresponding scenario.

| What happened?                                  | Downtime?  | Strategy    | Scenario    |
|:------------------------------------------------|:-----------|:------------|:------------|
| A table or several tables were deleted          | Not needed | `sidecar`   | Scenario A  |
| An entire database was dropped or corrupted     | Not needed | `direct`    | Scenario B  |
| Full server crash, need to rebuild the instance | **Yes**    | `copy_back` | Scenario C  |
| Same, but database > 500 GB or low disk space   | **Yes**    | `move_back` | Scenario C2 |

---

## 2. Critical: Large Databases and Timeouts

> **Warning:** If your database exceeds ~100 GB, the restore operation will take longer than
> a typical SSH session timeout. If the connection drops mid-operation, MariaDB will be left
> in a corrupted state.

Use `async`/`poll` for all heavy restore operations. Ready-made template:

```yaml
- name: Restore (async — safe for large databases)
  wiseops_team.mneme.restore:
    strategy: "{{ strategy }}"
    backup_dir: "{{ mneme_prepared_backup_dir }}"
    # ... other parameters
  async: 28800   # maximum allowed runtime in seconds (8 hours)
  poll: 60       # check status every 60 seconds
  register: restore_job

- name: Wait for restore to complete
  ansible.builtin.async_status:
    jid: "{{ restore_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 500
  delay: 60
```

All examples in the scenarios below use synchronous calls for brevity. For large databases,
replace the `wiseops_team.mneme.restore` task with the template above.

---

## 3. Scenarios

Scenarios A and B use the `recover` role — it orchestrates prepare → restore → cleanup
automatically. Scenarios C and C2 require MariaDB to be stopped before restore, so they use
the components directly.

---

### Scenario A: "Oops, I deleted a table" (Single Table Restore)

**Strategy: `sidecar` — logical restore.**
Spins up a temporary `mysqld` on the backup files, dumps the requested tables, and imports
them into production. MariaDB stays online. Zero downtime.

> To restore several tables, list them all under `mneme_recover_table`.

```yaml
---
- name: "Scenario A: Restore deleted table"
  hosts: db_servers
  become: true

  roles:
    - role: wiseops_team.mneme.recover
      vars:
        mneme_recover_strategy: sidecar
        mneme_recover_target_date: "2026-03-15"  # or "latest"
        mneme_recover_database: production_db
        mneme_recover_table:
          - users

  post_tasks:
    - name: Verify restored data
      community.mysql.mysql_query:
        query: "SELECT count(*) FROM production_db.users"
      register: check
      failed_when: check.query_result[0][0]["count(*)"] == 0
```

---

### Scenario B: "I dropped the whole client database" (Bulk Restore)

**Strategy: `direct` — physical DISCARD/IMPORT TABLESPACE.**
MariaDB stays online, but the tables being restored are unavailable during the import phase.
Faster than `sidecar` for large datasets. If the tables were dropped, `schema_file` is required.

> **Warning: `direct` breaks replication.** The module sets `SET SESSION sql_log_bin=0` so
> the restored data does not replicate to replicas. You must rebuild all replicas immediately
> after the operation completes.

> **Note on foreign keys:** MariaDB disables `FOREIGN_KEY_CHECKS` during `IMPORT TABLESPACE`.
> It is possible to restore a child table without its parent without getting an error. Always
> verify referential integrity after a direct restore.

```yaml
---
- name: "Scenario B: Restore dropped database"
  hosts: db_servers
  become: true

  roles:
    - role: wiseops_team.mneme.recover
      vars:
        mneme_recover_strategy: direct
        mneme_recover_target_date: "latest"
        mneme_recover_database: production_db
        mneme_recover_force: true

  post_tasks:
    - name: Verify row counts
      community.mysql.mysql_query:
        query: >
          SELECT table_name, table_rows
          FROM information_schema.tables
          WHERE table_schema = "production_db"
      register: tables

    - name: Verify foreign key integrity
      community.mysql.mysql_query:
        query: >
          SELECT child.id FROM orders child
          LEFT JOIN users parent ON child.user_id = parent.id
          WHERE parent.id IS NULL LIMIT 1
      register: fk_check
      failed_when: fk_check.query_result | length > 0
```

---

### Scenario C: "Server Crash / Disaster Recovery" (Full Instance)

**Strategy: `copy_back` — physical file copy.**
Stops MariaDB, wipes `datadir`, and copies backup files into place. The `recover` role does
not support this scenario because MariaDB must be stopped between `prepare` and `restore`.
Use the components directly.

> **Database > 500 GB or low disk space?** Use Scenario C2 (`move_back`) — it moves files
> instead of copying, saving both time and disk space.

```yaml
---
- name: "Scenario C: Full instance disaster recovery"
  hosts: db_servers
  become: true
  vars:
    mneme_prepare_target_date: "latest"

  tasks:
    - name: Stop MariaDB
      ansible.builtin.service:
        name: mariadb
        state: stopped

    - name: Wipe current data directory
      ansible.builtin.file:
        path: /var/lib/mysql
        state: absent

    - name: Recreate empty data directory
      ansible.builtin.file:
        path: /var/lib/mysql
        state: directory
        owner: mysql
        group: mysql
        mode: "0755"

    - name: Prepare backup artifacts
      ansible.builtin.include_role:
        name: wiseops_team.mneme.prepare

    - name: Copy back backup files
      wiseops_team.mneme.restore:
        strategy: copy_back
        backup_dir: "{{ mneme_prepared_backup_dir }}"
        datadir: /var/lib/mysql
        mneme_bin: "{{ mneme_bin_path }}"
        force: true

    - name: Start MariaDB
      ansible.builtin.service:
        name: mariadb
        state: started

  post_tasks:
    - name: Verify MariaDB is healthy
      community.mysql.mysql_query:
        query: "SELECT 1"

    - name: Cleanup restore artifacts
      ansible.builtin.include_role:
        name: wiseops_team.mneme.cleanup
      vars:
        mneme_prepare_target_date: "{{ mneme_prepare_target_date }}"
```

---

### Scenario C2: "Extreme Speed / Low Disk Space" (Move-Back)

**Strategy: `move_back` — moves files instead of copying.**
Use this when your database exceeds ~500 GB or when you do not have enough free disk space
for a full copy. The playbook structure is identical to Scenario C — only the `strategy`
parameter changes.

> **Destructive operation:** After `move_back` the backup directory will be empty. If the
> operation is interrupted by a power failure or disk error, data will be lost permanently.
> Ensure a stable environment before running.

> Last resort only. Use move_back only when copy_back is physically impossible — insufficient disk space or a hard time constraint. Once the operation starts, there is no rollback: files are moved one by one, and an interruption at any point leaves you with neither a valid backup nor a working instance.
> Before running: confirm the backup directory is on the same filesystem as datadir (otherwise move degrades to copy anyway), ensure UPS or equivalent power stability, and make sure no other process can touch the backup directory during the operation.

```yaml
    # The only change from Scenario C:
    - name: Move back backup files
      wiseops_team.mneme.restore:
        strategy: move_back        # <-- was copy_back
        backup_dir: "{{ mneme_prepared_backup_dir }}"
        datadir: /var/lib/mysql
        mneme_bin: "{{ mneme_bin_path }}"
        force: true
```

All other steps (stop MariaDB, wipe datadir, prepare, start, verify, cleanup) are identical
to Scenario C.

---

## 4. Reference

### Recovery Strategies

| Strategy | Type | Downtime | When to use |
|:---|:---|:---|:---|
| `sidecar` | Logical | No | Restoring specific tables. Safest method. |
| `direct` | Physical | No* | Restoring a whole database. Faster for large datasets. |
| `copy_back` | Physical | **Yes** | Full DR. Copies backup files into datadir. |
| `move_back` | Physical | **Yes** | Full DR. Moves files — faster and space-efficient, but destructive. |

*\* `direct`: server stays online, but the tables being restored are locked during DISCARD/IMPORT.*

---

### `wiseops_team.mneme.restore` Module Arguments

| Argument | Type | Strategies | Description |
|:---|:---|:---|:---|
| `backup_dir` | path | all | **Required.** Path to the unpacked and prepared backup. |
| `strategy` | str | all | `sidecar` (default), `direct`, `copy_back`, `move_back`. |
| `database` | str | sidecar, direct | Target database name. Required for these strategies. |
| `table` | list | sidecar, direct | List of tables. If omitted, all `.ibd` files are auto-discovered. |
| `schema_file` | path | direct | Path to a `.sql` schema dump. Required if tables were dropped. |
| `datadir` | path | copy/move_back | Target data directory. Default: `/var/lib/mysql`. |
| `force` | bool | direct, copy/move_back | Required for `direct`, `copy_back`, and `move_back`. |
| `temp_dir` | path | all | Directory for sockets and temp files. Default: `/tmp`. |
| `login_config` | path | all | Path to `.my.cnf`. Default: `/root/.my.cnf`. |

---

### `prepare` Role Variables

| Variable | Default | Description |
|:---|:---|:---|
| `mneme_prepare_target_date` | `latest` | Backup date (`YYYY-MM-DD`) or `"latest"`. |
| `mneme_prepare_type` | `daily` | Backup contour: `daily`, `weekly`, or `monthly`. |
| `mneme_prepare_timeout` | `14400` | Timeout for `mariabackup --prepare`, in seconds. |
| `mneme_prepare_work_dir` | see defaults | Working directory. Set automatically at runtime. |

---

### Facts Set by the `prepare` Role

| Fact | Description |
|:---|:---|
| `mneme_prepared_backup_dir` | Path to the unpacked and prepared backup. Pass this to `restore`. |
| `mneme_prepared_schema_dir` | Path to the schema dump directory. Use as `schema_file` source in `direct`. |
| `mneme_prepared_runtime_work_dir` | Working directory. Passed to `cleanup` automatically when `prepare` and `cleanup` run in the same play. |