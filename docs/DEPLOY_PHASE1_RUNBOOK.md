# Phase 1 Deploy Runbook — Master Rules + Hardening

Commits: `12479be` (Phase 1 hardening + Master Rules UI) → `<prep commit>` (smoke + migration parens)

## Pre-flight (do once)

### 1. Restore SSH access
SSH from current laptop (IP `182.8.97.55`) is currently timing out.
Likely fail2ban ban or VPS firewall change. From VPS web console:

```bash
# Unban current laptop IP
sudo fail2ban-client status sshd
sudo fail2ban-client set sshd unbanip 182.8.97.55

# Confirm UFW allows 22
sudo ufw status | grep 22
```

Then locally verify:
```bash
ssh -o ConnectTimeout=5 root@104.194.154.108 'uptime'
```

### 2. Confirm clean local state
```bash
git status --short  # should only show pyc / db / xlsx (cache/data, never deploy)
git log --oneline -3
```

---

## Deploy steps (execute in order)

### Step 1 — Sync code (backend + migrations)
`make deploy` only ships `kil/backend/`. For migration 031 we need **`deploy-full`**:

```bash
make deploy-full
```

This: lint → rsync `kil/` (backend + db/ + rules/ + worker/) → `systemctl restart kil-api`.

### Step 2 — Apply migration 031
```bash
ssh root@104.194.154.108 'cd /root/kil-server && \
  PGPASSWORD=KilEnt2026! psql -h 127.0.0.1 -U kil_ent -d kil_enterprise \
  -f kil/db/migrations/031_data_integrity_cleanup.sql'
```

Expected output:
- `DELETE 156` (orphan conflicts)
- `DELETE 0` (orphan audit — was already clean post-test) or a small N
- `DELETE 8` (duplicate events)
- `ALTER TABLE` ×4 (drop+add FK)
- `CREATE INDEX` (or no-op if `IF NOT EXISTS` hit)

Migration is **idempotent** — safe to re-run.

### Step 3 — Smoke test
```bash
make smoke
```

New checks added in this release (must pass):
- `recurring-rules-list` (GET /api/v1/enterprise/recurring-rules)
- `recurring-rules-stats`
- `recurring-rules-log`
- `schedule-draft-current` (GET /calendar/draft?month=2026-06)
- `schedule-draft-patterns`
- `master-rules-page` (HTML 200)
- `schedule-draft-calendar-page` (HTML 200)

If any fail, rollback (Step 5) and investigate.

### Step 4 — Manual UI verification
Browser → https://safencare.work/enterprise/master-rules

Login as `admin@sanocare.work` / `SanoCare2026!`. Verify:
1. Page loads, sidebar entry visible under Scheduling
2. Rule list populates (may be empty if no rules seeded yet — OK)
3. Coverage stats panel shows technician + frequency breakdown
4. "New Rule" button opens modal with all fields editable
5. Filter by frequency / tech / search works
6. "Derive from Pattern" panel: pick a customer → Suggest → see suggestion → Accept as Soft populates modal

Also browser → https://safencare.work/enterprise/schedule-draft-calendar — verify Phase 1 calendar still works post-migration (events render, conflicts panel populated).

### Step 5 — Rollback (if needed)
```bash
# Revert to last-known-good commit
git revert --no-commit 12479be <prep-commit-sha>
git commit -m "revert: rollback Phase 1"
make deploy-full

# Migration 031 is destructive on data — only orphan + duplicate rows
# already removed. FK CASCADE and unique index are additive (no data loss).
# Safe to leave them in place even after revert.
```

---

## Risk register

| Risk | Mitigation | Severity |
|------|-----------|----------|
| Migration deletes valid data | DELETEs target orphans only (WHERE NOT EXISTS) + duplicates (ROW_NUMBER>1) | Low |
| UNIQUE INDEX rejects future legit dups | Indexed on (tech, client, datetime, batch) — true dups are bugs | Low |
| Permission guard locks out supervisor | Read endpoints untouched; only write paths gated | Low |
| New audit log volume | 4 new actions, ~1-5 rows per draft generation | Negligible |
| Master Rules UI calls missing endpoint | All 8 endpoints verified to exist before commit | None |

## Known gaps (not blocking)
1. `customersWithPattern` filter — UI shows all customers; should be `/recurring-rules/candidates`. Deferred.
2. 4 legacy paused-customer events from batch 10 — historical data leak, low priority.
3. Audit log coverage 9/11 — `holiday_skipped`, `rule_violation_overridden` still missing. Add after Master Rules sees production use.

## Post-deploy follow-up
- Watch `/root/kil-server/cron.log` after 06:00 WIB daily cron fires
- Check `/api/v1/enterprise/recurring-rules/log` after first rule created via UI
- Verify `journalctl -u kil-api -f` shows no 500s during first 30 min
