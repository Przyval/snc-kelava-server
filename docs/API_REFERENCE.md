# SanoCare API Reference

> Base URL: `https://safencare.work`  
> Auth: `Authorization: Bearer <JWT>`  
> Login: `POST /api/v1/auth/login`

## Table of Contents

- [Accurate Accounting Export API](#accurate-export) — 3 endpoints
- [API Documentation Endpoint](#api-docs) — 1 endpoints
- [Fingerprint Attendance API](#attendance) — 10 endpoints
- [Universal Audit Log API](#audit-log) — 3 endpoints
- [Supervisory Action Log API](#audit-trail) — 4 endpoints
- [Enterprise Authentication API](#auth) — 6 endpoints
- [QR Code / Barcode Unit Checklist API](#barcode-checklist) — 6 endpoints
- [Breadcrumb GPS Tracking API](#breadcrumb) — 6 endpoints
- [Daily Operational Briefing API](#briefing) — 1 endpoints
- [Resource Calendar API - Dispatch View](#calendar) — 4 endpoints
- [Chemical Usage Tracking API](#chemical-tracking) — 5 endpoints
- [Client Portal API](#client-portal) — 4 endpoints
- [Complaint Tracking API](#complaints) — 7 endpoints
- [Completion Gate API - Evidence Enforcement](#completion-gate) — 3 endpoints
- [Contract Management API](#contracts) — 12 endpoints
- [Customer Satisfaction Score (CSAT) API](#csat) — 5 endpoints
- [Customers API](#customers) — 5 endpoints
- [Daily Digest API](#daily-digest) — 4 endpoints
- [Daily KPI Rapor Auto-Generation](#daily-rapor) — 4 endpoints
- [Dashboard Stats Widget API](#dashboard-stats) — 1 endpoints
- [GPS Drift Detection & Auto-Sidak Engine](#drift-detection) — 7 endpoints
- [Exception Queue API - Operational Issue Tracking](#exceptions) — 3 endpoints
- [Executive Summary API](#executive) — 1 endpoints
- [Export System API](#export) — 7 endpoints
- [Face Verification Attendance API](#face-attendance) — 4 endpoints
- [Governance](#governance) — 4 endpoints
- [GPS Live Map API v2](#gps-live) — 7 endpoints
- [Health Check & Monitoring API](#health) — 5 endpoints
- [Invoice Lock API - Contract-level Validation](#invoice-lock) — 2 endpoints
- [Lokasi (Customer) API — Kelava-compatible](#lokasi) — 2 endpoints
- [Mobile API — safeandcare.work](#mobile) — 14 endpoints
- [MOM (Minutes of Meeting) API](#mom) — 11 endpoints
- [Notification Center API](#notifications) — 5 endpoints
- [Ontology Resolver API](#ontology) — 4 endpoints
- [Operations API](#operations-kelava) — 4 endpoints
- [Ops](#ops) — 1 endpoints
- [Sales Pipeline API](#pipeline) — 12 endpoints
- [Punctuality Tracking API](#punctuality) — 4 endpoints
- [Schedule Auto-Generate Engine](#schedule-generator) — 4 endpoints
- [Schedule Template System API](#schedule-templates) — 7 endpoints
- [Schedule Template API (Plants vs Zombies)](#scheduling) — 10 endpoints
- [Technician Segments API](#segments) — 8 endpoints
- [Digital Service Form API](#service-form) — 5 endpoints
- [Staff Photo Management API](#staff-photos) — 3 endpoints
- [Supervisory Action / Sidak API](#supervisory) — 12 endpoints
- [Technicians API](#technicians) — 2 endpoints
- [Tracking](#tracking) — 1 endpoints
- [Performance Trends API](#trends) — 4 endpoints
- [User Management API](#user-management) — 8 endpoints
- [Photo & GPS Verification API](#verification) — 9 endpoints
- [WhatsApp Bot Gateway API](#wa-bot) — 7 endpoints
- [Priority Watchlist API](#watchlist) — 2 endpoints
- [Automated Weekly Report API](#weekly-report) — 5 endpoints
- [Winback Engine API](#winback) — 11 endpoints

---
## Accurate Accounting Export API
<a name="accurate-export"></a>

### `GET` `/api/v1/enterprise/accurate/preview`
GET /accurate/preview?month=YYYY-MM — preview completed visits for a month.

### `GET` `/api/v1/enterprise/accurate/download`
GET /accurate/download?month=YYYY-MM — download CSV for Accurate import.

### `GET` `/api/v1/enterprise/accurate/summary`
GET /accurate/summary?months=3 — monthly roll-up for the last N months.

---
## API Documentation Endpoint
<a name="api-docs"></a>

### `GET` `/api/v1/docs`
List all API endpoints with methods and descriptions.

---
## Fingerprint Attendance API
<a name="attendance"></a>

### `POST` `/api/v1/enterprise/webhooks/bioclock/push`
Receive attendance push events from BioClock.id.

**Parameters:**
- Expected payload (may vary by BioClock SDK version):

### `GET` `/api/v1/enterprise/attendance/today`
Today's attendance board: who's checked in, who hasn't.

### `GET` `/api/v1/enterprise/attendance/history`
Historical attendance logs.

### `GET` `/api/v1/enterprise/attendance/stats`
Attendance statistics for a date range.

### `GET` `/api/v1/enterprise/attendance/devices`
List all registered attendance devices.

### `POST` `/api/v1/enterprise/attendance/devices`
Register a new attendance device.

### `PATCH` `/api/v1/enterprise/attendance/devices/<int:device_id>`
Update device details.

### `GET` `/api/v1/enterprise/attendance/user-map`
List fingerprint user → technician mappings.

### `POST` `/api/v1/enterprise/attendance/user-map`
Map a fingerprint user ID to a SanoCare technician.

### `DELETE` `/api/v1/enterprise/attendance/user-map/<int:mapping_id>`
Remove a fingerprint user mapping.

---
## Universal Audit Log API
<a name="audit-log"></a>

### `GET` `/api/v1/enterprise/audit-log`
Query audit logs with filters.

**Parameters:**
- Params: module, action, entity_type, actor_id, days, page, per_page, q

### `GET` `/api/v1/enterprise/audit-log/stats`
Audit log statistics for the dashboard.

### `GET` `/api/v1/enterprise/audit-log/entity/<entity_type>/<entity_id>`
Get full audit history for a specific entity.

---
## Supervisory Action Log API
<a name="audit-trail"></a>

### `GET` `/api/v1/enterprise/audit/dashboard`
Supervisory overview: open reviews, escalation counts, recent activity.

### `GET` `/api/v1/enterprise/audit/feed`
Unified activity feed across all modules:

### `POST` `/api/v1/enterprise/audit/action`
Log a supervisory action on any entity.

**Parameters:**
- Body: {
- entity_type: 'customer' | 'technician' | 'contract' | 'campaign',
- entity_id: int,
- action: str,

### `GET` `/api/v1/enterprise/audit/actions/<entity_type>/<int:entity_id>`
Get all supervisory actions for a specific entity.

---
## Enterprise Authentication API
<a name="auth"></a>

### `POST` `/api/v1/auth/login`
Authenticate with ID Pekerja / email + password, receive JWT tokens.

**Parameters:**
- Body: { "login": "...", "password": "..." }
- Also accepts legacy { "email": "...", "password": "..." }
- Returns: { "access_token": "...", "refresh_token": "...", "user": {...} }

### `POST` `/api/v1/auth/refresh`
Exchange refresh token for new access + refresh tokens.

**Parameters:**
- Body: { "refresh_token": "..." }

### `GET` `/api/v1/auth/me`
Get current authenticated user profile.

### `POST` `/api/v1/auth/change-password`
Change password for current user.

**Parameters:**
- Body: { "current_password": "...", "new_password": "..." }

### `POST` `/api/v1/auth/logout`
Revoke current refresh token.

### `GET` `/api/v1/auth/verify`
Quick token verification endpoint.

---
## QR Code / Barcode Unit Checklist API
<a name="barcode-checklist"></a>

### `GET` `/api/v1/enterprise/barcode/units`
List units for a customer. Query: customer_id (required).

### `POST` `/api/v1/enterprise/barcode/units`
Register a new unit with barcode.

**Parameters:**
- Body: {
- customer_id: int,
- barcode: string,
- unit_type: "BAIT_STATION"|"TRAP"|"MONITOR"|...,

### `POST` `/api/v1/enterprise/barcode/units/bulk`
Bulk register units.

**Parameters:**
- Body: {
- customer_id: int,
- units: [

### `POST` `/api/v1/enterprise/barcode/scan`
Technician scans a unit barcode during visit.

**Parameters:**
- Body: {
- barcode: string,
- condition_code: "OK"|"DAMAGED"|"MISSING"|"NEEDS_REPLACEMENT"|"INFESTED"|"CLEAN",

### `GET` `/api/v1/enterprise/barcode/visit-checklist/<int:road_plan_id>`
Get checklist status for a visit: which units were scanned, which weren't.

### `GET` `/api/v1/enterprise/barcode/units/<int:unit_id>/history`
Scan history for a specific unit.

---
## Breadcrumb GPS Tracking API
<a name="breadcrumb"></a>

### `POST` `/api/v1/mobile/breadcrumb/ping`
Receive a single GPS position from mobile app.

**Parameters:**
- Body: {
- latitude: float,
- longitude: float,

### `POST` `/api/v1/mobile/breadcrumb/ping-batch`
Receive multiple GPS positions at once (offline sync).

**Parameters:**
- Body: {
- points: [

### `GET` `/api/v1/mobile/breadcrumb/trail/<int:tech_id>`
Get GPS breadcrumb trail for a technician on a specific date.

**Parameters:**
- Query params:
- date: YYYY-MM-DD (default: today)
- simplify: true (default) — reduce points for rendering

### `GET` `/api/v1/mobile/breadcrumb/live`
Get the most recent GPS position for each active technician (last 2 hours).

### `GET` `/api/v1/mobile/breadcrumb/summary/<int:tech_id>`
Get daily GPS summary for a technician (distance traveled, active time, etc.)

**Parameters:**
- Query params:
- start_date: YYYY-MM-DD
- end_date: YYYY-MM-DD

### `GET` `/api/v1/mobile/breadcrumb/heatmap`
GPS density heatmap data for all technicians on a given date.

**Parameters:**
- Query params: date (default: today)

---
## Daily Operational Briefing API
<a name="briefing"></a>

### `GET` `/api/v1/enterprise/briefing/today`
Morning briefing: everything admin needs to know today.

**Parameters:**
- Returns:

---
## Resource Calendar API - Dispatch View
<a name="calendar"></a>

### `GET` `/api/v1/enterprise/calendar/schedule`
Get weekly schedule grid: technicians × time slots.

**Parameters:**
- Query params:

### `GET` `/api/v1/enterprise/calendar/technician/<int:tech_id>/slots`
Get available slots for a specific technician.

**Parameters:**
- Query params:

### `GET` `/api/v1/enterprise/calendar/conflicts`
Detect scheduling conflicts (double bookings, overload).

### `GET` `/api/v1/enterprise/calendar/day-summary`
Get summary for a specific day - useful for calendar header.

---
## Chemical Usage Tracking API
<a name="chemical-tracking"></a>

### `GET` `/api/v1/enterprise/chemicals/catalog`
List all chemicals in catalog.

### `POST` `/api/v1/enterprise/chemicals/catalog`
Add a chemical to the catalog.

### `POST` `/api/v1/enterprise/chemicals/log`
Log chemical usage for a visit.

**Parameters:**
- Body: {
- customer_id: int,
- chemicals: [
- chemical_name: string,

### `GET` `/api/v1/enterprise/chemicals/usage`
Chemical usage history. Filters: customer_id, technician_id, days.

### `GET` `/api/v1/enterprise/chemicals/summary`
Aggregate chemical usage by type/chemical for reporting.

---
## Client Portal API
<a name="client-portal"></a>

### `POST` `/api/v1/enterprise/client-portal/tokens`
Create a shareable portal token for a customer.

**Parameters:**
- Body: {
- customer_id: int,

### `GET` `/api/v1/enterprise/client-portal/view`
Public client portal view. Accessed via token query parameter.

### `GET` `/api/v1/enterprise/client-portal/tokens`
List all portal tokens (admin view).

### `POST` `/api/v1/enterprise/client-portal/tokens/<int:token_id>/revoke`
Revoke a portal token.

---
## Complaint Tracking API
<a name="complaints"></a>

### `GET` `/api/v1/enterprise/complaints`
List complaints with optional filters.

### `POST` `/api/v1/enterprise/complaints`
Create a new complaint ticket.

### `GET` `/api/v1/enterprise/complaints/<int:complaint_id>`
Get complaint detail.

### `PATCH` `/api/v1/enterprise/complaints/<int:complaint_id>`
Update complaint: status, assignment, resolution, etc.

### `GET` `/api/v1/enterprise/complaints/customers/search`
Quick customer search for the complaint form.

### `GET` `/api/v1/enterprise/complaints/sla-status`
SLA health: counts of breached, at-risk (< 4h left), and on-track open tickets.

### `GET` `/api/v1/enterprise/complaints/technicians`
List technicians for assignment dropdown.

---
## Completion Gate API - Evidence Enforcement
<a name="completion-gate"></a>

### `POST` `/api/v1/enterprise/visits/<int:visit_id>/completion-status`
Attempt to validate a visit for completion.

**Parameters:**
- Note: This is a READ-ONLY check. Actual status update would require

### `GET` `/api/v1/enterprise/completion-gate/pending`
Get list of visits that have check-in but are not yet complete.

### `GET` `/api/v1/enterprise/completion-gate/stats`
Get completion gate statistics for today.

---
## Contract Management API
<a name="contracts"></a>

### `GET` `/api/v1/enterprise/contracts/dashboard`
Contract portfolio overview.

### `GET` `/api/v1/enterprise/contracts`
List all contracts with search and filters.

**Parameters:**
- Query params:
- search: Search by contract name, customer name
- status: active, expired, expiring_30d, expiring_60d
- page, per_page: Pagination

### `GET` `/api/v1/enterprise/contracts/<int:contract_id>`
Full contract detail with areas, subareas, and service history.

### `POST` `/api/v1/enterprise/contracts/<int:contract_id>/renewal-note`
Add a renewal tracking note to a contract.

**Parameters:**
- Body: { action, note, next_follow_up? }
- Actions: RENEWAL_INITIATED, CUSTOMER_CONTACTED, QUOTE_SENT, RENEWAL_CONFIRMED, RENEWAL_DECLINED

### `GET` `/api/v1/enterprise/contracts/<int:contract_id>/churn-reason`
Get churn/non-renewal reasons for a contract.

### `POST` `/api/v1/enterprise/contracts/<int:contract_id>/churn-reason`
Add a churn/non-renewal reason to a contract.

**Parameters:**
- Body: {
- reason_category: "service_quality"|"price"|"competitor"|"business_closed"|"relocation"|"other",

### `DELETE` `/api/v1/enterprise/contracts/<int:contract_id>/churn-reason/<int:reason_id>`
Delete a churn reason.

### `GET` `/api/v1/enterprise/contracts/<int:contract_id>/complaints`
Get complaints related to this contract's customer.

### `GET` `/api/v1/enterprise/contracts/alerts`
Get contracts requiring renewal action.

### `POST` `/api/v1/enterprise/contracts/<int:contract_id>/extend`
Extend a contract's end date.

**Parameters:**
- Body: { new_end_date: "YYYY-MM-DD", note?: str }

### `POST` `/api/v1/enterprise/contracts/<int:contract_id>/terminate`
Early terminate a contract.

**Parameters:**
- Body: { reason_category: str, reason_detail?: str, note?: str }

### `GET` `/api/v1/enterprise/contracts/<int:contract_id>/health`
Calculate a contract health score based on visit completion,

---
## Customer Satisfaction Score (CSAT) API
<a name="csat"></a>

### `POST` `/api/v1/enterprise/csat/submit`
Submit a CSAT rating for a visit.

**Parameters:**
- Body: {
- customer_id: int,
- technician_id: int,
- rating: 1-5,

### `GET` `/api/v1/enterprise/csat/dashboard`
CSAT overview with aggregated metrics.

### `GET` `/api/v1/enterprise/csat/technicians`
CSAT ranking by technician.

### `GET` `/api/v1/enterprise/csat/customers/<int:customer_id>`
CSAT history for a specific customer.

### `GET` `/api/v1/enterprise/csat/feedback`
Recent ratings with comments for review.

---
## Customers API
<a name="customers"></a>

### `GET` `/api/v1/enterprise/customers`
Get paginated list of customers with search and filters.

**Parameters:**
- Query params:
- search: Search by name, code, phone
- segment_id: Filter by segment
- status_filter: Smart filter (under_sla, at_risk, dormant, high_frequency)

### `GET` `/api/v1/enterprise/customers/<int:customer_id>`
SAP-Grade Account Control View.

### `GET` `/api/v1/enterprise/customers/<int:customer_id>/visits`
Get paginated visit history for a customer.

### `GET` `/api/v1/enterprise/customers/<int:customer_id>/contracts`
Get all contracts for a customer.

### `GET` `/api/v1/enterprise/customers/segments`
Get list of customer segments for filtering.

**Parameters:**
- Note: m_segment table doesn't exist so returning empty list.

---
## Daily Digest API
<a name="daily-digest"></a>

### `POST` `/api/v1/enterprise/daily-digest/generate`
Generate daily digest for a given date.

**Parameters:**
- Body: { date?: "YYYY-MM-DD", send_wa?: bool }

### `GET` `/api/v1/enterprise/daily-digest/latest`
Get the most recent daily digest.

### `GET` `/api/v1/enterprise/daily-digest/history`
List generated digests. Query params: days (default 30)

### `GET` `/api/v1/enterprise/daily-digest/preview`
Preview today's digest without saving.

---
## Daily KPI Rapor Auto-Generation
<a name="daily-rapor"></a>

### `POST` `/api/v1/enterprise/rapor/generate`
Generate daily KPI rapor for all technicians on a given date.

**Parameters:**
- Body: {
- date: "YYYY-MM-DD" (default: yesterday),
- KPI Weights:

### `GET` `/api/v1/enterprise/rapor/technician/<int:tech_id>`
Get rapor history for a technician.

### `GET` `/api/v1/enterprise/rapor/leaderboard`
KPI leaderboard for a date range.

### `GET` `/api/v1/enterprise/rapor/monthly/<int:tech_id>`
Monthly aggregated KPI for a technician.

---
## Dashboard Stats Widget API
<a name="dashboard-stats"></a>

### `GET` `/api/v1/enterprise/dashboard-stats`
Single endpoint returning all dashboard KPIs.

---
## GPS Drift Detection & Auto-Sidak Engine
<a name="drift-detection"></a>

### `GET` `/api/v1/enterprise/drift/config`
List all customer GPS configurations.

### `POST` `/api/v1/enterprise/drift/config`
Set GPS drift config for a customer.

**Parameters:**
- Body: {
- customer_id: int,
- latitude: float,
- longitude: float,

### `POST` `/api/v1/enterprise/drift/config/bulk-import`
Auto-populate customer GPS configs from visit check-in history.

### `POST` `/api/v1/enterprise/drift/scan`
Run GPS drift detection scan for recent visits.

**Parameters:**
- Body: {
- days: int (default 7),
- auto_sidak: bool (default false) — auto-create sidak for critical drift

### `GET` `/api/v1/enterprise/drift/alerts`
List drift alerts with filters.

### `POST` `/api/v1/enterprise/drift/alerts/<int:alert_id>/resolve`
Resolve a drift alert.

### `GET` `/api/v1/enterprise/drift/scores`
GPS compliance score per technician (last 30 days).

---
## Exception Queue API - Operational Issue Tracking
<a name="exceptions"></a>

### `GET` `/api/v1/enterprise/exceptions/queue`
Get full exception queue - all issues requiring attention.

### `GET` `/api/v1/enterprise/exceptions/by-technician`
Get exception counts grouped by technician.

### `GET` `/api/v1/enterprise/exceptions/summary`
Get exception summary for dashboard widget.

---
## Executive Summary API
<a name="executive"></a>

### `GET` `/api/v1/enterprise/executive/kpis`
Four operational briefing widgets for the executive dashboard.

---
## Export System API
<a name="export"></a>

### `GET` `/api/v1/enterprise/export/visits`
Export visit data as CSV.

**Parameters:**
- Query params: date_from, date_to (YYYY-MM-DD), technician_id

### `GET` `/api/v1/enterprise/export/leaderboard`
Export technician performance leaderboard as CSV.

**Parameters:**
- Query params: date_from, date_to

### `GET` `/api/v1/enterprise/export/complaints`
Export complaints as CSV. Query params: status, date_from, date_to

### `GET` `/api/v1/enterprise/export/contracts`
Export contract summary as CSV.

### `GET` `/api/v1/enterprise/export/csat`
Export CSAT ratings as CSV.

### `GET` `/api/v1/enterprise/export/audit-log`
Export audit log as CSV. Query params: days (default 30)

### `GET` `/api/v1/enterprise/export`
List available export endpoints.

---
## Face Verification Attendance API
<a name="face-attendance"></a>

### `POST` `/api/v1/mobile/face-attendance/clock-in`
Clock in with selfie face verification.

**Parameters:**
- Accepts multipart/form-data with:

### `POST` `/api/v1/mobile/face-attendance/clock-out`
Clock out (simpler — selfie optional).

### `GET` `/api/v1/mobile/face-attendance/today`
Today's face attendance board.

### `POST` `/api/v1/mobile/face-attendance/<int:log_id>/override`
Admin manually overrides face match result.

---
## Governance
<a name="governance"></a>

### `POST` `/api/v1/enterprise/review/close`
Transition account from OPEN -> CLOSED (RESOLVED or ACCEPTED_RISK).

**Parameters:**
- Mandatory: id_customer, outcome, note

### `POST` `/api/v1/enterprise/escalate`
Move escalation level: WATCH -> ATTENTION -> ESCALATED.

### `GET` `/api/v1/enterprise/history/<int:customer_id>`
Get audit trail for the courtroom view.

### `GET` `/api/v1/enterprise/policies/explain`
Get text justification for a rule code.

---
## GPS Live Map API v2
<a name="gps-live"></a>

### `GET` `/api/v1/enterprise/gps-live/positions`
Get the most recent GPS position for each active technician.

**Parameters:**
- Query params: date (YYYY-MM-DD, default: today)

### `GET` `/api/v1/enterprise/gps-live/today-route`
All planned visits for a date with last-known GPS coordinates per stop.

**Parameters:**
- Query params: date (YYYY-MM-DD, default: today)

### `GET` `/api/v1/enterprise/gps-live/trail/<int:tech_id>`
Get GPS trail for a specific technician on a given date.

### `GET` `/api/v1/enterprise/gps-live/activity`
Field activity summary for a date.

**Parameters:**
- Query params: date (YYYY-MM-DD, default: today)

### `GET` `/api/v1/enterprise/gps-live/available-dates`
Return dates that have GPS/visit data, for the calendar picker.

**Parameters:**
- Query params: months (int, default: 3)

### `GET` `/api/v1/enterprise/gps-live/timeline/<int:tech_id>`
Full day visit timeline for one technician.

**Parameters:**
- Query params: date (YYYY-MM-DD, default: today)

### `GET` `/api/v1/enterprise/gps-live/atrisk-locations`
AT_RISK / OVERDUE / P1 customers with last-known GPS coordinates.

---
## Health Check & Monitoring API
<a name="health"></a>

### `GET` `/api/v1/enterprise/health/ping`
Quick liveness probe (no auth).

### `GET` `/api/v1/enterprise/health/deep`
Comprehensive health check with DB, disk, uploads diagnostics.

### `GET` `/api/v1/enterprise/health/history`
Get recent health check history.

### `GET` `/api/v1/enterprise/health/status`
Compact status for dashboard embedding.

### `POST` `/api/v1/enterprise/health/reset-circuit-breaker`
Manually reset Kelava circuit breaker after DB comes back online.

---
## Invoice Lock API - Contract-level Validation
<a name="invoice-lock"></a>

### `GET` `/api/v1/enterprise/invoice-lock/contracts`
List contracts with their readiness for invoicing based on visit execution proof.

### `GET` `/api/v1/enterprise/invoice-lock/contracts/<int:contract_id>/readiness`
Detailed checklist of why a contract is locked or ready for invoicing.

---
## Lokasi (Customer) API — Kelava-compatible
<a name="lokasi"></a>

### `GET` `/api/v1/enterprise/lokasi`
Paginated customer list with filters.

### `GET` `/api/v1/enterprise/lokasi/filters`
Distinct values for filter dropdowns.

---
## Mobile API — safeandcare.work
<a name="mobile"></a>

### `GET` `/api/v1/enterprise/dashboard`
Summary stats for the mobile home screen.

### `GET` `/api/v1/enterprise/visits/today`
Today's road plan for the logged-in technician (by p_user_id).

### `GET` `/api/v1/enterprise/visits/schedule`
Visit schedule for a given date (defaults to today).

**Parameters:**
- Query param: ?date=YYYY-MM-DD

### `POST` `/api/v1/enterprise/visits/<int:road_plan_id>/checkin`
Check in to a visit — creates or updates mobile_visits record.

### `POST` `/api/v1/enterprise/visits/<int:road_plan_id>/checkout`
Check out from a visit.

### `GET` `/api/v1/enterprise/customers`
Customer list with visit count.

### `GET` `/api/v1/enterprise/customers/<int:customer_id>`
Customer detail with contracts and recent visit history.

### `GET` `/api/v1/enterprise/approvals`
Pending supervisory actions awaiting koordinator approval.

### `POST` `/api/v1/enterprise/approvals/<int:action_id>/approve`
Koordinator approves a pending action.

### `POST` `/api/v1/enterprise/approvals/<int:action_id>/reject`
Koordinator rejects a pending action.

### `POST` `/api/v1/enterprise/visits/<int:road_plan_id>/photos`
Upload photo evidence for a visit (check-in or check-out).

### `GET` `/api/v1/enterprise/visits/<int:road_plan_id>/photos`
List all photos for a visit (mobile-uploaded + Kelava originals).

### `GET` `/api/v1/enterprise/visits/<int:road_plan_id>/photos/<path:filename>`
Serve a mobile-uploaded photo file.

### `GET` `/api/v1/enterprise/my-performance`
Personal performance stats for the logged-in technician.

---
## MOM (Minutes of Meeting) API
<a name="mom"></a>

### `POST` `/api/v1/enterprise/mom/meetings`
Create a new meeting record.

### `GET` `/api/v1/enterprise/mom/meetings`
List meetings with pagination and search.

### `GET` `/api/v1/enterprise/mom/meetings/<int:meeting_id>`
Get meeting detail with transcript, summary, and action items.

### `DELETE` `/api/v1/enterprise/mom/meetings/<int:meeting_id>`
Delete a meeting (admin only).

### `POST` `/api/v1/enterprise/mom/meetings/<int:meeting_id>/audio`
Upload audio recording for a meeting.

### `POST` `/api/v1/enterprise/mom/meetings/<int:meeting_id>/transcribe`
Transcribe meeting audio using Google Gemini.

### `PATCH` `/api/v1/enterprise/mom/meetings/<int:meeting_id>/transcript`
Edit/correct the transcript manually.

### `POST` `/api/v1/enterprise/mom/meetings/<int:meeting_id>/summarize`
Generate structured MOM summary using Gemini.

### `PATCH` `/api/v1/enterprise/mom/meetings/<int:meeting_id>/actions/<int:action_id>`
Update action item status or details.

### `POST` `/api/v1/enterprise/mom/meetings/<int:meeting_id>/send`
Send MOM summary via WhatsApp.

### `GET` `/api/v1/enterprise/mom/meetings/<int:meeting_id>/distributions`
Get send history for a meeting.

---
## Notification Center API
<a name="notifications"></a>

### `GET` `/api/v1/enterprise/notifications`
Get notifications for current user.

**Parameters:**
- Query params: unread_only (bool), category, page, per_page

### `POST` `/api/v1/enterprise/notifications/<int:notif_id>/read`
Mark a notification as read.

### `POST` `/api/v1/enterprise/notifications/read-all`
Mark all notifications as read for current user.

### `POST` `/api/v1/enterprise/notifications/generate`
Scan for operational issues and create notifications.

### `GET` `/api/v1/enterprise/notifications/summary`
Quick unread count per category for badge display.

---
## Ontology Resolver API
<a name="ontology"></a>

### `GET` `/api/v1/enterprise/ontology/schema`
Return the ontology schema — object types and their properties/links.

### `GET` `/api/v1/enterprise/ontology/objects/customer/<int:customer_id>`
Full customer ontology object.

**Parameters:**
- Merges: m_customer + v_customer_rfm_segment + v_customer_priority_action

### `GET` `/api/v1/enterprise/ontology/objects/technician/<int:tech_id>`
Full technician ontology object.

**Parameters:**
- Merges: p_user + enterprise_users + v_tech_verification_score

### `GET` `/api/v1/enterprise/ontology/search`
Cross-object search across customers and technicians.

---
## Operations API
<a name="operations-kelava"></a>

### `GET` `/api/v1/enterprise/operations/workload`
Get today's workload summary.

**Parameters:**
- Query params:
- date: Target date (default: today)

### `GET` `/api/v1/enterprise/operations/exceptions`
Get exception counts (overdue, missing data, etc.).

### `GET` `/api/v1/enterprise/operations/exceptions/table`
Get paginated list of road plans needing attention.

**Parameters:**
- Query params:
- type: Exception type (overdue, missing_checkout, short_visit)
- page: Page number (default: 1)
- per_page: Items per page (default: 20)

### `GET` `/api/v1/enterprise/operations/road-plans`
Get paginated list of road plans with filters.

**Parameters:**
- Query params:
- date: Target date (default: today)
- status: Filter by status
- type: Filter by type

---
## Ops
<a name="ops"></a>

### `GET` `/api/v1/map/positions`
Get latest position for each technician

---
## Sales Pipeline API
<a name="pipeline"></a>

### `GET` `/api/v1/enterprise/pipeline/funnel`
Funnel counts per channel and overall, plus survey stats.

### `GET` `/api/v1/enterprise/pipeline/leads`
Paginated lead list with search/filter/sort.

### `GET` `/api/v1/enterprise/pipeline/leads/<int:lead_id>`
Single lead detail.

### `GET` `/api/v1/enterprise/pipeline/sdr-performance`
SDR performance from Survey data.

### `GET` `/api/v1/enterprise/pipeline/trends`
Monthly outreach activity trends per channel.

### `GET` `/api/v1/enterprise/pipeline/insights`
Actionable insights: stale leads, hot prospects, closed lost analysis.

### `GET` `/api/v1/enterprise/pipeline/hubexo/enrichment-stats`
Coverage metrics for Hubexo enrichment KPI cards.

### `GET` `/api/v1/enterprise/pipeline/hubexo/projects`
Enriched project list with geo + classification.

### `GET` `/api/v1/enterprise/pipeline/hubexo/companies`
Enriched company directory.

### `GET` `/api/v1/enterprise/pipeline/hubexo/contacts`
Enriched contact list with combined emails + LinkedIn.

### `GET` `/api/v1/enterprise/pipeline/hubexo/map-data`
GeoJSON FeatureCollection for Leaflet.js map.

### `GET` `/api/v1/enterprise/pipeline/hubexo/export`
CSV export of enriched Hubexo contacts for CRM import.

---
## Punctuality Tracking API
<a name="punctuality"></a>

### `GET` `/api/v1/enterprise/punctuality/daily`
Get punctuality report for a specific date.

**Parameters:**
- Query params:
- date: YYYY-MM-DD (default: today)
- segment: Filter by segment
- late_only: true to show only late check-ins

### `GET` `/api/v1/enterprise/punctuality/technician/<int:tech_id>`
Punctuality history for a specific technician.

**Parameters:**
- Query params:
- start_date, end_date: Date range (default: last 30 days)

### `GET` `/api/v1/enterprise/punctuality/ranking`
Rank technicians by lateness frequency.

**Parameters:**
- Perfect for daily morning meeting: "Kemarin siapa yang telat?"
- Query params:
- days: Look-back period (default: 7)
- segment: Filter by segment

### `GET` `/api/v1/enterprise/punctuality/yesterday`
Quick report: Who was late yesterday?

---
## Schedule Auto-Generate Engine
<a name="schedule-generator"></a>

### `POST` `/api/v1/enterprise/schedule-gen/generate`
Auto-generate t_road_plan entries from schedule_templates.

**Parameters:**
- Body: {
- year: int,
- month: int,
- dry_run: bool (default true — preview only)

### `PUT` `/api/v1/enterprise/schedule-gen/move`
Move a road plan to a different date and/or technician (drag-and-drop).

**Parameters:**
- Body: {
- road_plan_id: int,

### `PUT` `/api/v1/enterprise/schedule-gen/swap`
Swap two road plans' technician assignments.

**Parameters:**
- Body: { road_plan_id_1: int, road_plan_id_2: int }

### `GET` `/api/v1/enterprise/schedule-gen/gaps`
Find scheduling gaps: customers with active contracts but no visits scheduled.

**Parameters:**
- Query params: month (int), year (int)

---
## Schedule Template System API
<a name="schedule-templates"></a>

### `GET` `/api/v1/enterprise/schedule-templates`
List all schedule templates, optionally filtered by technician.

### `POST` `/api/v1/enterprise/schedule-templates`
Create a schedule template.

**Parameters:**
- Body: {
- name: str,
- technician_id: int,
- items: [{ day_of_week: 0-6 (Mon-Sun), customer_id: int, service_type?: str, notes?: str }]

### `GET` `/api/v1/enterprise/schedule-templates/<int:tpl_id>`
Get template with all items.

### `PUT` `/api/v1/enterprise/schedule-templates/<int:tpl_id>`
Replace template items entirely.

**Parameters:**
- Body: { name?: str, items: [...] }

### `DELETE` `/api/v1/enterprise/schedule-templates/<int:tpl_id>`
Delete a schedule template.

### `POST` `/api/v1/enterprise/schedule-templates/<int:tpl_id>/apply`
Apply a template to generate road_plan entries for a given week.

**Parameters:**
- Body: { week_start: "YYYY-MM-DD" (must be a Monday) }

### `GET` `/api/v1/enterprise/schedule-templates/technicians`
Quick technician search for template forms.

---
## Schedule Template API (Plants vs Zombies)
<a name="scheduling"></a>

### `GET` `/api/v1/enterprise/scheduling/templates`
List all schedule templates with filters.

**Parameters:**
- Query params:
- technician_id: Filter by technician
- customer_id: Filter by customer
- day_of_week: Filter by day (0-6)

### `POST` `/api/v1/enterprise/scheduling/templates`
Create a new schedule template.

**Parameters:**
- Body: {
- customer_id: int,
- day_of_week: 0-6,
- scheduled_time: "HH:MM",

### `PATCH` `/api/v1/enterprise/scheduling/templates/<int:template_id>`
Update a schedule template.

### `DELETE` `/api/v1/enterprise/scheduling/templates/<int:template_id>`
Deactivate (soft-delete) a schedule template.

### `GET` `/api/v1/enterprise/scheduling/board`
The "Plants vs Zombies" scheduling board.

**Parameters:**
- Query params:
- start_date: YYYY-MM-DD (default: Monday of current week)
- days: number of days (default: 7)

### `POST` `/api/v1/enterprise/scheduling/assign`
Assign a technician to a schedule template (drag-and-drop).

**Parameters:**
- Body: { template_id: int, technician_id: int }

### `GET` `/api/v1/enterprise/scheduling/technicians-list`
Simple technician list for dropdowns (id + name + segment).

### `POST` `/api/v1/enterprise/scheduling/auto-assign`
Auto-assign unassigned templates to technicians using load balancing.

**Parameters:**
- Algorithm:
- Body: {

### `POST` `/api/v1/enterprise/scheduling/detect-patterns`
AI-powered pattern detection from historical visit data.

**Parameters:**
- Body: { months_back: int (default: 3), min_occurrences: int (default: 3) }

### `POST` `/api/v1/enterprise/scheduling/apply-patterns`
Create templates from detected patterns.

**Parameters:**
- Body: {
- patterns: [

---
## Technician Segments API
<a name="segments"></a>

### `GET` `/api/v1/enterprise/segments`
List all technicians with their segments and KPI summary.

### `POST` `/api/v1/enterprise/segments`
Assign or update a technician's segment.

**Parameters:**
- Body: {
- technician_id: int,
- segment: "MOBILE"|"STATION"|"SUPPORT"|"SUPERVISOR",

### `POST` `/api/v1/enterprise/segments/batch`
Batch assign segments to multiple technicians.

**Parameters:**
- Body: {
- assignments: [

### `GET` `/api/v1/enterprise/segments/<int:tech_id>`
Get segment info and KPI rules for a specific technician.

### `GET` `/api/v1/enterprise/segments/kpi-rules`
Get all KPI rules grouped by segment.

### `GET` `/api/v1/enterprise/segments/leaderboard`
Leaderboard split by segment.

**Parameters:**
- Query params:
- segment: Filter to one segment
- days: Period in days (default: 30)

### `PATCH` `/api/v1/enterprise/segments/kpi-rules/<int:rule_id>`
Update KPI rule thresholds (green/yellow/red).

**Parameters:**
- Body: {

### `GET` `/api/v1/enterprise/segments/unassigned`
List technicians who haven't been assigned to any segment yet.

---
## Digital Service Form API
<a name="service-form"></a>

### `POST` `/api/v1/enterprise/service-form`
Create or submit a service form.

**Parameters:**
- Body: {
- customer_id: int,
- areas_serviced: string,
- findings: string (required),

### `GET` `/api/v1/enterprise/service-form/<int:form_id>`
Get service form detail.

### `GET` `/api/v1/enterprise/service-form`
List service forms with filters.

### `PATCH` `/api/v1/enterprise/service-form/<int:form_id>`
Update a draft service form.

### `GET` `/api/v1/enterprise/service-form/customer/<int:customer_id>/history`
Service form history for a customer (for client-facing reports).

---
## Staff Photo Management API
<a name="staff-photos"></a>

### `GET` `/api/v1/enterprise/staff-photos`
List all staff photos with metadata.

### `POST` `/api/v1/enterprise/staff-photos/<int:p_user_id>`
Upload/replace staff photo for a technician.

### `DELETE` `/api/v1/enterprise/staff-photos/<int:p_user_id>`
Delete staff photo for a technician.

---
## Supervisory Action / Sidak API
<a name="supervisory"></a>

### `GET` `/api/v1/enterprise/supervisory/actions`
List supervisory actions with filters.

**Parameters:**
- Query params:
- action_type: Filter by type
- supervisor_id: Filter by supervisor
- target_technician_id: Filter by target technician

### `POST` `/api/v1/enterprise/supervisory/actions`
Create a supervisory action.

**Parameters:**
- Body: {
- action_type: "SIDAK"|"SP_WARNING"|"COACHING"|"REVIEW"|"NEW_CLIENT_INSTALL"|"AUDIT_ACCOMPANY"|"COMPLAINT_HANDLING",
- supervisor_id: int,
- scheduled_date: "YYYY-MM-DD",

### `POST` `/api/v1/enterprise/supervisory/actions/<int:action_id>/complete`
Complete a supervisory action with findings.

**Parameters:**
- Body: { findings, follow_up_action?, follow_up_deadline? }

### `POST` `/api/v1/enterprise/supervisory/actions/<int:action_id>/approve`
Koordinator approves a pending supervisory action (sidak/SP).

**Parameters:**
- Body: { note?: string }

### `POST` `/api/v1/enterprise/supervisory/actions/<int:action_id>/reject`
Koordinator rejects a pending supervisory action.

**Parameters:**
- Body: { reason: string }

### `GET` `/api/v1/enterprise/supervisory/actions/pending`
List all actions pending koordinator approval.

### `POST` `/api/v1/enterprise/supervisory/actions/<int:action_id>/cancel`
Cancel a scheduled supervisory action.

### `POST` `/api/v1/enterprise/supervisory/trigger-sidak`
Trigger a sidak (surprise inspection) for a technician.

**Parameters:**
- Body: {
- supervisor_id: int,
- target_technician_id: int,

### `GET` `/api/v1/enterprise/supervisory/calendar/<int:supervisor_id>`
Get supervisor's calendar with all actions.

**Parameters:**
- Query params:
- start_date: YYYY-MM-DD
- end_date: YYYY-MM-DD

### `GET` `/api/v1/enterprise/supervisory/sidak-candidates`
Suggest technicians that should be inspected based on:

### `POST` `/api/v1/enterprise/supervisory/reports`
Submit a supervision/QC report.

**Parameters:**
- Body: {
- supervisor_id: int,
- technician_id: int,
- score_appearance: 1-5,

### `GET` `/api/v1/enterprise/supervisory/reports/technician/<int:tech_id>`
Get all supervision reports for a technician.

---
## Technicians API
<a name="technicians"></a>

### `POST` `/api/v1/enterprise/technicians/leaderboard`
Recompute KPI archive for current month (or specified month).

**Parameters:**
- Body: { month?: "2026-02" }

### `GET` `/api/v1/enterprise/technicians/kpi-archive/available-months`
Get list of months that have KPI archive data.

---
## Tracking
<a name="tracking"></a>

### `POST` `/api/v1/enterprise/tracking/position`
Receive high-frequency GPS position from technician app.

**Parameters:**
- Payload: { "lat": -7.25, "lng": 112.75, "timestamp": "ISO...", "tech_id": 123 }

---
## Performance Trends API
<a name="trends"></a>

### `GET` `/api/v1/enterprise/trends/weekly`
Overall weekly completion trends for the past N weeks.

**Parameters:**
- Query params: weeks (default 12)

### `GET` `/api/v1/enterprise/trends/technician/<int:tech_id>`
Performance trend for a specific technician.

**Parameters:**
- Query params: weeks (default 12)

### `GET` `/api/v1/enterprise/trends/comparison`
Compare all technicians' performance for a given period.

**Parameters:**
- Query params: days (default 30)

### `GET` `/api/v1/enterprise/trends/coverage`
Monthly customer coverage: how many unique customers visited vs total.

**Parameters:**
- Query params: months (default 6)

---
## User Management API
<a name="user-management"></a>

### `GET` `/api/v1/enterprise/users/`
List all enterprise users with filtering.

### `GET` `/api/v1/enterprise/users/<int:user_id>`
Get detailed user info including recent auth activity.

### `POST` `/api/v1/enterprise/users/`
Create a new enterprise user.

### `PATCH` `/api/v1/enterprise/users/<int:user_id>`
Update user profile (role, name, active status).

### `POST` `/api/v1/enterprise/users/<int:user_id>/reset-password`
Admin reset - set a new password for a user.

### `POST` `/api/v1/enterprise/users/<int:user_id>/unlock`
Unlock a locked-out user account.

### `GET` `/api/v1/enterprise/users/auth-log`
View system-wide auth audit log.

### `GET` `/api/v1/enterprise/users/stats`
User management overview stats.

---
## Photo & GPS Verification API
<a name="verification"></a>

### `GET` `/api/v1/enterprise/verification/dashboard`
Verification dashboard overview with anomaly counts and trends.

### `GET` `/api/v1/enterprise/verification/scorecards`
Technician compliance scorecards (30-day window).

### `GET` `/api/v1/enterprise/verification/anomalies`
List visits with anomaly flags.

### `GET` `/api/v1/enterprise/verification/visit/<int:visit_id>`
Full verification detail for a single visit: GPS, photos, flags.

### `POST` `/api/v1/enterprise/verification/flag`
Manually flag a visit for review.

### `POST` `/api/v1/enterprise/verification/flag/<int:flag_id>/resolve`
Mark a flag as resolved with notes.

### `POST` `/api/v1/enterprise/verification/scan`
Run anomaly detection scan for recent visits and auto-create flags.

### `GET` `/api/v1/enterprise/verification/photos/<int:road_plan_id>`
Get all photos for a road plan.

### `GET` `/api/v1/enterprise/verification/photo-proxy`
Proxy and compress photos from Kelava server.

**Parameters:**
- Security: only allows fetching from whitelisted Kelava hosts.
- Query params:
- path: photo path from t_road_plan_foto.path
- size: thumb (300px) | medium (800px) | full (1600px), default=medium

---
## WhatsApp Bot Gateway API
<a name="wa-bot"></a>

### `GET` `/api/v1/enterprise/wa-bot/webhook`
Webhook verification (for Fonnte/Meta setup).

### `POST` `/api/v1/enterprise/wa-bot/webhook`
Receive incoming WA messages and process commands.

**Parameters:**
- Fonnte webhook format: { "sender": "6281...", "message": "...", "name": "..." }

### `POST` `/api/v1/enterprise/wa-bot/send`
Send a WA message manually.

**Parameters:**
- Body: { phone: str, message: str, template_name?: str }

### `POST` `/api/v1/enterprise/wa-bot/send-bulk`
Send WA message to multiple recipients.

**Parameters:**
- Body: { recipients: [{ phone, name? }], message: str, template_name?: str }

### `POST` `/api/v1/enterprise/wa-bot/send-schedule-reminder`
Send tomorrow's schedule to all technicians via WA.

**Parameters:**
- Body: { date?: "YYYY-MM-DD" (defaults to tomorrow) }

### `GET` `/api/v1/enterprise/wa-bot/log`
Query WA message log.

### `GET` `/api/v1/enterprise/wa-bot/templates`
List available message templates.

---
## Priority Watchlist API
<a name="watchlist"></a>

### `GET` `/api/v1/enterprise/watchlist`
Priority watchlist: all P1/P2 customers OR account_status AT_RISK/OVERDUE.

**Parameters:**
- Query params:
- priority: P1 | P2  (filter)
- status:   AT_RISK | OVERDUE | INACTIVE  (filter)
- limit:    max rows (default 200)

### `GET` `/api/v1/enterprise/due-visits`
Customers whose scheduled visit is due within the next N days.

**Parameters:**
- Calculated from: last_completed_visit_at::date + expected_cycle_days
- Query params:
- days: forecast horizon in days (default 30, max 90)

---
## Automated Weekly Report API
<a name="weekly-report"></a>

### `POST` `/api/v1/enterprise/weekly-report/generate`
Generate a weekly report for the given week.

**Parameters:**
- Body: { week_start?: "YYYY-MM-DD" }  (defaults to last Monday)

### `GET` `/api/v1/enterprise/weekly-report/latest`
Get the most recent weekly report.

### `GET` `/api/v1/enterprise/weekly-report/history`
List all generated weekly reports.

### `GET` `/api/v1/enterprise/weekly-report/<int:report_id>`
Get a specific weekly report by ID.

### `GET` `/api/v1/enterprise/weekly-report/preview`
Preview this week's report without saving.

---
## Winback Engine API
<a name="winback"></a>

### `GET` `/api/v1/enterprise/winback/campaigns`
List all winback campaigns with summary stats.

### `POST` `/api/v1/enterprise/winback/campaigns`
Create a new winback campaign.

**Parameters:**
- Body: { name, description?, target_segment?, assigned_team?, customer_ids: [int] }

### `GET` `/api/v1/enterprise/winback/campaigns/<int:campaign_id>`
Get campaign detail with all entries.

### `POST` `/api/v1/enterprise/winback/campaigns/<int:campaign_id>/activate`
Transition campaign: DRAFT → ACTIVE.

### `POST` `/api/v1/enterprise/winback/campaigns/<int:campaign_id>/complete`
Transition campaign: ACTIVE → COMPLETED.

### `PATCH` `/api/v1/enterprise/winback/entries/<int:entry_id>/status`
Update winback entry status.

**Parameters:**
- Body: { status, note? }
- Valid transitions:

### `PATCH` `/api/v1/enterprise/winback/entries/<int:entry_id>/assign`
Assign a winback entry to a sales rep.

**Parameters:**
- Body: { assigned_to: int (p_user.id) }

### `POST` `/api/v1/enterprise/winback/entries/<int:entry_id>/note`
Add a contact note to an entry (without changing status).

**Parameters:**
- Body: { note: str }

### `GET` `/api/v1/enterprise/winback/entries/<int:entry_id>/activity`
Get full activity log for a winback entry.

### `GET` `/api/v1/enterprise/winback/stats`
Overall winback engine statistics.

### `GET` `/api/v1/enterprise/winback/eligible`
Get list of customers eligible for winback.
