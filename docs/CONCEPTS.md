# Technical Concepts

## Retention Logic
The retention policies and crontab is defined in a `mneme_retention_contours` variable.
There are 3 default independent contours of backup with their own retention policies:
- daily
- weekly
- monthly

Each of the contours has it's own schedule and retention policy. The number of backups in each contour to be kept is set in 
`count` value. Each time the backup_wrapper script starts it performs the backup process and then it deletes the outdated 
archives.
So, in an example below only the last 5 daily backups will be preserved. Weekly and monthly backups are not active.

```yaml
mneme_retention_contours:
  - type: daily
    count: 5
    schedule: "0 9 * * *"
    active: true
  - type: weekly
    count: 2
    schedule: "0 12 * * 1"
    active: false
  - type: monthly
    count: 1
    schedule: "0 14 1 * *"
    active: false
```

There is also the global crontab trigger `mneme_backup_cron`. If it's false, the backup wrapper script is generated,
but the crontab jobs are not. In this case you may start the backup process manually on the server:
```shell
/usr/local/bin/mneme_wrapper.sh --type daily
```

The retention policies will be applied according to your settings at the end of the script even if it was started manually.

### Retention Policy Visualization

The retention logic uses independent contours. For example, with `daily: 5` and `weekly: 4`:

```
Imagine two separate "buckets" for backups: one for 'daily' and one for 'weekly'.

Bucket 1: Daily Backups (retains 5)
====================================
Day 1: [D1]
Day 2: [D1, D2]
Day 3: [D1, D2, D3]
Day 4: [D1, D2, D3, D4]
Day 5: [D1, D2, D3, D4, D5]
Day 6: [D2, D3, D4, D5, D6]  <-- D1 is removed
Day 7: [D3, D4, D5, D6, D7]  <-- D2 is removed

This bucket always holds the last 5 daily backup files.

Bucket 2: Weekly Backups (retains 4, runs on Sunday)
====================================================
Week 1 (Sun): [W1]
Week 2 (Sun): [W1, W2]
Week 3 (Sun): [W1, W2, W3]
Week 4 (Sun): [W1, W2, W3, W4]
Week 5 (Sun): [W2, W3, W4, W5] <-- W1 is removed

This bucket always holds the last 4 weekly backup files.

Key Points:
- The 'daily' and 'weekly' backups are managed completely independently.
- A weekly backup is just another backup file, but it's stored and counted in the 'weekly' bucket.
- The same logic applies to 'monthly' backups, which would have their own bucket.
```


## Cleanup and Locking

The backup script is designed to ensure that incomplete or partially completed backups are properly cleaned up, even if the script encounters an error, is interrupted, or fails. Here is how the cleanup process works:

1. **Lock File Management:**
   - The script uses a PID file (`/var/run/mneme_wrapper.pid`) to ensure that only one instance of the script runs at a time.
   - At the start, the script checks if a PID file already exists. If the file exists and the process ID (PID) it references is active, the script will exit, preventing multiple concurrent executions. This avoids conflicts and ensures data integrity.
   - If the PID file is found but the process is no longer active, the script will identify it as stale, remove the file, and proceed.

2. **Signal Handling:**
   - The script sets up traps to capture various signals (e.g., `SIGINT`, `SIGTERM`, `ERR`, `EXIT`). When these signals are caught, the `cleanup` function is triggered.
   - This ensures that, regardless of how the script is terminated (whether via an error, a manual interruption, or normal completion), the cleanup function will be executed.

3. **Cleanup Function:**
   - The `cleanup` function is responsible for:
     - **Removing any uncompressed or partially completed backup directories:** If the backup process is interrupted or fails, it may leave behind incomplete files. The script will remove these directories to prevent clutter and ensure consistency for the next run.
     - **Deleting the PID file:** This is done to ensure that the script can be safely started again in the future without encountering issues from a previous run.
   - This function is registered to run whenever the script exits, ensuring cleanup in all scenarios.

4. **Automatic Cleanup on Exit:**
   - Upon receiving an interrupt (e.g., `CTRL+C`) or if an error occurs (`ERR`), the script calls the `cleanup` function.
   - After completing the backup process successfully, the script disables the traps and removes the PID file, ensuring that no leftover files are present.

## Safe Slave Backup

When backuping a slave you'd better add these options:
```yaml
mneme_safe_slave_backup: true
mneme_safe_info: true
```

It is greatly recommended to use the option `mneme_safe_slave_backup` for slave backup process. If active, it stops the replication process,
waits for all the opened tables to be closed and then start the process of backup. After the backup process it returns back 
the replication. This option waits for a period of seconds defined in `mneme_safe_slave_backup_timeout` to start the replication.
If the timeout reached and some tables are still opened it will fail. Default is 300 seconds.

It would be also a good idea to include the `mneme_safe_info` option. This option is useful when backing up a replication slave server. It prints the binary log position and name of the master server.
It also writes this information to the "mariadb_backup_slave_info" file as a "CHANGE MASTER" command.
A new slave for this master can be set up by starting a slave server on this backup and issuing a "CHANGE MASTER" command 
with the binary log position saved in the "mariadb_backup_slave_info" file.

**NOTE!**
This option is not compatible with multi-channel replication as it test the node for a slave status using `SHOW SLAVE STATUS`.
It would be empty for the named channels setup. Example:
```
MariaDB [(none)]> SHOW SLAVE STATUS\G 
Empty set (0.000 sec) 
 
MariaDB [(none)]> SHOW ALL SLAVES STATUS\G 
*************************** 1. row *************************** 
              Connection_name: mysql-central-nl-1.example.com 
              Slave_SQL_State: Slave has read all relay log; waiting for more updates 
               Slave_IO_State: Waiting for master to send event
```

In such a case you'll get this in log:
```
Not checking slave open temp tables for --safe-slave-backup because host is not a slave
```
Normally, you should get this:

```
[00] 2024-12-19 11:07:12 Slave open temp tables: 0
[00] 2024-12-19 11:07:12 Slave is safe to backup
```

### Safe Slave Auto‐Restore Replication

The backup script provides an option to automatically resume replication on a slave server if it gets stopped during the backup process—even in the event of a failure. This is controlled by the variable:
When you set `mneme_safe_slave_autorestore_replication: true`, the script will, during its cleanup routine, automatically execute a SQL query to restart replication. The specific query that is executed is defined by the variable:

- **`mneme_safe_slave_autorestore_replication_query`**  
  *Type:* String  
  *Default:* `"START SLAVE;"`  

This means that by default the script will issue the command:

```sql
START SLAVE;
```

to resume replication if it has been halted by the backup process (using options like `--safe-slave-backup`).

**Important Notes:**

- **Ensuring Replication Resumption:**  
  Even if the backup process fails, the cleanup function will call this query to make sure that the replication is restarted. This prevents scenarios where the replication thread remains stopped and the database is left in an inconsistent replication state.

- **Customization for Named Channels:**  
  Some environments use named replication channels, or require a more specific command to restart replication. In such cases, you can override the default query by setting `mneme_safe_slave_autorestore_replication_query` to a custom value. For example, if your environment requires a query like:
  
  ```sql
  START SLAVE FOR CHANNEL 'my_channel';
  ```
  
  you can specify that instead, ensuring compatibility with your setup.

By enabling this option and, if necessary, customizing the resume query, you can be confident that replication will be properly resumed regardless of backup outcomes.

## Partial Restore Architecture

The partial restore process is designed to be Replication-Silent (Non-Replicating) by default. The wrapper injects `SET SESSION sql_log_bin=0` into every MySQL transaction. This isolation ensures that the complex "Partition Exchange" workflows and tablespace imports do not corrupt the replication stream, effectively treating the restore operation as a local maintenance task.

## Sandboxed Schema Parsing

To ensure 100% reliability when restoring specific tables from a full schema dump, the role utilizes a **Sandboxed Parsing Strategy**.

Instead of using fragile Regular Expressions to extract `CREATE TABLE` statements, the `wiseops_team.mneme.restore` module:
1. Creates a secure, ephemeral temporary directory with strict permissions (`0700`).
2. Initializes a minimal, blank MariaDB instance (Sandbox) within this directory.
3. Loads the schema dump into the Sandbox.
4. Queries the Sandbox for the canonical `SHOW CREATE TABLE` statement.

This guarantees that complex schemas (including JSON defaults, intricate comments, and partitioning) are parsed correctly by the database engine itself, eliminating syntax errors during recovery.