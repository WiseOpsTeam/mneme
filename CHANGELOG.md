## [2.0.0] - 2026-02-22

This is a major architectural release. `mariabackup` has evolved from a simple cron-job configuration tool into a comprehensive **Disaster Recovery as Code** solution. 

### Major Features (New)
* **Declarative Recovery (`mneme_restore`):** Introduced a native custom Ansible module to handle database restoration. No more manual CLI scripts. Supports four recovery strategies: `sidecar`, `direct`, `copy_back`, and `move_back`.
* **Automated Verification Drills (`mneme_verify`):** Introduced a new module for CI/CD pipelines. It spins up an ephemeral, sandboxed MariaDB instance to safely restore and test data integrity without impacting production.
* **Smart Helpers:** Added `restore_prepare` and `restore_cleanup` tasks for auto-discovery, idempotent unarchiving, and automatic handling of `latest` backups with SHA256 integrity checks.
* **Observability:** Built-in support for Prometheus Node Exporter (Textfile Collector). Backups now generate `.prom` files exposing metrics like `last_status`, `duration_seconds`, and `size_bytes`.

### Infrastructure & Testing
* **Full CI/CD Pipeline:** Implemented comprehensive automated testing using Molecule and Docker (Sibling Containers architecture).
* **E2E Test Suite:** Tests now cover complex scenarios including partitioned tables restoration, idempotency, path traversal prevention, and MySQL schema parsing edge cases.
