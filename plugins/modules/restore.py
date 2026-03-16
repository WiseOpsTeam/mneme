#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

DOCUMENTATION = r'''
---
module: wiseops_team.mneme.restore
short_description: Universal DR module. Supports Sidecar (Logical), Direct (Physical), and Copy-Back strategies.
options:
  strategy:
    description: Restore strategy.
    type: str
    choices: [ sidecar, direct, copy_back, move_back ]
    default: sidecar
  backup_dir:
    description: Path to PREPARED backup directory (unarchived).
    type: path
    required: true
  database:
    description: Target database name (Required for sidecar/direct).
    type: str
  table:
    description: Target table name or list of tables.
    If empty, all tables in DB are restored.
    type: list
    elements: str
  schema_file:
    description: Optional path to .sql schema file.
    Used to recreate tables in 'direct' mode.
    type: path
  # --- Binary Paths ---
  client_bin:
    description: Path to mariadb/mysql client binary.
    type: path
  dump_bin:
    description: Path to mariadb-dump/mysqldump binary.
    type: path
  mysqld_bin:
    description: Path to mysqld binary (required for Sidecar).
    type: path
  mneme_bin:
    description: Path to mariadb-backup binary (required for copy_back).
    type: path
  # --- Environment ---
  datadir:
    description: Live MariaDB data directory (destination).
    type: path
    default: /var/lib/mysql
  temp_dir:
    description: Directory for sockets and temp files.
    Must be writable.
    type: path
  login_config:
    description: Path to .my.cnf.
    type: path
    default: /root/.my.cnf
  system_user:
    description: System user owning the database files.
    type: str
    default: mysql
  force:
    description: Allow dangerous operations (overwrite files, copy-back to non-empty dir).
    type: bool
    default: false
author:
  - Ivan Gumeniuk (IMHIO LTD)
'''

import os
import shutil
import subprocess
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wiseops_team.mneme.plugins.module_utils.common import (
    get_binary, check_disk_space, run_cmd, exec_sql, discover_tables,
    MariaDBSandbox, BackupSidecar, fail_with_hint, sanitize_identifier, validate_path_within_base, quote_identifier
)


# --- Strategy: Full Restore (Copy-Back / Move-Back) ---

def run_full_restore(module, params):
    strategy = params['strategy']  # copy_back or move_back
    backup_dir = params['backup_dir']
    datadir = params['datadir']
    sys_user = params['system_user']
    force = params['force']

    mb_bin = get_binary(module, params['mneme_bin'], 'mariabackup')

    # 1. Safety Check: Datadir must be empty or force=True
    if os.path.exists(datadir) and os.listdir(datadir):
        if not force:
            module.fail_json(msg="Datadir is not empty. Use force: true to overwrite.", datadir=datadir)

    # 2. Disk Space Logic
    check_space = True
    if strategy == 'move_back':
        try:
            target_for_stat = datadir if os.path.exists(datadir) else os.path.dirname(datadir.rstrip('/'))
            src_dev = os.stat(backup_dir).st_dev
            dst_dev = os.stat(target_for_stat).st_dev

            if src_dev == dst_dev:
                check_space = False
            else:
                module.fail_json(
                    msg="Critical Strategy Error: 'move_back' requires source and destination to be on the same physical filesystem (partition).",
                    detail="Cross-device move detected. This would degrade into a slow copy/delete operation, violating the 'instant restore' requirement.",
                    source_device_id=src_dev,
                    target_device_id=dst_dev
                )
        except OSError as e:
            module.fail_json(msg="Failed to verify filesystem layout for move_back strategy", error=str(e))

    if check_space:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(backup_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
        check_disk_space(module, datadir, total_size)

    # 3. Execute Command
    action_flag = '--{}'.format(strategy.replace('_', '-'))
    cmd = [mb_bin, action_flag, '--target-dir={}'.format(backup_dir), '--datadir={}'.format(datadir)]
    run_cmd(module, cmd)

    # 4. Fix Permissions
    for dirpath, dirnames, filenames in os.walk(datadir):
        shutil.chown(dirpath, user=sys_user, group=sys_user)
        for f in filenames:
            shutil.chown(os.path.join(dirpath, f), user=sys_user, group=sys_user)

    module.exit_json(changed=True, msg="Full restore ({}) completed".format(strategy))


# --- Strategy: Direct (Batch) ---

def restore_single_table_direct(module, params, client_bin, login_config, db, db_safe, tbl, tbl_safe, src_dir, sandbox=None):
    datadir = params['datadir']
    sys_user = params['system_user']
    backup_dir = params['backup_dir']

    # === SECURITY: Sanitize identifiers ===
    try:
        db_safe = sanitize_identifier(db)
        tbl_safe = sanitize_identifier(tbl)
    except ValueError as e:
        module.fail_json(msg=f"Invalid identifier: {e}")

    # === SECURITY: Validate paths ===
    validate_path_within_base(module, backup_dir, src_dir, "source directory")

    # Files check
    src_files = [f for f in os.listdir(src_dir) if f.startswith(tbl + ".") or f.startswith(tbl + "#P#")]
    ibd_files = [f for f in src_files if f.endswith(".ibd")]

    if not ibd_files:
        module.warn("No .ibd files found for table {}, skipping.".format(tbl))
        return

    # Check if table exists in target DB (using sanitized identifiers)
    check_query = (
        f"SELECT 1 FROM information_schema.tables "
        f"WHERE table_schema = '{db_safe}' AND table_name = '{tbl_safe}'"
    )
    out = exec_sql(module, client_bin, login_config, None, check_query)
    table_exists = "1" in str(out)

    # Schema handling
    if sandbox:
        stmt = sandbox.get_create_statement(db, tbl)
        if stmt:
            exec_sql(module, client_bin, login_config, db, f"DROP TABLE IF EXISTS {quote_identifier(tbl_safe)}")
            exec_sql(module, client_bin, login_config, db, stmt)
        elif not table_exists:
            module.fail_json(msg="Table {} missing and not found in schema file (Sandbox parsing)".format(tbl))
    elif not table_exists:
        module.fail_json(msg="Table {} missing and no schema file provided".format(tbl))

    # Partition detection
    is_partitioned = any("#P#" in f for f in ibd_files)

    if is_partitioned:
        for p_file in ibd_files:
            part_name = p_file.split("#P#")[1].replace(".ibd", "")
            part_name_safe = sanitize_identifier(part_name)
            dummy = "{}_dummytmp_{}".format(tbl_safe, part_name_safe)
            src_ibd = os.path.join(src_dir, p_file)
            src_cfg = src_ibd.replace(".ibd", ".cfg")

            # Validate source file paths
            validate_path_within_base(module, backup_dir, src_ibd, "source .ibd file")

            # Create dummy table to import tablespace
            exec_sql(module, client_bin, login_config, db, f"DROP TABLE IF EXISTS {quote_identifier(dummy)}")
            exec_sql(module, client_bin, login_config, db, f"CREATE TABLE {quote_identifier(dummy)} LIKE {quote_identifier(tbl_safe)}")
            exec_sql(module, client_bin, login_config, db, f"ALTER TABLE {quote_identifier(dummy)} REMOVE PARTITIONING")
            exec_sql(module, client_bin, login_config, db, f"ALTER TABLE {quote_identifier(dummy)} DISCARD TABLESPACE")

            # Copy files
            dst_dir = os.path.join(datadir, db)
            dst_ibd = os.path.join(dst_dir, "{}.ibd".format(dummy))
            dst_cfg = os.path.join(dst_dir, "{}.cfg".format(dummy))

            # Validate destination paths
            validate_path_within_base(module, datadir, dst_ibd, "destination .ibd file")

            shutil.copy2(src_ibd, dst_ibd)
            if os.path.exists(src_cfg): shutil.copy2(src_cfg, dst_cfg)

            shutil.chown(dst_ibd, user=sys_user, group=sys_user)
            if os.path.exists(dst_cfg): shutil.chown(dst_cfg, user=sys_user, group=sys_user)

            # Import and Exchange
            exec_sql(module, client_bin, login_config, db, f"ALTER TABLE {quote_identifier(dummy)} IMPORT TABLESPACE")
            exec_sql(module, client_bin, login_config, db,
                     f"ALTER TABLE {quote_identifier(tbl_safe)} EXCHANGE PARTITION {quote_identifier(part_name_safe)} WITH TABLE {quote_identifier(dummy)}")
            exec_sql(module, client_bin, login_config, db, f"DROP TABLE {quote_identifier(dummy)}")
    else:
        # Standard table (using sanitized identifier)
        exec_sql(module, client_bin, login_config, db, f"ALTER TABLE {quote_identifier(tbl_safe)} DISCARD TABLESPACE")

        dst_dir = os.path.join(datadir, db)
        dst_ibd = os.path.join(dst_dir, "{}.ibd".format(tbl_safe))
        dst_cfg = os.path.join(dst_dir, "{}.cfg".format(tbl_safe))

        src_ibd = os.path.join(src_dir, "{}.ibd".format(tbl))
        src_cfg = os.path.join(src_dir, "{}.cfg".format(tbl))

        # Validate all paths
        validate_path_within_base(module, backup_dir, src_ibd, "source .ibd file")
        validate_path_within_base(module, datadir, dst_ibd, "destination .ibd file")

        if os.path.exists(dst_ibd): os.remove(dst_ibd)
        if os.path.exists(dst_cfg): os.remove(dst_cfg)

        shutil.copy2(src_ibd, dst_ibd)
        if os.path.exists(src_cfg): shutil.copy2(src_cfg, dst_cfg)

        shutil.chown(dst_ibd, user=sys_user, group=sys_user)
        if os.path.exists(dst_cfg): shutil.chown(dst_cfg, user=sys_user, group=sys_user)

        exec_sql(module, client_bin, login_config, db, f"ALTER TABLE {quote_identifier(tbl_safe)} IMPORT TABLESPACE")


def run_direct_restore(module, params):
    if not params['force']:
        module.fail_json(msg="Strategy 'direct' requires force: true")

    db = params['database']
    backup_dir = params['backup_dir']
    datadir = params['datadir']

    if not db:
        module.fail_json(msg="Database parameter required for direct restore")

    # === SECURITY: Sanitize once at entry point ===
    try:
        db_safe = sanitize_identifier(db)
    except ValueError as e:
        module.fail_json(msg=f"Invalid database name: {e}")

    client_bin = get_binary(module, params['client_bin'], 'mariadb')
    login_config = params['login_config']
    src_dir = os.path.join(backup_dir, db)  # filesystem uses original name

    validate_path_within_base(module, backup_dir, src_dir, "database source directory")

    tables = params['table']
    if not tables:
        tables = discover_tables(module, backup_dir, db)

    # Sanitize all table names upfront
    try:
        tables_safe = {t: sanitize_identifier(t) for t in tables}
    except ValueError as e:
        module.fail_json(msg=f"Invalid table name: {e}")

    # Check disk space
    total_size = 0
    for t in tables:
        for f in os.listdir(src_dir):
            if f.startswith(t) and f.endswith('.ibd'):
                total_size += os.path.getsize(os.path.join(src_dir, f))
    check_disk_space(module, datadir, total_size)

    # Initialize Sandbox if schema file is provided
    schema_file = params.get('schema_file')
    sandbox = None

    # We use a try/finally block here because we can't easily use the context manager
    # conditionally across the loop without nesting deeply.
    try:
        if schema_file and os.path.exists(schema_file):
            mysqld_bin = get_binary(module, params.get('mysqld_bin'), 'mysqld')

            # Using context manager manual entry
            sb_instance = MariaDBSandbox(
                module, mysqld_bin, client_bin,
                params['system_user'], params.get('temp_dir')
            )
            sandbox = sb_instance.__enter__()
            sandbox.load_schema(schema_file)

        module.warn(
            "Strategy 'direct' breaks replication (slaves must be rebuilt) and bypasses Foreign Key checks."
        )

        for tbl in tables:
            restore_single_table_direct(
                module, params, client_bin, login_config,
                db, db_safe, tbl, tables_safe[tbl], src_dir, sandbox
            )

    finally:
        if sandbox:
            sandbox.__exit__(None, None, None)

    module.exit_json(changed=True, msg="Restored {} tables via Direct".format(len(tables)))


# --- Strategy: Sidecar (Batch) ---

def run_sidecar_restore(module, params):
    backup_dir = params['backup_dir']
    db = params['database']
    tables = params['table']

    if not db:
        module.fail_json(msg="Database parameter required for sidecar restore")

    # === SECURITY: Sanitize identifiers ===
    try:
        sanitize_identifier(db)
    except ValueError as e:
        module.fail_json(msg=f"Invalid database name: {e}")

    # Validate and sanitize all table names
    if tables:
        for t in tables:
            try:
                sanitize_identifier(t)
            except ValueError as e:
                module.fail_json(msg=f"Invalid table name '{t}': {e}")

    if not tables:
        tables = discover_tables(module, backup_dir, db)

    mysqld_bin = get_binary(module, params['mysqld_bin'], 'mysqld')
    dump_bin = get_binary(module, params['dump_bin'], 'mariadb-dump')
    client_bin = get_binary(module, params['client_bin'], 'mariadb')
    login_config = params['login_config']

    # Use Context Manager for Sidecar mysqld
    with BackupSidecar(
            module, mysqld_bin, backup_dir,
            params['system_user'], params.get('temp_dir')
    ) as sidecar:

        # Dump ALL requested tables in one go
        dump_cmd = [
                       dump_bin,
                       "--socket={}".format(sidecar.socket_path),
                       "--add-drop-table",
                       "--quick",
                       "--single-transaction",
                       db
                   ] + tables

        restore_cmd = [
            client_bin,
            "--defaults-file={}".format(login_config),
            "--init-command=SET SESSION sql_log_bin=0; SET FOREIGN_KEY_CHECKS=0;",
            db
        ]

        # Pipe: dump -> restore
        p1 = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p2 = subprocess.Popen(restore_cmd, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p1.stdout.close()  # Allow p1 to receive SIGPIPE if p2 exits

        _, err_restore = p2.communicate()
        _, err_dump = p1.communicate()

        if p1.returncode != 0:
            fail_with_hint(module, "Sidecar Dump failed", err_dump, cmd=" ".join(dump_cmd))
        if p2.returncode != 0:
            fail_with_hint(module, "Sidecar Restore failed", err_restore, cmd=" ".join(restore_cmd))

    module.exit_json(changed=True, msg="Restored {} tables via Sidecar".format(len(tables)))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            strategy=dict(type='str', choices=['sidecar', 'direct', 'copy_back', 'move_back'], default='sidecar'),
            backup_dir=dict(type='path', required=True),

            # Optional for copy_back
            database=dict(type='str'),
            table=dict(type='list', elements='str'),

            # Binaries
            client_bin=dict(type='path'),
            dump_bin=dict(type='path'),
            mysqld_bin=dict(type='path'),
            mneme_bin=dict(type='path'),

            schema_file=dict(type='path'),
            force=dict(type='bool', default=False),

            datadir=dict(type='path', default='/var/lib/mysql'),
            temp_dir=dict(type='path'),
            login_config=dict(type='path', default='/root/.my.cnf'),
            system_user=dict(type='str', default='mysql'),
        ),
        supports_check_mode=False
    )

    if module.params['strategy'] == 'sidecar':
        run_sidecar_restore(module, module.params)
    elif module.params['strategy'] in ['copy_back', 'move_back']:
        run_full_restore(module, module.params)
    else:
        run_direct_restore(module, module.params)


if __name__ == '__main__':
    main()