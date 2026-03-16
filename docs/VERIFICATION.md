# Backup Verification & Disaster Recovery Drills

Trusting a backup without testing it is a strategy for failure. This collection provides the `wiseops_team.mneme.drill` role to orchestrate verification, which internally uses the dedicated `wiseops_team.mneme.verify` module.

## How It Works (The "Ephemeral" Concept)

The `wiseops_team.mneme.verify` module performs a **Safe, Ephemeral Restore**:

1.  **Isolation:** It spins up a temporary MariaDB instance (Sidecar) reading directly from the backup files.
2.  **Sandboxing:** It creates a temporary database on the target server (e.g., `verify_a1b2c3d4`).
3.  **Restoration:** It restores the requested tables (or random ones) into this temporary database.
4.  **Validation:** It executes your specified SQL `validation_query`.
5.  **Cleanup:** It **always** drops the temporary database, regardless of success or failure.
6.  **Artifact Safety:** The role unpacks your compressed backup into a temporary workspace before running `mariabackup --prepare`. Your original `.tar.gz` archive remains untouched. 

> **Safety Note:** The validation operates entirely in a sandbox. The module enforces `sql_log_bin=0`, ensuring that the temporary schema and test queries do **not** replicate to slaves and do not pollute your binary logs.

## Usage Scenarios

### Scenario A: The "Smoke Test" (Random Sampling)
Check if the backup is readable and 3 random tables can be physically restored.

```yaml
- name: Smoke Test (Random Tables)
  hosts: db_servers
  become: true
  roles:
    - role: wiseops_team.mneme.drill
      vars:
        mneme_verify_target_date: "latest"
        mneme_verify_database: "production_db"
        mneme_verify_random_tables_count: 3
        mneme_verify_validation_query: "SHOW TABLES"
```

### Scenario B: Deep Readability Validation
Verify that critical tables are not just physically present, but that their data pages can be read without throwing corruption errors.

```yaml
- name: Verify Orders Table Integrity
  hosts: db_servers
  become: true
  roles:
    - role: wiseops_team.mneme.drill
      vars:
        mneme_verify_target_date: "latest"
        mneme_verify_database: "shop_db"
        mneme_verify_tables: 
          - "orders"
          - "order_items"
        # Reading data forces InnoDB to access the data pages, 
        # crashing the query if the .ibd file is corrupted.
        mneme_verify_validation_query: "SELECT count(id) FROM orders"
```

## Role Reference: `wiseops_team.mneme.drill`

| Variable                           | Type   | Default          | Description                                                                                                                                                                                         |
|------------------------------------|--------|------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mneme_verify_target_date`         | string | `"latest"`       | The backup date to verify (`YYYY-MM-DD` or `"latest"`).                                                                                                                                             |
| `mneme_verify_type`                | string | `"daily"`        | The backup contour (`daily`, `weekly`, `monthly`).                                                                                                                                                  |
| `mneme_verify_database`            | string | `""`             | **Required.** The source database name inside the backup.                                                                                                                                           |
| `mneme_verify_validation_query`    | string | *(see defaults)* | Required. SQL query to run. Fails if the database engine returns an error (e.g., syntax error, table corruption, or missing data structures). Note: The drill will not fail on an empty result set. |
| `mneme_verify_tables`              | list   | `[]`             | List of specific tables to restore.                                                                                                                                                                 |
| `mneme_verify_random_tables_count` | int    | `3`              | Number of random tables to restore. Used if `mneme_verify_tables` is empty.                                                                                                                         |

*(Note: Advanced users can call the `wiseops_team.mneme.verify` module directly if custom artifact preparation is required).*
