# Disaster Recovery Runbook: Restoring Backups

This document provides a consolidated guide for restoring MariaDB backups created by this Ansible role.
Unlike legacy methods involving manual CLI scripts, restoration is now handled via the idempotent Ansible module `wiseops_team.mneme.restore`.

## 1. Restoration Strategies

The role supports four distinct restoration strategies covering different DRP scenarios.

| Strategy      | Type     | Use Case                                                                                                                                                                          | Downtime?              |
|:--------------|:---------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-----------------------|
| **sidecar**   | Logical  | Restoring specific tables (`.ibd` + `mysqldump`). Safest method. Recommended for single tables or small batches.                                                                  | No                     |
| **direct**    | Physical | Restoring heavy tables or whole databases. Uses `DISCARD`/`IMPORT TABLESPACE`. Fastest for large data.                                                                            | No*                    |
| **copy_back** | Physical | Full Instance Recovery. Restoring the entire server from scratch.                                                                                                                 | **Yes** (Service Stop) |
| **move_back** | Physical | Time-Critical Recovery. Best for huge DBs (>1TB) or low disk space. Destructive (empties backup dir). NOT ATOMIC. Power failure during this operation results in TOTAL DATA LOSS. | **Yes** (Service Stop) |
> (*) **Note on Direct Restore:** While the server remains online, the specific tables being restored will be locked/unavailable during the `DISCARD`/`IMPORT` phase.

---

## 2. Prerequisites & Automated Preparation

Before running any restore module, use the built-in prepare role.
It automatically handles:
1.  **Unarchiving** (using `pigz` if available).
2.  **Permissions** (recursively sets ownership to `mysql` user).
3.  **Preparation** (runs `mariabackup --prepare --export`).
4.  **Idempotency** (skips if already done).

Add this task to the beginning of your playbook:

```yaml
tasks:
  - name: Prepare Backup Artifacts
    ansible.builtin.include_role:
      name: wiseops_team.mneme.prepare
      tasks_from: prepare
    vars:
      # Optional: Date of the backup (YYYY-MM-DD) or the default 'latest' will be used
      mneme_prepare_target_date: "2025-07-20"
      # Optional: 'daily' (default), 'weekly', 'monthly'
      mneme_prepare_type: "daily"

  # The helper sets these facts for you:
  # - mneme_prepared_backup_dir
  # - mneme_prepared_schema_dir
```

---

## 3. Scenarios

### ⚠️ Critical Considerations for Direct Strategy

The `direct` strategy uses the physical `DISCARD/IMPORT TABLESPACE` method. While extremely fast, it has significant operational side effects:

#### 1. Replication Desynchronization
The module forces `SET SESSION sql_log_bin=0` to import tablespaces safely.
- **Impact:** The restored data **will not** replicate to slaves. The Master will have the data, but Slaves will be unaware of it.
- **Action Required:** You **must rebuild all replicas (slaves)** immediately after a direct restore.

#### 2. Referential Integrity (Foreign Keys)
MariaDB disables Foreign Key checks during `IMPORT TABLESPACE`.
- **Impact:** It is possible to restore a child table without its parent. The database will not stop you, but the data may be logically inconsistent.
- **Action Required:** Manually verify data integrity after restore.
  Example check:
  ```sql
  -- Find orphaned rows
  SELECT child.id FROM child_table child
  LEFT JOIN parent_table parent ON child.parent_id = parent.id
  WHERE parent.id IS NULL;
  ```
  
### Scenario A: "Oops, I deleted a table" (Single Table Restore)

**Strategy:** `sidecar` (Logical)
**Method:** Spins up a temporary `mysqld` instance on the backup files and streams data to the live server.

```yaml
- name: Prepare Backup Artifacts
  ansible.builtin.include_role:
    name: wiseops_team.mneme.prepare
    tasks_from: prepare
  vars:
    mneme_prepare_target_date: "latest"
    
- name: Restore 'users' table safely
  wiseops_team.mneme.restore:
    strategy: sidecar
    backup_dir: "{{ mneme_prepared_backup_dir }}" # Fact from prepare step
    database: "very_important_database"
    table: 
      - "users"
    # Binaries (from role defaults)
    client_bin: "{{ mneme_mariadb_bin_path }}"
    dump_bin: "{{ mneme_mariadb_dump_bin_path }}"
    mysqld_bin: "{{ mneme_mysqld_bin_path }}"
    login_config: /root/.my.cnf
```

### Scenario B: "I dropped the whole client database" (Bulk Restore)

**Strategy:** `direct` (Physical + Auto-Discovery)
**Method:** If `table` is omitted, the module scans the backup directory for all `.ibd` files in the database folder and restores them one by one via `IMPORT TABLESPACE`.

```yaml
- name: Prepare Backup Artifacts
  ansible.builtin.include_role:
    name: wiseops_team.mneme.prepare
    tasks_from: prepare
  vars:
    mneme_prepare_target_date: "latest"
    
- name: Restore entire database (Auto-Discovery)
  wiseops_team.mneme.restore:
    strategy: direct
    backup_dir: "{{ mneme_prepared_backup_dir }}" # Fact from prepare step
    database: "very_important_database"
    # table: <omitted> -> triggers auto-discovery of all tables
    
    # Schema is required to re-create tables if they were dropped
    schema_file: "{{ mneme_prepared_schema_dir }}/very_important_database_schema.sql"    
    force: true # Required for Direct strategy
    
    client_bin: "{{ mneme_mariadb_bin_path }}"
    login_config: /root/.my.cnf
```

### Scenario C: "Server Crash / Disaster Recovery" (Full Instance)

**Strategy:** `copy_back`
**Method:** Stops the server, wipes `datadir`, and moves backup files into place.

```yaml
- name: FULL RESTORE (COPY-BACK)
  vars:
    mneme_prepare_target_date: "latest"
  block:
    - name: Stop MariaDB
      ansible.builtin.service: name=mariadb state=stopped

    - name: Wipe current data directory
      ansible.builtin.file:
        path: /var/lib/mysql
        state: absent

    - name: Recreate datadir
      ansible.builtin.file: 
        path: /var/lib/mysql 
        state: directory 
        owner: mysql 
        group: mysql
        mode: '0755'
        
    - name: Prepare Backup Artifacts
      ansible.builtin.include_role:
        name: wiseops_team.mneme.prepare
        tasks_from: prepare
        
    - name: Copy-Back Backup files
      wiseops_team.mneme.restore:
      strategy: copy_back
      backup_dir: "{{ mneme_prepared_backup_dir }}" # Fact from prepare step
      datadir: /var/lib/mysql
      mneme_bin: "{{ mneme_bin_path }}"
      force: true

    - name: Start MariaDB
      ansible.builtin.service: name=mariadb state=started
```
### Scenario D: "Extreme Speed / Low Disk Space" (Move-Back)

**Strategy:** `move_back`
**Use Case:** Your database is 2TB, and you only have 500GB free space left, OR you need to restore ASAP and cannot wait for file copying.
**Warning:** ⚠️ **DESTRUCTIVE OPERATION.** This strategy **moves** files from the backup directory to the data directory. The backup directory will be empty after the operation.

```yaml
- name: FULL RESTORE (MOVE-BACK)
  vars:
    mneme_prepare_target_date: "latest"
  block:
    - name: Stop MariaDB
      ansible.builtin.service: name=mariadb state=stopped

    - name: Wipe current data directory
      ansible.builtin.file:
        path: /var/lib/mysql
        state: absent

    - name: Recreate datadir
      ansible.builtin.file: 
        path: /var/lib/mysql 
        state: directory 
        owner: mysql 
        group: mysql
        mode: '0755'
        
    - name: Prepare Backup Artifacts
      ansible.builtin.include_role:
        name: wiseops_team.mneme.prepare
        tasks_from: prepare
        
    - name: Move-Back Backup files (Almost instant on same FS)
      wiseops_team.mneme.restore:
      strategy: move_back
      backup_dir: "{{ mneme_prepared_backup_dir }}" # Fact from prepare step
      datadir: /var/lib/mysql
      mneme_bin: "{{ mneme_bin_path }}"
      force: true

    - name: Start MariaDB
      ansible.builtin.service: name=mariadb state=started
```

### Scenario E: Automatic Restoration (Auto-Discovery)

To restore the absolute latest available state without specifying a date manually, use `latest`.
The role implements a **Safe Discovery Strategy**:

1.  **Scoped:** Respects `mneme_prepare_type`. If you request `daily`, it ignores newer `weekly` backups to prevent logical mismatches.
2.  **Atomic Safety:** Prioritizes completed backups with verified `.sha256` markers. It effectively protects against Race Conditions (e.g., attempting to restore while a new backup is still being written).
3.  **Fallback:** If checksum generation is disabled, it falls back to the newest raw `.tar.gz` file (with a warning).


## 4. Handling Large Datasets (Timeouts)

**⚠️ CRITICAL FOR LARGE DATABASES (>500GB)**

If your restoration process takes longer than your SSH session timeout (usually 1 hour), the Ansible connection will be dropped by firewalls or network equipment because the module "hangs" while waiting for the restore to complete.
**Result:** The restore process on the server will be terminated abruptly, leaving the database in a corrupted state.

To prevent this, you **MUST** use Ansible's native asynchronous mode (`async` and `poll`).

### Example: Asynchronous Restore (Safe for Long Operations)

```yaml
- name: FULL DISASTER RECOVERY (Async Mode)
  wiseops_team.mneme.restore:
    strategy: copy_back
    # Use the fact generated by the prepare task
    backup_dir: "{{ mneme_prepared_backup_dir }}"
    datadir: /var/lib/mysql
    mneme_bin: "{{ mneme_bin_path }}"
    force: true
    # Fire-and-forget logic to survive SSH timeouts:
    async: 28800  # Maximum allowed runtime in seconds (e.g., 8 hours)
    poll: 60      # Check status every 60 seconds
    register: restore_job

- name: Check Restore Status
  async_status:
    jid: "{{ restore_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 500  # (Optional) Usually 'poll' handles the waiting, but this is for extra safety loops
  delay: 10
```

---

## 4. Module Reference

### Common Arguments

| Argument     | Type | Description                                                             |
|--------------|------|-------------------------------------------------------------------------|
| `backup_dir` | path | **Required.** Path to the *unarchived* and *prepared* backup directory. |
| `strategy`   | str  | `sidecar` (default), `direct`, or `copy_back`/`move_back`.              |
| `temp_dir`   | path | Directory for temp sockets/files. Defaults to `/tmp`.                   |
| `force`      | bool | Required for `direct` and `copy_back`. Allows overwriting data.         |

### Binary Paths (Important)

To ensure the module uses the correct binaries defined in your role variables, always map these arguments:

```yaml
client_bin: "{{ mneme_mariadb_bin_path }}"       # /bin/mariadb
dump_bin: "{{ mneme_mariadb_dump_bin_path }}"    # /bin/mariadb-dump
mysqld_bin: "{{ mneme_mysqld_bin_path }}"        # /usr/sbin/mysqld (Needed for Sidecar)
mneme_bin: "{{ mneme_bin_path }}"          # /usr/bin/mariadb-backup (Needed for Copy-Back)

```

### Strategy-Specific Arguments

| Strategy                     | Argument      | Description                                                            |
|------------------------------|---------------|------------------------------------------------------------------------|
| **sidecar**                  | `database`    | Target database name.                                                  |
|                              | `table`       | List of tables to restore.                                             |
| **direct**                   | `database`    | Target database name.                                                  |
|                              | `table`       | List of tables. If empty, restores ALL found `.ibd` files.             |
|                              | `schema_file` | Path to `.sql` schema dump. Required if tables do not exist in the DB. |
| **copy_back**/ **move_back** | `datadir`     | Target data directory (e.g. `/var/lib/mysql`).                         |

---

## 5. Post-Restore Cleanup

To remove the temporary unarchived data and save disk space, use the `restore_cleanup` helper at the end of your playbook.

```yaml
  post_tasks:
    - name: Cleanup Restore Artifacts
      ansible.builtin.include_role:
        name: wiseops_team.mneme.prepare
        tasks_from: cleanup
      vars:
        # Must match the date used in preparation
        mneme_prepare_target_date: "2025-07-20"
```

## 6. Troubleshooting

**Error: `Sidecar mysqld failed to start`**

* **Check Permissions:** Does the `mysql` user have read access to `backup_dir`? (See Step 1).
* **Check AppArmor/SELinux:** Is the system blocking `mysqld` from reading files in `/home/data`?
* **Check Logs:** The module output will contain the stderr from the failed process.

**Error: `Insufficient disk space`**

* The module checks for free space (required space * 1.1) before starting `direct` or `copy_back`.
* Clean up old artifacts or increase volume size.

**Error: `Table ... missing and no schema file provided`**

* In `direct` strategy, if you are restoring a table that was `DROP`ped, you **must** provide `schema_file`. The module needs the `CREATE TABLE` statement to recreate the tablespace structure before importing the `.ibd` file.

