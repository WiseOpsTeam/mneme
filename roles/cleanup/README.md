# wiseops_team.mneme.cleanup

Removes the working directory created by the `wiseops_team.mneme.prepare` role.

Call this in `post_tasks` or an `always` block at the end of your recovery playbook.

## Variables

| Variable | Default | Description |
|---|---|---|
| `mneme_prepare_target_date` | `latest` | Must match the value used in the prepare step. |
| `mneme_prepare_work_dir` | `{{ mneme_temp_dir }}/restore_{{ mneme_prepare_target_date }}` | Path to the working directory to remove. Overridden automatically if prepare ran in the same play. |

## Example
```yaml
post_tasks:
  - name: Cleanup restore artifacts
    ansible.builtin.include_role:
      name: wiseops_team.mneme.cleanup
    vars:
      mneme_prepare_target_date: "2026-03-15"
```

See the [Recovery Runbook](../../docs/RECOVERY_RUNBOOK.md) for full details.
