# Backup Verification & Disaster Recovery Drills

Trusting a backup without testing it is a strategy for failure. This role includes a dedicated module `mneme_verify` designed to be part of your CI/CD pipeline or nightly cron jobs.

## How It Works (The "Ephemeral" Concept)

The `mneme_verify` module performs a **Safe, Ephemeral Restore**:

1.  **Isolation:** It spins up a temporary MariaDB instance (Sidecar) reading directly from the backup files.
2.  **Sandboxing:** It creates a temporary database on the target server (e.g., `verify_a1b2c3d4`).
3.  **Restoration:** It restores the requested tables (or random ones) into this temporary database.
4.  **Validation:** It executes your specified SQL `validation_query`.
5.  **Cleanup:** It **always** drops the temporary database, regardless of success or failure.
6.  **Affects the backup** Modifies backup artifacts (Perform on copy if needed)

> **Safety Note:** The module enforces `sql_log_bin=0`, ensuring that these tests do **not** replicate to slaves and do not pollute binary logs.

## Usage Scenarios

### Scenario A: The "Smoke Test" (Random Sampling)
Check if the backup is readable and 3 random tables can be physically restored.

```yaml
- name: Smoke Test (Random Tables)
  mneme_verify:
    backup_dir: "{{ latest_backup_dir }}"
    database: "production_db" # The DB name inside the backup
    random_tables_count: 3
    validation_query: "SHOW TABLES"
```

### Scenario B: Business Logic Validation
Verify that critical data exists (e.g., "Yesterday's orders are present").

```yaml
- name: Verify Recent Orders
  mneme_verify:
    backup_dir: "{{ latest_backup_dir }}"
    database: "shop_db"
    table: 
      - "orders"
      - "order_items"
    validation_query: >-
      SELECT count(*) FROM orders 
      WHERE created_at > NOW() - INTERVAL 24 HOUR 
      HAVING count(*) > 0
```

## Module Reference: `mneme_verify`

| Argument              | Type   | Required | Description                                                    |
|:----------------------|:-------|:---------|:---------------------------------------------------------------|
| `backup_dir`          | path   | Yes      | Path to the **prepared** backup directory.                     |
| `database`            | string | Yes      | The source database name inside the backup.                    |
| `validation_query`    | string | Yes      | SQL query to run. If it fails (returns error), the task fails. |
| `table`               | list   | No*      | List of specific tables to restore.                            |
| `random_tables_count` | int    | No*      | Number of random tables to restore.                            |

*\* Mutually exclusive: use either `table` or `random_tables_count`.*
