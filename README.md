[![CI](https://github.com/WiseOpsTeam/mneme/actions/workflows/ci.yml/badge.svg)](https://github.com/WiseOpsTeam/mneme/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ansible Version](https://img.shields.io/badge/ansible-v2.16%20%2B-blue)](https://galaxy.ansible.com/ui/repo/published/wiseops_team/mneme/)
[![Platforms](https://img.shields.io/badge/platforms-EL%208%20|%209-lightgrey)](https://galaxy.ansible.com/ui/repo/published/wiseops_team/mneme/)
# **mneme** - MySQL Native Ephemeral Management Engine

**Production-Grade Backup & Disaster Recovery as Code for MariaDB.**

An enterprise-grade Ansible collection designed to manage the full lifecycle of data protection. Unlike legacy roles that merely configure cron jobs, `mneme` treats restoration as a first-class citizen.
It includes dedicated custom Ansible modules (`wiseops_team.mneme.restore`, `wiseops_team.mneme.verify`) that enable **Declarative Recovery**, allowing you to integrate disaster recovery drills directly into your CI/CD pipelines.

## Quick Start

**0. Install the collection**

The recommended way to install is via a `requirements.yml` file:

```yaml
---
collections:
  - name: wiseops_team.mneme
    source: https://galaxy.ansible.com
```

Install it using ansible-galaxy:
```
ansible-galaxy collection install -r requirements.yml
```

Or install directly:
```
ansible-galaxy collection install wiseops_team.mneme
```

**1. Add to your Playbook:**
```yaml
- hosts: db_servers
  roles:
    - role: wiseops_team.mneme.backup
```

**2. Configure in `group_vars/db_servers.yml`:**

```yaml
# This is the only mandatory variable you need to set.
mneme_mysql_password: "YOUR_SECURE_PASSWORD_HERE"
```

This will configure a daily backup job at 9 AM server time, keeping the 5 most recent backups.

## Collection Structure

The collection is organized into three roles:

| Role | Description |
|:-----|:------------|
| `wiseops_team.mneme.backup` | Installation, configuration, cron scheduling, retention, and monitoring. |
| `wiseops_team.mneme.restore` | Preparation of backup artifacts (unarchiving, permissions, `--prepare --export`). |
| `wiseops_team.mneme.verify` | Automated backup verification drills using ephemeral restore. |

And two custom modules:

| Module | Description |
|:-------|:------------|
| `wiseops_team.mneme.restore` | Declarative recovery module supporting sidecar, direct, copy_back, and move_back strategies. |
| `wiseops_team.mneme.verify` | Safe backup verification via ephemeral restore and validation query execution. |

## Capabilities

- Full support for RHEL/CentOS systems for managing `mariabackup` configuration and scheduling.
- Automated backups using `mariabackup`, with options for compression and retention management.
- **Native Ansible Restore Module:** Includes a custom python module `wiseops_team.mneme.restore` for declarative recovery. No more manual CLI scripts.
- **Automated Backup Verification (Drills):**
  - Includes a dedicated `wiseops_team.mneme.verify` module for CI/CD pipelines.
  - **Ephemeral Testing:** Spins up a temporary instance, restores random or specific tables to a sandbox, runs validation queries, and cleans up. 
  - **Zero Impact:** Guaranteed isolation from production data. Modifies backup artifacts though. Perform on copy if needed.
- **Flexible Recovery Strategies:** Supports four modes:
  - `sidecar`: Safe logical restore of specific tables using a temporary instance.
  - `direct`: Fast physical restore for large datasets using `DISCARD/IMPORT TABLESPACE`.
  - `copy_back`: Full instance disaster recovery (Standard).
  - `move_back`: **Instant** full recovery for massive datasets (Moves files instead of copying, saving I/O and disk space).
- **Partitioned Tables Support:** Fully automated restoration of partitioned InnoDB tables in `direct` mode. The module transparently handles the complex "Exchange Partition" workflow to bypass MariaDB's `DISCARD TABLESPACE` limitations.
- Partial compatibility with similar utility Percona Xtrabackup. See below.
- **Enterprise-Grade Restoration:**
  - **Sandboxed Parsing:** Uses an ephemeral MariaDB instance to parse schemas safely, handling complex table structures and comments without regex errors.
- **Smart helpers** to automate the tedious parts of recovery:
  - **Auto-Discovery & Unarchiving:** No need to manually find files or run `tar`.
  - **Smart Preparation:** Idempotent `prepare` step. If the backup is already unpacked and prepared, it skips the heavy lifting.
  - **Permission Safety:** Automatically handles `root` vs `mysql` user ownership issues.
- **Semantic hints** for the typical errors
- **Internal security**: SQL injection and path traversal detection

## Requirements

1. **Ansible Version**: Ansible 9.11.0 (ansible-core 2.16.x) recommended. Requires community.general and community.mysql collections (declared as dependencies).
2. **SSH Access**: The Ansible user must have SSH access to the instance via `ansible.rsa` key.
3. **MySQL/MariaDB**: The target system must have a MySQL/MariaDB instance installed and configured.

## Basic Configuration

| **Variable**                     | **Type** | **Default**                                       | **Description**                                                                                                                                          |
|:---------------------------------|:---------|:--------------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mneme_mysql_password`     | string   | Not defined                                       | Is not defined, so the role will fail without password being set (recommended to use Ansible Vault, Hashicorp Vault or another secure encrypted storage) |
| `mneme_backup_dir`         | string   | `/home/data/mneme_backups/backup`           | Directory to store uncompressed backup files                                                                                                             |
| `mneme_archive_dir`        | string   | `/home/data/mneme_backups/archive`          | Directory to store compressed backup archives                                                                                                            |
| `mneme_retention_contours` | list     | complex list of dayly, weekly and monthly backups | Defines the backup schedule and retention policy. See [Retention Logic](docs/CONCEPTS.md#retention-logic) for a detailed explanation.                    |
| `mneme_mailto_address`     | string   | `root@example.com`                                | Email address for cron job notifications                                                                                                                 |

> A complete reference of all available variables can be found in **[docs/VARIABLES.md](docs/VARIABLES.md)**.

## Common Usage Scenarios

Below are common configurations for specific use cases. You can add these variables to your `group_vars` or `host_vars`.

### Backing up a Replica (Slave) Server

To ensure a consistent and safe backup from a replica server, the role can temporarily stop the replication SQL thread. This prevents changes from occurring during the backup process.

```yaml
# Pauses replication and captures the master's binary log position.
mneme_safe_slave_backup: true
mneme_safe_info: true

# Ensures replication is restarted even if the backup script fails.
mneme_safe_slave_autorestore_replication: true
```

- `mneme_safe_slave_backup`: Stops the replica SQL thread and waits for open temporary tables to close before starting the backup.
- `mneme_safe_info`: Saves the master's binary log coordinates, which is essential for setting up a new replica from this backup.

> For a detailed explanation of how this works, see the [Safe Slave Backup](docs/CONCEPTS.md#safe-slave-backup) concept guide.

### Limiting Resource Usage (cgroups)

To prevent the backup process from impacting server performance, you can run it within a `systemd` cgroup to limit its memory and CPU usage.

```yaml
# Enable the use of cgroups via systemd-run.
mneme_use_cgroups: true

# Set memory limits.
mneme_ram_soft_limit: "2G"
mneme_ram_hard_limit: "4G"
```

- `mneme_ram_soft_limit`: A soft limit (`MemoryHigh`). The kernel will start reclaiming memory aggressively if the process exceeds this, but it won't be killed.
- `mneme_ram_hard_limit`: A hard limit (`MemoryMax`). If the process exceeds this, the Out-of-Memory (OOM) killer will terminate it, preventing swapping.

### Partial and Schema-Only Backups

You can fine-tune your backups to include or exclude specific databases and tables. This is useful for large environments or for backing up only critical data.

```yaml
# Back up only the 'customers' and 'products' databases.
mneme_databases_include:
  - "customers"
  - "products"

# Exclude all tables that start with 'log_' or 'tmp_'.
mneme_tables_exclude: "^(log_|tmp_).*"

# Additionally, back up the schema (but not the data) for the 'analytics' database.
mneme_databases_schemes_include:
  - "analytics"
```

- `mneme_databases_include`: A list of database names to include in the full backup.
- `mneme_tables_exclude`: A regular expression to match table names you wish to exclude.
- `mneme_databases_schemes_include`: A list of databases for which only the schema (`CREATE TABLE` statements) will be dumped. This is stored in a separate archive.

## Advanced Concepts

For a deeper understanding of the collection's internal workings, including script logic, cleanup procedures, and replication handling, please refer to our **[Technical Concepts Guide](docs/CONCEPTS.md)**.

## Backup Verification (CI/CD)

Validate your backups nightly without touching production data:

```yaml
- name: Nightly Drill - Verify 3 Random Tables
  wiseops_team.mneme.verify:
    backup_dir: "/home/data/mneme_backups/backup/daily-2025-12-25"
    database: "production_db"
    random_tables_count: 3
    validation_query: "SELECT count(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
```
Refer to the **[Verification Guide](docs/VERIFICATION.md)** and the `wiseops_team.mneme.verify` module.

## Restoring from Backup

Recovery is handled via the custom `wiseops_team.mneme.restore` module and helper tasks.
Here is a complete, compact playbook to restore a specific table from a specific date:

```yaml
---
- name: Disaster Recovery - Restore Single Table
  hosts: db_servers
  become: true
  vars:
    # 1. Define the target
    mneme_restore_target_date: "2025-10-20"
    target_db: "production_db"
    target_table: "users"

  tasks:
    # 2. Auto-discovery, Unarchiving & Preparation
    - name: Prepare Backup Artifacts
      ansible.builtin.include_role:
        name: wiseops_team.mneme.restore
        tasks_from: prepare

    # 3. Restore (Sidecar strategy: zero downtime, specific table)
    - name: Restore Table
      wiseops_team.mneme.restore:
        strategy: sidecar
        backup_dir: "{{ mneme_prepared_backup_dir }}" # Fact from prepare step
        database: "{{ target_db }}"
        table: ["{{ target_table }}"]

    # 4. Cleanup workspace
    - name: Cleanup Temp Files
      ansible.builtin.include_role:
        name: wiseops_team.mneme.restore
        tasks_from: cleanup
```

For detailed scenarios (Full Recovery, Point-in-Time, Direct Restore), see the **[Disaster Recovery Runbook](docs/RECOVERY_RUNBOOK.md)**.

## Observability & Monitoring

Stop relying on email silence. This collection treats backups as measurable metrics.

- **Prometheus (Recommended):** Generates `.prom` files for Node Exporter's Textfile Collector.
  - Metrics: `last_run_timestamp`, `last_status`, `duration_seconds`, `size_bytes`.
  - Labels: `type` (daily/weekly), `db_host`.
- **Legacy UDP:** Supports fire-and-forget StatsD packets.

Read **[docs/MONITORING.md](docs/MONITORING.md)** for configuration details and ready-to-use **PromQL Alerting Rules**.

## TODO

- check-mode for the recovery and verification modules
- Post-backup hooks to call encryption/rclone or trigger something similar (mneme_post_backup_cmd/mneme_post_backup_failed_cmd)
- Selinux enforcement support
- Ubuntu/Debian support
- xtrabackup/mysql support with full test cases

## License

Licensed under the MIT License.

## Author Information

Maintained by:
    **Ivan Gumeniuk**
