#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2024, Ivan Gumeniuk <WiseOps>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

DOCUMENTATION = r'''
---
module: verify
short_description: Safe backup verification module (Ephemeral Restore).
description:
  - Spins up a temporary MariaDB instance on backup files (Sidecar).
  - Restores selected or random tables into a TEMPORARY database on the target server.
  - Runs a validation SQL query.
  - Automatically DROPS the temporary database after execution (even on failure).
  - Designed for CI/CD and Disaster Recovery Drills.
options:
  backup_dir:
    description: Path to PREPARED backup directory.
    type: path
    required: true
  database:
    description: Source database name INSIDE the backup.
    type: str
    required: true
  table:
    description: Specific list of tables to verify. Mutually exclusive with random_tables_count.
    type: list
    elements: str
  random_tables_count:
    description: Number of random tables to select for verification.
    type: int
  validation_query:
    description: SQL query to run against the restored temporary database.
    type: str
    required: true
  # --- Binary Paths ---
  client_bin:
    description: Path to mariadb/mysql client binary.
    type: path
  dump_bin:
    description: Path to mariadb-dump/mysqldump binary.
    type: path
  mysqld_bin:
    description: Path to mysqld binary.
    type: path
  # --- Environment ---
  temp_dir:
    description: Directory for sockets and temp files.
    type: path
  login_config:
    description: Path to .my.cnf.
    type: path
    default: /root/.my.cnf
  system_user:
    description: System user owning the database files.
    type: str
    default: mysql
author:
  - Ivan Gumeniuk (@meklon)
'''

EXAMPLES = r'''
- name: Verify backup by restoring 3 random tables
  wiseops_team.mneme.verify:
    backup_dir: /backups/daily/today
    database: production_db
    random_tables_count: 3
    validation_query: "SELECT count(*) FROM information_schema.tables WHERE table_schema = DATABASE()"

- name: Deep content verification
  wiseops_team.mneme.verify:
    backup_dir: /backups/daily/today
    database: production_db
    table: ["orders", "users"]
    validation_query: "SELECT 1 FROM orders WHERE created_at > NOW() - INTERVAL 1 DAY LIMIT 1"
'''

import uuid
import random
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wiseops_team.mneme.plugins.module_utils.common import (
    get_binary, exec_sql, discover_tables, BackupSidecar, run_cmd, fail_with_hint
)


def run_verify(module, params):
    backup_dir = params['backup_dir']
    src_db = params['database']

    # 1. Determine tables to restore
    tables = params.get('table')
    random_count = params.get('random_tables_count')

    if not tables and not random_count:
        module.fail_json(msg="Either 'table' list or 'random_tables_count' must be provided.")

    if random_count:
        all_tables = discover_tables(module, backup_dir, src_db)
        if not all_tables:
            module.fail_json(msg=f"No tables found in backup for database '{src_db}'")

        # If requested more than available, take all
        count = min(random_count, len(all_tables))
        tables = random.sample(all_tables, count)
        module.log(f"Selected random tables for verification: {tables}")

    # 2. Generate Ephemeral DB Name
    # verify_<8_random_chars>
    temp_db_name = "verify_" + str(uuid.uuid4())[:8]

    # Binaries
    mysqld_bin = get_binary(module, params['mysqld_bin'], 'mysqld')
    dump_bin = get_binary(module, params['dump_bin'], 'mariadb-dump')
    client_bin = get_binary(module, params['client_bin'], 'mariadb')
    login_config = params['login_config']
    sys_user = params['system_user']
    temp_dir = params.get('temp_dir')

    try:
        # 3. Create Temporary Database on Target
        # Note: exec_sql enforces sql_log_bin=0, so this won't replicate
        exec_sql(module, client_bin, login_config, None, f"CREATE DATABASE `{temp_db_name}`")

        # 4. Start Sidecar & Pipe Data
        with BackupSidecar(module, mysqld_bin, backup_dir, sys_user, temp_dir) as sidecar:

            dump_cmd = [
                           dump_bin,
                           f"--socket={sidecar.socket_path}",
                           "--add-drop-table",
                           "--quick",
                           "--single-transaction",
                           src_db
                       ] + tables

            # Restore into the TEMP database, not the source name
            restore_cmd = [
                client_bin,
                f"--defaults-file={login_config}",
                "--init-command=SET SESSION sql_log_bin=0; SET FOREIGN_KEY_CHECKS=0;",
                temp_db_name
            ]

            # Pipe: dump -> restore
            # module.run_command does not support inter-process pipes natively,
            # so we shell out intentionally for this pipeline.
            shell_cmd = ' '.join(dump_cmd) + ' | ' + ' '.join(restore_cmd)
            rc, _, err = module.run_command(['/bin/sh', '-c', shell_cmd])
            if rc != 0:
                raise Exception(f"Dump|restore pipeline failed: {err}")

        # 5. Run Validation Query
        val_query = params['validation_query']

        # We manually construct the command with check=False to catch the error
        # instead of letting run_cmd kill the script immediately.
        # Enforcing same safety as exec_sql (no binlog, no FK checks)
        full_query = f"SET SESSION sql_log_bin=0; SET FOREIGN_KEY_CHECKS=0; {val_query}"

        cmd = [
            client_bin,
            f"--defaults-file={login_config}",
            '-N', '-B',
            '-e', full_query,
            temp_db_name
        ]

        out, err, rc = run_cmd(module, cmd, check=False)

        if rc != 0:
            # Raise exception to be caught by the outer try/except block
            raise Exception(f"SQL Error: {err}")

        module.exit_json(
            changed=False,
            msg=f"Verification successful. Restored {len(tables)} tables to {temp_db_name} and passed validation.",
            tables_verified=tables
        )

    except Exception as e:
        # Now this block will catch SQL errors too
        module.fail_json(msg="Verification failed", error=str(e))

    finally:
        # 6. Cleanup (Always runs)
        # Drop the temp database
        try:
            exec_sql(module, client_bin, login_config, None, f"DROP DATABASE IF EXISTS `{temp_db_name}`")
        except Exception:
            pass


def main():
    module = AnsibleModule(
        argument_spec=dict(
            backup_dir=dict(type='path', required=True),
            database=dict(type='str', required=True),

            table=dict(type='list', elements='str'),
            random_tables_count=dict(type='int'),

            validation_query=dict(type='str', required=True),

            client_bin=dict(type='path'),
            dump_bin=dict(type='path'),
            mysqld_bin=dict(type='path'),

            temp_dir=dict(type='path'),
            login_config=dict(type='path', default='/root/.my.cnf'),
            system_user=dict(type='str', default='mysql'),
        ),
        mutually_exclusive=[
            ('table', 'random_tables_count')
        ],
        supports_check_mode=False
    )

    run_verify(module, module.params)


if __name__ == '__main__':
    main()