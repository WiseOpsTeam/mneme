#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import os
import shutil
import subprocess
import time
import tempfile
import re


KNOWN_ERROR_HINTS = {
    # --- Group 1: Connectivity & Authentication ---
    "Can't connect to local MySQL server through socket": {
        "hint": "Socket Error. Client and Server are looking for the Unix socket in different locations. Check [client] and [mysqld] sections in my.cnf or use an explicit --socket parameter.",
        "category": "Connectivity",
        "severity": "Critical"
    },
    "ERROR 2002 (HY000)": {
        "hint": "General Connection Error. The server is not running or is unreachable via the specified socket/port.",
        "category": "Connectivity",
        "severity": "Critical"
    },
    "Access denied for user": {
        "hint": "Authentication Failed. Check username/password. Ensure the user has permissions for both 'localhost' (socket) and '127.0.0.1' (TCP) if needed. Also check if .my.cnf is readable.",
        "category": "Authentication",
        "severity": "Critical"
    },
    "Access denied; you need (at least one of) the RELOAD privilege(s)": {
        "hint": "Insufficient Privileges. The backup user requires global RELOAD, LOCK TABLES, and PROCESS privileges.",
        "category": "Permissions",
        "severity": "High"
    },
    "failed to execute query 'LOCK TABLES FOR BACKUP'": {
        "hint": "Locking Failed. Insufficient permissions to lock tables or the operation timed out waiting for a lock.",
        "category": "Permissions",
        "severity": "High"
    },
    "INSERT command denied to user": {
        "hint": "History Write Failed. Backup succeeded, but writing to 'mysql.mariadb_backup_history' failed. Grant INSERT permissions to the backup user.",
        "category": "Permissions",
        "severity": "Low"
    },
    "Missing required privilege REPLICATION CLIENT": {
        "hint": "Replication Rights Missing. Cannot retrieve binary log coordinates. Grant REPLICATION CLIENT privilege.",
        "category": "Permissions",
        "severity": "Medium"
    },

    # --- Group 2: System Resources ---
    "Permission denied": {
        "hint": "File Permission Error. The process cannot read/write files. Check directory permissions (chown/chmod) or SELinux context.",
        "category": "Configuration",
        "severity": "Critical"
    },
    "Errcode: 13": {
        "hint": "File Permission Error (Errcode 13). The operating system denied access to the file/directory.",
        "category": "Configuration",
        "severity": "Critical"
    },
    "Too many open files": {
        "hint": "File Descriptor Limit Exceeded. The utility cannot open all .ibd files simultaneously. Increase 'ulimit -n' for the user or adjust limits.conf.",
        "category": "Resource",
        "severity": "Critical"
    },
    "No space left on device": {
        "hint": "Disk Full. Target directory or /tmp (used for sorting/temporary files) is out of space.",
        "category": "Resource",
        "severity": "Critical"
    },
    "run out of disk space": {
        "hint": "Disk Full. The utility detected insufficient space during operation.",
        "category": "Resource",
        "severity": "Critical"
    },
    "Broken pipe": {
        "hint": "Pipe Broken. The receiving process (pigz, nc, socat) terminated unexpectedly. Possible causes: remote disk full, network drop, or receiver crash.",
        "category": "Resource",
        "severity": "Critical"
    },
    "Cannot allocate memory": {
        "hint": "Out of Memory (OOM). Failed to allocate buffer. Reduce the --use-memory parameter or ensure swap is available.",
        "category": "Resource",
        "severity": "Critical"
    },

    # --- Group 3: Locking & Concurrency ---
    "Lock wait timeout exceeded": {
        "hint": "FTWRL Timeout. Failed to acquire global lock due to long-running queries (ALTER, UPDATE). Increase --ftwrl-wait-timeout or kill blocking queries.",
        "category": "Locking",
        "severity": "High"
    },
    "Waiting for table metadata lock": {
        "hint": "Metadata Lock (MDL). DDL operations are blocking the backup. Check process list for ALTER/DROP/TRUNCATE statements.",
        "category": "Locking",
        "severity": "High"
    },
    "failed to execute query FLUSH NO_WRITE_TO_BINLOG TABLES": {
        "hint": "FLUSH TABLES Failed. Usually caused by a timeout or missing RELOAD privilege.",
        "category": "Locking",
        "severity": "High"
    },

    # --- Group 4: Data Integrity ---
    "Database page corruption detected": {
        "hint": "Page Corruption. Checksum mismatch detected. Likely hardware/disk failure. Run hardware diagnostics immediately.",
        "category": "Data Integrity",
        "severity": "Critical"
    },
    "Page read from tablespace is corrupted": {
        "hint": "Read Corruption. CRC32 failure while reading an .ibd file.",
        "category": "Data Integrity",
        "severity": "Critical"
    },
    "Log block checksum mismatch": {
        "hint": "Redo Log Error. If occurring during backup (Warning) -> benign race condition. If during prepare (Error) -> log file corruption.",
        "category": "Data Integrity",
        "severity": "Medium"
    },
    "failed to copy enough redo log": {
        "hint": "Redo Log Overwrite. Server write speed exceeds backup copy speed (redo log wrapped around). Increase innodb_log_file_size or improve backup I/O throughput.",
        "category": "Consistency",
        "severity": "Critical"
    },

    # --- Group 5: Restore & Import ---
    "Schema mismatch": {
        "hint": "Schema Drift. The .cfg file does not match the data dictionary. Check for server version mismatch or different ROW_FORMAT settings.",
        "category": "Restore",
        "severity": "High"
    },
    "Tablespace is missing for table": {
        "hint": "Missing Tablespace. The .frm file exists, but the .ibd file is missing. The table is corrupted or was manually deleted.",
        "category": "Restore",
        "severity": "High"
    },
    "innodb_init(): Error occured": {
        "hint": "InnoDB Init Failed. Error during prepare/startup. Check compatibility (MySQL vs MariaDB versions) and log integrity.",
        "category": "Restore",
        "severity": "Critical"
    },
    "Operating system error number 2": {
        "hint": "File Not Found. Often indicates missing ib_logfile0 or configuration files during the prepare step.",
        "category": "Restore",
        "severity": "High"
    },
    "The log sequence number... in the system tablespace does not match": {
        "hint": "LSN Mismatch. ibdata1 and redo log are out of sync. Ensure the --prepare step completed successfully.",
        "category": "Restore",
        "severity": "High"
    },

    # --- Group 6: Tools & Configuration ---
    "unknown option": {
        "hint": "Unknown Configuration Option. The tool encountered a server option it doesn't recognize (e.g., in [mysqld] vs global). Move server-specific flags to the correct section.",
        "category": "Configuration",
        "severity": "Low"
    },
    "qpress: not found": {
        "hint": "Missing qpress. The backup is compressed (.qp), but the qpress utility is not installed.",
        "category": "Configuration",
        "severity": "High"
    },
    "command not found": {
        "hint": "Binary Missing. A required tool (mariadb-backup, pigz, socat, etc.) is not installed or not in PATH.",
        "category": "Configuration",
        "severity": "Critical"
    },
    "aria_log_control": {
        "hint": "Aria Engine Error. Aria control file is missing or corrupted. Critical for system tables (mysql.*).",
        "category": "Tool Specific",
        "severity": "Medium"
    },
    "Unsupported server version": {
        "hint": "Version Incompatibility. Attempting to use xtrabackup on MariaDB (or vice versa), or major version mismatch.",
        "category": "Compatibility",
        "severity": "Critical"
    },
    "xb_stream_write_data() failed": {
        "hint": "Stream Write Failed. Error writing to the xbstream output. Check disk space or pipe connectivity.",
        "category": "IO",
        "severity": "Critical"
    },
    "encryption support missing": {
        "hint": "Encryption Unsupported. The tool was built without OpenSSL/Keyring support, but the backup is encrypted.",
        "category": "Configuration",
        "severity": "Critical"
    },
    "innodb_page_size mismatch": {
        "hint": "Page Size Mismatch. Backup source and restore target have different innodb_page_size (e.g., 4k vs 16k).",
        "category": "Compatibility",
        "severity": "Critical"
    },
    "mariabackup: error: failed to open the target stream": {
        "hint": "Target Stream Error. Failed to open output stream. Check directory permissions or pipe status.",
        "category": "IO",
        "severity": "High"
    },
    "Got signal 11": {
        "hint": "Segmentation Fault. The utility crashed. Check memory stability and binary compatibility.",
        "category": "Crash",
        "severity": "Critical"
    },
    "This target seems to be not prepared yet": {
        "hint": "Not Prepared. Attempting to restore or use a raw backup without running --prepare first.",
        "category": "Usage",
        "severity": "Medium"
    },
    "xtrabackup_checkpoints missing": {
        "hint": "Corrupted Backup. The 'xtrabackup_checkpoints' metadata file is missing. The backup is empty or failed early.",
        "category": "Data Integrity",
        "severity": "Critical"
    }
}


# --- Security Helpers ---

def sanitize_identifier(name):
    if not name:
        return name

    if not re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', name):
        if re.search(r'[;\'"\\`\x00]', name):
            raise ValueError(f"Forbidden characters in identifier: {name}")

    if name.startswith('-'):
        raise ValueError(f"Identifier cannot start with dash: {name}")

    return name.replace('`', '``')


def validate_path_within_base(module, base_path, target_path, param_name="path"):
    """
    Validate that target_path is within base_path (prevent path traversal).
    Returns the resolved absolute path if valid.
    Fails the module if path traversal is detected.
    """
    try:
        # Resolve to absolute paths, following symlinks
        real_base = os.path.realpath(base_path)
        real_target = os.path.realpath(target_path)

        # Ensure target is within base (with trailing slash to prevent prefix attacks)
        # e.g., /backup/data vs /backup/data_evil
        if not (real_target.startswith(real_base + os.sep) or real_target == real_base):
            module.fail_json(
                msg=f"Path traversal detected in '{param_name}'",
                base_path=real_base,
                target_path=real_target,
                hint="The specified path attempts to escape the backup directory"
            )

        return real_target
    except OSError as e:
        module.fail_json(msg=f"Cannot resolve path '{target_path}': {e}")

# --- Generic Helpers ---

def get_binary(module, explicit_path, binary_name):
    """Finds a binary path, prioritizing explicit config over PATH."""
    if explicit_path:
        if os.path.exists(explicit_path) and os.access(explicit_path, os.X_OK):
            return explicit_path
        module.fail_json(msg="Binary defined in variables not found or not executable", path=explicit_path)
    sys_path = shutil.which(binary_name)
    if sys_path:
        return sys_path
    module.fail_json(msg="Binary not found in PATH and no explicit path provided", binary=binary_name)


def check_disk_space(module, path, required_bytes):
    """Checks if there is enough space on the filesystem containing 'path'."""
    # If path doesn't exist, check parent
    target = path
    while not os.path.exists(target):
        target = os.path.dirname(target)
        if target == '/' or not target:
            break

    try:
        stat = os.statvfs(target)
        available = stat.f_bavail * stat.f_frsize
        # Add 10% safety buffer
        needed_safe = int(required_bytes * 1.1)
        if available < needed_safe:
            module.fail_json(
                msg="Insufficient disk space",
                path=target,
                available_mb=available // (1024 * 1024),
                required_mb=needed_safe // (1024 * 1024)
            )
    except OSError as e:
        module.warn("Could not check disk space: " + str(e))


def fail_with_hint(module, msg, stderr, stdout=None, cmd=None):
    """
    Guaranteed Fail Wrapper.
    Even if the error analysis logic fails (due to parsing issues, encoding, or type mismatches),
    this function MUST ensure the original error is returned via fail_json.
    """

    final_msg = msg
    safe_stderr = stderr

    try:
        if stderr is not None:
            if isinstance(stderr, bytes):
                safe_stderr = stderr.decode('utf-8', errors='replace')
            else:
                safe_stderr = str(stderr)
        else:
            safe_stderr = ""
    except Exception:
        safe_stderr = "Critical: Could not decode stderr"

    try:
        hint_details = None

        for error_marker, info in KNOWN_ERROR_HINTS.items():
            if error_marker in safe_stderr:
                hint_details = info
                break

        if hint_details:
            final_msg = (
                f"{msg}. "
                f"Analyzed Failure: [{hint_details.get('category', 'Unknown')}] "
                f"{hint_details.get('hint', '')}"
            )

    except Exception:
        pass

    module.fail_json(
        msg=final_msg,
        stderr=safe_stderr,
        stdout=stdout,
        cmd=cmd
    )

def run_cmd(module, cmd_list, env=None, check=True):
    """Wrapper for subprocess to run shell commands safely."""
    try:
        proc = subprocess.Popen(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = proc.communicate()

        if check and proc.returncode != 0:
            fail_with_hint(
                module,
                msg="Command failed",
                stderr=err,
                stdout=out,
                cmd=" ".join(cmd_list)
            )

        return out, err, proc.returncode
    except OSError as e:
        fail_with_hint(
            module,
            msg="Execution failed",
            stderr=str(e),
            cmd=" ".join(cmd_list)
        )


def exec_sql(module, client_bin, login_config, db, query, session_opts=""):
    """
    Executes a SQL query using the mariadb client.
    Enforces replication safety (sql_log_bin=0).
    """
    # Always disable binlog to protect replication
    full_query = "SET SESSION sql_log_bin=0; SET FOREIGN_KEY_CHECKS=0; " + session_opts + query

    # -N (skip headers), -B (batch/tab-separated)
    cmd = [client_bin, '--defaults-file={}'.format(login_config), '-N', '-B', '-e', full_query]

    # Handle connection to 'no database'
    if db:
        cmd.append(db)

    out, _, _ = run_cmd(module, cmd)
    return out


def discover_tables(module, backup_dir, db):
    """Scans backup dir for .ibd files, filtering out partitions."""
    src_dir = os.path.join(backup_dir, db)
    if not os.path.exists(src_dir):
        module.fail_json(msg="Database directory not found in backup", path=src_dir)

    tables = set()
    for f in os.listdir(src_dir):
        if f.endswith('.ibd'):
            # Filter partitions: table#P#part.ibd -> table
            name = f.replace('.ibd', '')
            if '#P#' in name:
                name = name.split('#P#')[0]
            tables.add(name)
    return list(tables)


# --- Context Managers ---

class MariaDBBaseInstance:
    """Base class for managing ephemeral mysqld instances."""

    def __init__(self, module, mysqld_bin, sys_user, temp_base_dir=None):
        self.module = module
        self.mysqld_bin = mysqld_bin
        self.sys_user = sys_user
        self.temp_base = temp_base_dir
        self.temp_dir = None
        self.proc = None
        self.socket_path = None
        self.pid_file = None

    def _setup_dirs(self, prefix):
        """Creates secure temp directories."""
        self.temp_dir = tempfile.mkdtemp(prefix=prefix, dir=self.temp_base)
        os.chmod(self.temp_dir, 0o700)
        shutil.chown(self.temp_dir, user=self.sys_user, group=self.sys_user)

        self.socket_path = os.path.join(self.temp_dir, "mysql.sock")
        self.pid_file = os.path.join(self.temp_dir, "mysql.pid")

    def _wait_for_socket(self, timeout=120):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.proc.poll() is not None:
                _, err = self.proc.communicate()
                fail_with_hint(self.module, "Ephemeral mysqld failed to start", stderr=err)
            if os.path.exists(self.socket_path):
                return True
            time.sleep(0.5)
        return False

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()

        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)


class MariaDBSandbox(MariaDBBaseInstance):
    """
    Creates a FRESH, EMPTY, TEMPORARY MariaDB instance.
    Used for parsing schemas safely without regex.
    """

    def __init__(self, module, mysqld_bin, client_bin, sys_user, temp_base_dir=None):
        super(MariaDBSandbox, self).__init__(module, mysqld_bin, sys_user, temp_base_dir)
        self.client_bin = client_bin

    def __enter__(self):
        self._setup_dirs(prefix="mariadb_sandbox_")

        datadir = os.path.join(self.temp_dir, "data")
        os.mkdir(datadir)
        shutil.chown(datadir, user=self.sys_user, group=self.sys_user)

        # Initialize minimal DB
        install_bin = shutil.which('mariadb-install-db') or shutil.which('mysql_install_db')
        if not install_bin:
            self.module.fail_json(msg="mariadb-install-db not found. Required for sandbox.")

        init_cmd = [
            install_bin,
            f"--datadir={datadir}",
            "--auth-root-authentication-method=socket",
            "--skip-test-db",
            f"--user={self.sys_user}"
        ]
        run_cmd(self.module, init_cmd)

        # Start mysqld
        start_cmd = [
            self.mysqld_bin,
            "--no-defaults",
            f"--datadir={datadir}",
            f"--socket={self.socket_path}",
            f"--pid-file={self.pid_file}",
            f"--tmpdir={self.temp_dir}",
            "--skip-networking",
            "--skip-grant-tables",
            "--skip-log-bin",
            "--innodb-fast-shutdown=2",
            f"--user={self.sys_user}"
        ]

        self.proc = subprocess.Popen(start_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if not self._wait_for_socket():
            self.module.fail_json(msg="Sandbox mysqld did not start within timeout")

        return self

    def load_schema(self, schema_path):
        """Pipes the schema file into the sandbox."""
        if not os.path.exists(schema_path):
            return False

        with open(schema_path, 'rb') as f:
            load_cmd = [self.client_bin, f"--socket={self.socket_path}", "-u", "root"]
            p = subprocess.Popen(load_cmd, stdin=f, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if p.returncode != 0:
                fail_with_hint(self.module, "Failed to load schema into sandbox", stderr=err)
        return True

    def get_create_statement(self, db_name, table_name):
        """Returns the canonical CREATE TABLE statement."""
        query = f"SHOW CREATE TABLE `{db_name}`.`{table_name}`"
        cmd = [
            self.client_bin, f"--socket={self.socket_path}", "-u", "root",
            "-N", "-B", "-r", "-e", query
        ]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = proc.communicate()

            if proc.returncode != 0:
                if b"doesn't exist" in err:
                    return None
                fail_with_hint(self.module, "Sandbox query failed", stderr=err, cmd=" ".join(cmd))

            output = out.decode('utf-8').strip()
            parts = output.split('\t', 1)
            if len(parts) == 2:
                return parts[1]
            return None
        except OSError as e:
            self.module.fail_json(msg="Sandbox execution error", error=str(e))


class BackupSidecar(MariaDBBaseInstance):
    """
    Spins up a mysqld instance ON TOP OF existing backup files.
    Used for Logical Restore (Sidecar strategy) and Verification.
    """

    def __init__(self, module, mysqld_bin, backup_dir, sys_user, temp_base_dir=None):
        super(BackupSidecar, self).__init__(module, mysqld_bin, sys_user, temp_base_dir)
        self.backup_dir = backup_dir

    def __enter__(self):
        self._setup_dirs(prefix="mariadb_sidecar_")

        # Start mysqld directly on backup dir
        # Note: --innodb-fast-shutdown=0 is safer for backups
        start_cmd = [
            self.mysqld_bin,
            "--no-defaults",
            f"--datadir={self.backup_dir}",
            f"--tmpdir={self.temp_dir}",
            f"--socket={self.socket_path}",
            f"--pid-file={self.pid_file}",
            "--skip-networking",
            "--skip-grant-tables",
            "--skip-log-bin",
            "--innodb-fast-shutdown=0",
            "--innodb-read-only=0",  # Need to allow recovery
            f"--user={self.sys_user}"
        ]

        self.proc = subprocess.Popen(start_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if not self._wait_for_socket():
            self.module.fail_json(msg="Sidecar mysqld (on backup files) failed to start. Check logs or permissions.")

        return self