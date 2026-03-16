# Ops Action Plan Q1 2026
> **Generated:** 2026-01-13  
> **Based on:** Insight Pack January 2026  
> **Status:** For Review

---

## Executive Summary

Analysis of 33,510 completed visits identified **3 systemic issues** causing data quality problems:

| Issue | Count | % | Root Cause |
|-------|-------|---|------------|
| No Photo | 5,261 | 15.7% | No enforcement in app |
| Suspect Time (21-23h) | 5,711 | 17.0% | Bulk submission at day end |
| Multi-day Duration | 3,431 | 10.2% | Forgot to checkout |

These issues affect KPI accuracy and prevent fair technician evaluation.

---

## Priority 1: Critical (This Week)

### P1.1: Auto-Checkout at 18:00

**Problem:** 3,431 visits have multi-day duration (technician forgot checkout)  
**Solution:** Automatic checkout at 18:00 if visit still open

**Implementation:**
```javascript
// Pseudo-code
cron.schedule('0 18 * * 1-6', async () => {
  const openVisits = await Visit.find({ checkout: null, checkin: { $lt: today() } });
  for (const visit of openVisits) {
    visit.checkout = new Date();
    visit.checkout_type = 'AUTO';
    visit.flag = 'AUTO_CHECKOUT_18H';
    await visit.save();
  }
});
```

**KPI Impact:**
- Multi-day duration → 0% (eliminated)
- Duration compliance accuracy → increased

**Owner:** Dev Team  
**ETA:** 1 week

---

### P1.2: Block Checkout Without Photo (MOBILE/STATION)

**Problem:** 2,395 MOBILE+STATION visits without photos (excludes SUPPORT)  
**Solution:** Block checkout button if `foto_count = 0`

**Implementation:**
```javascript
// In checkout handler
if (visit.type === 't_mobile' || visit.type === 't_station') {
  if (visit.foto_count === 0) {
    throw new Error('Photo required before checkout');
  }
}
```

**Exclusion:** SUPPORT/CHECKLIST tasks (if confirmed by Ops not to require photos)

**KPI Impact:**
- Photo compliance (MOBILE) → 100%
- Photo compliance (STATION) → 100%

**Owner:** Dev Team  
**ETA:** 3 days

---

## Priority 2: Important (This Month)

### P2.1: Open Visit Indicator

**Problem:** Technicians start new visits without closing previous ones  
**Solution:** Show "Open Visit" warning, optionally block new visit

**Implementation:**
- UI: Red badge showing "1 visit masih terbuka"
- Option: Require closing or abandoning before new visit

**Owner:** Dev Team  
**ETA:** 2 weeks

---

### P2.2: Server-Recorded Timestamps

**Problem:** Check-in/out times may be manipulated (backdated)  
**Solution:** Use server timestamp instead of client timestamp

**Implementation:**
```javascript
// Instead of
visit.checkin = req.body.timestamp;

// Use
visit.checkin = new Date(); // Server time
visit.client_timestamp = req.body.timestamp; // Keep for audit
visit.timestamp_diff_seconds = differenceInSeconds(visit.checkin, req.body.timestamp);
```

**Flag:** If `timestamp_diff_seconds > 3600`, flag as `LATE_SYNC`

**Owner:** Dev Team  
**ETA:** 2 weeks

---

## Priority 3: Nice to Have (Q2)

### P3.1: Reminder Notification

**Trigger:** 2 hours after check-in if no checkout  
**Message:** "Anda masih dalam kunjungan di [Customer]. Jangan lupa checkout!"

### P3.2: Offline Sync Detection

**Flag:** Visits synced > 24 hours after check-in as `OFFLINE_SYNC`  
**KPI Treatment:** Exclude from on-time calculation in STRICT mode

---

## SOP Clarifications Required (Ops Team)

| Question | Context | Deadline |
|----------|---------|----------|
| Do SUPPORT/CHECKLIST require photos? | Currently 100% no-photo | This week |
| Are night visits (21-23h) legitimate? | Top customers: Bukit Darmo Golf | This week |
| STATION visit duration: is 8+ hours normal? | Median is 507 min (8.5h) | This week |

---

## Success Metrics

| Metric | Current | Target (End Q1) |
|--------|---------|-----------------|
| Photo Compliance (MOBILE+STATION) | 86.8% | 98% |
| Multi-day Duration | 10.2% | < 1% |
| On-time STRICT | 68.6% | 75% |
| NULL grades | 0 | 0 |
| Acceptance tests passing | 7/7 | 7/7 |

---

## Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Data Team | | | |
| Dev Team | | | |
| Operations | | | |
| Management | | | |
