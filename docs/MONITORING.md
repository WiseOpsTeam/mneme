# Monitoring & Observability

This role provides "Enterprise-Grade" observability for your backups. Instead of relying on simple email notifications, we recommend using the **Prometheus Textfile Collector** pattern. This allows you to treat backups as a metric, enabling historical analysis and reliable alerting.

## 1. Prometheus (Recommended)

### Architecture
The backup script generates a static metric file (`.prom`) upon completion (success or failure). You must point your **Node Exporter** to this directory.

1.  **Backup Wrapper** -> Writes mneme_<type>.prom to disk (e.g., mneme_daily.prom).
2.  **Node Exporter** -> Reads `mariabackup.prom` via `--collector.textfile.directory`.
3.  **Prometheus** -> Scrapes Node Exporter.

### Configuration

Enable the feature in your playbook variables:

```yaml
mneme_prometheus_enabled: true
# Directory watched by node_exporter
mneme_prometheus_dir: "/var/lib/node_exporter/textfile_collector"
```

> **Important:** This role **does not** install or configure `node_exporter`. You must ensure `node_exporter` is running with the flag `--collector.textfile.directory=/var/lib/node_exporter/textfile_collector` (or matching your path).

### Exported Metrics

All metrics include the following labels:
*   `type`: The backup contour (`daily`, `weekly`, `monthly`).
*   `db_host`: The inventory hostname of the server.

| Metric Name                                  | Type  | Description                                                                         |
|:---------------------------------------------|:------|:------------------------------------------------------------------------------------|
| `mneme_last_run_timestamp_seconds`     | Gauge | Unix timestamp of the last *attempted* backup run (updates on Success AND Failure). |
| `mneme_last_success_timestamp_seconds` | Gauge | Unix timestamp of the last **successful** backup run. **Use this for alerts.**      |
| `mneme_last_status`                    | Gauge | `1` = Success, `0` = Failure.                                                       |
| `mneme_duration_seconds`               | Gauge | Time taken to complete the backup (in seconds).                                     |
| `mneme_size_bytes`                     | Gauge | Size of the compressed archive (in bytes). `0` if failed.                           |
---

## 2. Alerting Rules (PromQL)

Here are the standard alerting rules you should add to your Prometheus/Alertmanager configuration.

### A. Backup Failed (Immediate)
Trigger an alert if the last run reported a failure status.

```promql
mneme_last_status == 0
```

### B. Backup Missing (Dead Man's Switch) - CRITICAL
Trigger an alert if a **successful** backup hasn't occurred in the expected time window. 
Using `last_success_timestamp` ensures that failing scripts (which update `last_run` but not `last_success`) trigger this alert.

```promql
(time() - mneme_last_success_timestamp_seconds{type="daily"}) > (26 * 3600)
```
Why 26 hours? To allow for slight schedule drifts and backup duration without false positives for a 24h cycle.

### C. Anomaly Detection (Size Drop)
Trigger a warning if the backup size is significantly smaller (e.g., < 80%) than yesterday. This often indicates accidental data deletion (DROP TABLE/TRUNCATE) or configuration errors.

```promql
mneme_size_bytes < (mneme_size_bytes offset 1d * 0.8)
```

---

## 3. Legacy Monitoring (UDP/StatsD)

For older environments, the role supports sending a simple status packet via UDP (StatsD style).

```yaml
mneme_monitoring_notify_enable: true
mneme_monitoring_notify_ip: "127.0.0.1"
mneme_monitoring_notify_port: 8125
mneme_monitoring_notify_message_success: "mariabackup.status:1|g|#tag:val"
mneme_monitoring_notify_message_fail: "mariabackup.status:0|g|#tag:val"
```

**Note:** The legacy method is "fire-and-forget" and does not provide persistence or metadata (size/duration). We strongly recommend migrating to Prometheus.