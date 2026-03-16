# wiseops_team.mneme.drill

Disaster recovery drill role. Orchestrates ephemeral backup verification by preparing artifacts, restoring tables to a temporary database, executing validation queries, and cleaning up.

Internally uses the `wiseops_team.mneme.verify` module and the `wiseops_team.mneme.prepare` role.

See the [Verification Guide](../../docs/VERIFICATION.md) for full details.
