### Path and Retention Settings

| **Variable**               | **Type** | **Default**                                       | **Description**                                                                           |
|:---------------------------|:---------|:--------------------------------------------------|:------------------------------------------------------------------------------------------|
| `mneme_backup_dir`         | string   | `/home/data/mneme_backups/backup`                 | Directory to store uncompressed backup files                                              |
| `mneme_archive_dir`        | string   | `/home/data/mneme_backups/archive`                | Directory to store compressed backup archives                                             |
| `mneme_temp_dir`           | string   | `/home/data/mneme_backups/tmp`                    | Temporary directory used during backup process                                            |
| `mneme_log_dir`            | string   | `/var/log/mariabackup`                            | Directory to store backup logs                                                            |
| `mneme_data_dir`           | string   | `/var/lib/mysql`                                  | Database location                                                                         |
| `mneme_retention_contours` | list     | complex list of daily, weekly and monthly backups | The cronjobs and the retention policy are set in this variable. See in description below. |
| `mneme_backup_cron`        | bool     | `true`                                            | Trigger activating the cronjob of regular backup                                          |
| `mneme_mailto_address`     | string   | `root@example.com`                                | Email address for cron job notifications                                                  |

### Database Connection

| **Variable**           | **Type** | **Default** | **Description**                                                                                                                                          |
|:-----------------------|:---------|:------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mneme_mysql_user`     | string   | `root`      | MySQL user for backup operations                                                                                                                         |
| `mneme_mysql_password` | string   | Not defined | Is not defined, so the role will fail without password being set (recommended to use Ansible Vault, Hashicorp Vault or another secure encrypted storage) |
| `mneme_mysql_host`     | string   | `localhost` | MySQL server host                                                                                                                                        |
| `mneme_mysql_port`     | integer  | `3306`      | MySQL server port                                                                                                                                        |
| `mneme_socket`         | string   | `""`        | MySQL socket file location                                                                                                                               |

### Backup Behavior

| **Variable**                  | **Type** | **Default**               | **Description**                                                                                                                                                                                                          |
|:------------------------------|:---------|:--------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mneme_bin_path`              | string   | `/usr/bin/mariadb-backup` | Path to the `mariadb-backup` binary                                                                                                                                                                                      |
| `mneme_mariadb_dump_bin_path` | string   | `/bin/mariadb-dump`       | Path to the `mariadb-dump` binary                                                                                                                                                                                        |
| `mneme_mariadb_bin_path`      | string   | `/bin/mariadb`            | Path to the `mariadb` binary                                                                                                                                                                                             |
| `mneme_compress`              | bool     | `true`                    | Whether to compress the backup files                                                                                                                                                                                     |
| `mneme_compression_level`     | integer  | `6`                       | Compression level (1-9) for backups                                                                                                                                                                                      |
| `mneme_pigz_processes`        | integer  | undefined                 | Number of pigz processes to use (passed as `-p n`); defaults to number of online processors                                                                                                                              |
| `mneme_nice_priority`         | integer  | `19`                      | Priority level for backup process (limits IOPS impact)                                                                                                                                                                   |
| `mneme_use_memory`            | string   | `1G`                      | Amount of memory to use during the backup preparation process                                                                                                                                                            |
| `mneme_prepare_backup`        | bool     | `true`                    | If true, backup will be prepared before archiving. It will reduce significally time of recovery process but will affect server CPU each time it creates backup. It's also incompatible with incremental backup strategy. |

### Resource Limits (cgroups)

| **Variable**           | **Type** | **Default** | **Description**                                                                                                                                               |
|:-----------------------|:---------|:------------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mneme_use_cgroups`    | bool     | `true`      | If `true`, launches the backup script via `systemd-run` with memory limits using cgroups.                                                                     |
| `mneme_ram_soft_limit` | string   | `1G`        | Soft memory limit (`MemoryHigh`). When this threshold is reached, the kernel will start to aggressively reclaim memory from the process but will not kill it. |
| `mneme_ram_hard_limit` | string   | `3G`        | Hard memory limit (`MemoryMax`). If this limit is exceeded, the OOM Killer will forcibly terminate the backup process.                                        |

### Replication Safety

| **Variable**                                     | **Type** | **Default**    | **Description**                                                                                                                                                                                                                          |
|:-------------------------------------------------|:---------|:---------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mneme_safe_slave_backup`                        | bool     | `true`         | If true, mariabackup will stop the replication SQL thread and waits to start backing up until Slave_open_temp_tables in SHOW STATUS is zero. It will wait until mneme_safe_slave_backup_timeout.                                         |
| `mneme_safe_slave_backup_timeout`                | integer  | 300            | If safe-slave-backup option is used, mariabackup will wait until this time limit is reached to close all opened tables. If not, the overall process will fail.                                                                           |
| `mneme_safe_info`                                | bool     | `false`        | This option is useful when backing up a replication slave server. It prints the binary log position and name of the master server. It also writes this information to the "mariadb_backup_slave_info" file as a "CHANGE MASTER" command. |
| `mneme_safe_slave_autorestore_replication`       | bool     | `true`         | Force the replication start if something happend during the script execution                                                                                                                                                             |
| `mneme_safe_slave_autorestore_replication_query` | string   | `START SLAVE;` | Query for the forcefull replication restart. Might be changed according your environment if needed                                                                                                                                       |
| `mneme_block_on_master`                          | bool     | `false`        | If true it will add master detection to the cron job, preventing the start. Useful when you want to set up cronjobs for several servers that may change the roles                                                                        |

### Archive Verification

| **Variable**              | **Type** | **Default** | **Description**                                                                                                        |
|:--------------------------|:---------|:------------|:-----------------------------------------------------------------------------------------------------------------------|
| `mneme_verify_archive`    | bool     | `true`      | If true, verifies the archive integrity using `tar -tzf` after creation. Corrupted archives are automatically removed. |
| `mneme_generate_checksum` | bool     | `true`      | If true, generates a SHA256 checksum file (`.sha256`) alongside each backup archive.                                   |

### Partial Backup Options

| **Variable**                      | **Type** | **Default** | **Description**                                     |
|:----------------------------------|:---------|:------------|:----------------------------------------------------|
| `mneme_databases_include`         | list     | `[]`        | List of databases to include in the backup          |
| `mneme_databases_exclude`         | list     | `[]`        | List of databases to exclude from the backup        |
| `mneme_tables_include`            | string   | `""`        | Regexp of tables to include in the backup           |
| `mneme_tables_exclude`            | string   | `""`        | Regexp of tables to exclude from the backup         |
| `mneme_databases_schemes_include` | list     | `[]`        | List of databases to include as schema-only backups |

### Legacy Monitoring

| **Variable**                              | **Type** | **Default**                                                           | **Description**                          |
|:------------------------------------------|:---------|:----------------------------------------------------------------------|:-----------------------------------------|
| `mneme_monitoring_notify_enable`          | bool     | `false`                                                               | Enable notification to monitoring system |
| `mneme_monitoring_notify_port`            | integer  | `8125`                                                                | Port for monitoring system               |
| `mneme_monitoring_notify_ip`              | string   | `127.0.0.1`                                                           | IP for monitoring system                 |
| `mneme_monitoring_notify_message_success` | string   | `mariabackup.status:1&#124;g&#124;{{ mneme_monitoring_notify_tags }}` | Success message for monitoring           |
| `mneme_monitoring_notify_message_fail`    | string   | `mariabackup.status:0&#124;g&#124;{{ mneme_monitoring_notify_tags }}` | Failure message for monitoring           |
| `mneme_monitoring_notify_tags`            | string   | `#mariabackup:{{ inventory_hostname }}`                               | Tags for monitoring message              |

### Prometheus Monitoring

| **Variable**               | **Type** | **Default**                                 | **Description**                                                                                                 |
|:---------------------------|:---------|:--------------------------------------------|:----------------------------------------------------------------------------------------------------------------|
| `mneme_prometheus_enabled` | bool     | `false`                                     | Enable generation of OpenMetrics `.prom` file for Node Exporter.                                                |
| `mneme_prometheus_dir`     | path     | `/var/lib/node_exporter/textfile_collector` | Directory watched by Node Exporter (flag `--collector.textfile.directory`). The role will create it if missing. |

### Security

| **Variable**                | **Type** | **Default** | **Description**                           |
|:----------------------------|:---------|:------------|:------------------------------------------|
| `mneme_backup_script_owner` | string   | `root`      | Owner of the backup wrapper script        |
| `mneme_backup_script_group` | string   | `root`      | Group of the backup wrapper script        |
| `mneme_backup_script_mode`  | string   | `'0755'`    | Permissions for the backup wrapper script |

### Repository Management

| **Variable**                       | **Type** | **Default**                              | **Description**                                           |
|:-----------------------------------|:---------|:-----------------------------------------|:----------------------------------------------------------|
| `mneme_install_repo`               | bool     | `false`                                  | If true, it will install the official MariaDB repository. |
| `mneme_mariadb_version`            | string   | `11.4`                                   | The version of MariaDB to install the repository for.     |
| `mneme_mariadb_repo_url_ol_7`      | string   | `http://archive.mariadb.org/...`         | MariaDB repository URL for Oracle Linux 7.                |
| `mneme_mariadb_repo_url_rocky_8_9` | string   | `http://yum.mariadb.org/...`             | MariaDB repository URL for Rocky Linux 8, 9.              |
| `mneme_mariadb_repo_url_rhel_9`    | string   | `http://yum.mariadb.org/...`             | MariaDB repository URL for Red Hat Enterprise Linux 9.    |
| `mneme_epel_repo_archive_url`      | string   | `https://archives.fedoraproject.org/...` | EPEL archive repository URL for Oracle Linux 7.           |
| `mneme_epel_repo_url`              | string   | `https://dl.fedoraproject.org/...`       | EPEL repository URL for other supported OS versions.      |
| `mneme_epel_repo_key_url`          | string   | `https://dl.fedoraproject.org/...`       | GPG key URL for EPEL repository.                          |


### Percona Xtrabackup Compatibility

| **Variable**                           | **Type** | **Default** | **Description**                                                  |
|:---------------------------------------|:---------|:------------|:-----------------------------------------------------------------|
| `mneme_xtrabackup_compatibility` | bool     | false       | If true, the role skips the installation of mariabackup package. |

### Restore & Recovery Configuration (`wiseops_team.mneme.prepare` role)

These variables are used by the `wiseops_team.mneme.prepare` role.

| **Variable**                          | **Default**                                     | **Description**                                                                                                                       |
|:--------------------------------------|:------------------------------------------------|:--------------------------------------------------------------------------------------------------------------------------------------|
| `mneme_prepare_target_date`     | `latest`                                        | The date of the backup to restore (Format: `YYYY-MM-DD`). Must be provided at runtime otherwise the latest valid backup will be used. |
| `mneme_prepare_type`            | `daily`                                         | The retention contour type to look for (`daily`, `weekly`, `monthly`).                                                                |
| `mneme_prepare_work_dir`        | `{{ mneme_temp_dir }}/restore_{{ date }}` | Directory where the backup will be unarchived. Can be overridden if you need to use a different disk partition.                       |
| `mneme_prepare_timeout` | `14400`                                         | Timeout in seconds for the `mariadb-backup --prepare` step (default: 4 hours).                                                        |
| `mneme_system_user`             | `mysql`                                         | System user that owns the database files. Crucial for permission fixing during restore.                                               |