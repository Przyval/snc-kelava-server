# App Change Requests - KPI Enforcement
> **Generated:** 2026-01-13  
> **For:** Development Team

---

## CR-001: Auto-Checkout at 18:00

**Priority:** P1  
**Type:** Backend Cron Job

### Requirements
1. Run daily at 18:00 WIB (Monday-Saturday)
2. Find all visits where:
   - `checkout_time IS NULL`
   - `checkin_time < TODAY 08:00`
3. For each: set `checkout_time = NOW()`, `checkout_type = 'AUTO'`
4. Log to audit table: `road_plan_id`, `original_checkin`, `auto_checkout_time`

### Database Changes
```sql
ALTER TABLE t_visit ADD COLUMN checkout_type VARCHAR(20) DEFAULT 'MANUAL';
-- Values: MANUAL, AUTO, ABANDONED
```

### Acceptance Criteria
- [ ] Cron runs at 18:00 WIB M-Sat
- [ ] Open visits older than today are closed
- [ ] Audit log populated
- [ ] Test with 3 known open visits

---

## CR-002: Photo Required Before Checkout

**Priority:** P1  
**Type:** Frontend + Backend Validation

### Requirements
1. On checkout attempt, check if `foto_count >= 1`
2. If `foto_count = 0` AND `type IN ('t_mobile', 't_station', 'spv_tc', 'spv_qc')`:
   - Block checkout
   - Show error: "Minimal 1 foto harus diupload sebelum checkout"
3. If `type = 'checklist'`: Allow checkout without photo

### Frontend Changes
```typescript
const canCheckout = () => {
  const photoRequired = ['t_mobile', 't_station', 'spv_tc', 'spv_qc'];
  if (photoRequired.includes(visit.type) && visit.fotoCount === 0) {
    return { allowed: false, reason: 'Photo required' };
  }
  return { allowed: true };
};
```

### Acceptance Criteria
- [ ] MOBILE/STATION blocked without photo
- [ ] SUPPORT/CHECKLIST allowed without photo
- [ ] Error message displays correctly
- [ ] Backend also validates (not just frontend)

---

## CR-003: Open Visit Indicator

**Priority:** P2  
**Type:** Frontend UI

### Requirements
1. Check if user has any `visit.checkout IS NULL`
2. If yes: Show badge on home screen "1 kunjungan masih terbuka"
3. Clicking badge → navigates to open visit

### Optional Enhancement
- Block "Start New Visit" if open visit exists
- Require "Batalkan Kunjungan" or "Checkout" first

### Acceptance Criteria
- [ ] Badge visible when open visit exists
- [ ] Badge click navigates to visit
- [ ] Badge disappears after checkout

---

## CR-004: Server Timestamp for Check-in/out

**Priority:** P2  
**Type:** Backend API Change

### Requirements
1. On check-in/checkout API call:
   - Use `server_time = NOW()` as official timestamp
   - Store `client_timestamp` from request body
   - Calculate `sync_delay_seconds = server_time - client_timestamp`
2. Flag if `sync_delay_seconds > 3600` (1 hour)

### Database Changes
```sql
ALTER TABLE t_visit ADD COLUMN client_checkin TIMESTAMP;
ALTER TABLE t_visit ADD COLUMN sync_delay_seconds INT;
ALTER TABLE t_visit ADD COLUMN is_late_sync BOOLEAN DEFAULT FALSE;
```

### API Changes
```json
// Request
{
  "road_plan_id": 123,
  "client_timestamp": "2026-01-13T09:30:00+07:00"
}

// Response includes
{
  "server_timestamp": "2026-01-13T09:30:05+07:00",
  "sync_delay_seconds": 5
}
```

### Acceptance Criteria
- [ ] Server time used as official
- [ ] Client time stored for audit
- [ ] Delay calculated correctly
- [ ] Late sync flagged (> 1 hour)

---

## CR-005: Checkout Reminder Notification

**Priority:** P3  
**Type:** Backend Cron + Push Notification

### Requirements
1. Run every hour (10:00, 11:00, ... 17:00)
2. Find visits where:
   - `checkout IS NULL`
   - `checkin > 2 hours ago`
3. Send push notification: "Anda masih dalam kunjungan. Jangan lupa checkout!"

### Acceptance Criteria
- [ ] Notification sent after 2 hours
- [ ] Only one notification per visit
- [ ] Notification stops after checkout

---

## Testing Notes

For all CRs, test scenarios:
1. Happy path (normal operation)
2. Edge case: midnight crossover
3. Edge case: multiple visits same day
4. Edge case: offline submission
5. Regression: existing functionality unaffected

---

## Timeline

| CR | Description | Start | End |
|----|-------------|-------|-----|
| CR-001 | Auto-checkout | Week 1 | Week 1 |
| CR-002 | Photo required | Week 1 | Week 1 |
| CR-003 | Open visit indicator | Week 2 | Week 2 |
| CR-004 | Server timestamp | Week 2 | Week 3 |
| CR-005 | Reminder notification | Week 4 | Week 4 |
