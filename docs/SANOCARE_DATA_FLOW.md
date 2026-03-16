# SanoCare Database - Data Flow & Core Apps

> **Generated:** 2026-01-10 | **Database:** PostgreSQL @ app.kelava.id

---

## 📊 Database Overview

| Metric | Value |
|--------|-------|
| **Total Tables** | 154 |
| **Database Size** | ~200MB |
| **Primary Domain** | Pest Control Service Management |

### Entity Counts (Live Data)

| Entity | Count | Notes |
|--------|-------|-------|
| road_plans | 33,651 | Scheduled visits |
| visits | 33,645 | Executed visits (check-in/out) |
| customers | 1,301 | Registered clients |
| users (teknisi) | 85 | Field technicians + staff |
| kontrak | 75 | Active contracts |
| invoices | 5 | Billing records |
| clients (tenant) | 2 | SaaS tenants |

---

## 🏗️ Core Data Architecture

### Table Naming Convention
| Prefix | Meaning | Example |
|--------|---------|---------|
| `m_` | Master data | `m_customer`, `m_product` |
| `t_` | Transactional | `t_visit`, `t_invoice` |
| `p_` | Platform/User | `p_user`, `p_role` |
| `s_` | Settings/System | `s_pos` |
| `x_` | Extended config | `x_setting_application` |
| `target_` | KPI targets | `target_sales` |

---

## 🔄 Core Application Flow

```mermaid
flowchart TD
    subgraph MASTER["📋 MASTER DATA"]
        CLIENT["m_client<br/>2 tenants"]
        CUSTOMER["m_customer<br/>1,301 customers"]
        USER["p_user<br/>85 users/teknisi"]
        OUTLET["m_outlet<br/>Service locations"]
        KONTRAK["m_customer_kontrak<br/>75 contracts"]
    end

    subgraph PLANNING["📅 PLANNING"]
        ROADPLAN["t_road_plan<br/>33,651 schedules"]
        RP_AREA["t_road_plan_area<br/>Area assignments"]
        RP_SUBAREA["t_road_plan_subarea<br/>Sub-area details"]
    end

    subgraph EXECUTION["🚀 EXECUTION"]
        VISIT["t_visit<br/>33,645 visits"]
        VISIT_DATA["t_visit_data<br/>Service details"]
        VISIT_PRODUCT["t_visit_product<br/>Products used"]
        RP_FOTO["t_road_plan_foto<br/>Photo evidence"]
    end

    subgraph BILLING["💰 BILLING"]
        INVOICE["t_invoice<br/>5 invoices"]
        PAYMENT["t_payment"]
        SO["t_sales_order"]
    end

    CLIENT --> CUSTOMER
    CUSTOMER --> KONTRAK
    KONTRAK --> ROADPLAN
    USER --> ROADPLAN
    OUTLET --> ROADPLAN
    
    ROADPLAN --> RP_AREA
    ROADPLAN --> RP_SUBAREA
    ROADPLAN --> VISIT
    
    VISIT --> VISIT_DATA
    VISIT --> VISIT_PRODUCT
    VISIT --> RP_FOTO
    
    KONTRAK --> INVOICE
    VISIT --> INVOICE
```

---

## 🎯 Road Plan Flow (Core Business Process)

### Status Lifecycle
```mermaid
stateDiagram-v2
    [*] --> Baru: Created
    Baru --> Requested: Submitted for approval
    Requested --> Berjalan: Approved & Active
    Berjalan --> Selesai: Completed
    Selesai --> [*]
    
    note right of Baru: 3 records
    note right of Requested: 4 records
    note right of Berjalan: 207 records
    note right of Selesai: 33,437 records (99.4%)
```

### Road Plan Types
| Type | Count | Description |
|------|-------|-------------|
| `t_mobile` | 20,630 | Mobile technician visit |
| `t_station` | 8,173 | Station-based service |
| `checklist` | 2,759 | Routine checklist |
| `spv_tc` | 1,862 | Supervisor technical check |
| `spv_qc` | 223 | Supervisor quality control |

---

## 🔑 Key Entities Detail

### m_customer (45 columns)
Customer master data with full profile.

| Key Columns | Type | Purpose |
|-------------|------|---------|
| `id`, `code`, `name` | identity | Unique identification |
| `address`, `id_city`, `id_kecamatan`, `id_kelurahan` | location | Geographic hierarchy |
| `phone1`, `phone2`, `email` | contact | Communication |
| `id_segment`, `id_customer_group` | classification | Business segmentation |
| `credit_limit`, `payment_term` | financial | Billing terms |
| `id_owner`, `is_owner` | ownership | Multi-outlet support |
| `id_sales` | relationship | Assigned salesperson |

### t_road_plan (16 columns)
Scheduled service visits.

| Key Columns | Type | Purpose |
|-------------|------|---------|
| `id`, `no_ra` | identity | Visit ID & reference number |
| `visit_date` | timestamp | Scheduled date |
| `status` | enum | Baru/Requested/Berjalan/Selesai |
| `type` | enum | t_mobile/t_station/checklist/spv_* |
| `id_user` | FK | Assigned technician |
| `id_customer`, `id_outlet` | FK | Customer & location |
| `id_kontrak` | FK | Contract reference |
| `is_cancel` | boolean | Cancellation flag |

### t_visit (19 columns)
Executed visits with GPS tracking.

| Key Columns | Type | Purpose |
|-------------|------|---------|
| `id`, `id_road_plan` | identity | Links to schedule |
| `check_in`, `check_out` | timestamp | Time tracking |
| `latitude`, `longitude` | numeric | Check-in GPS |
| `latitude_o`, `longitude_o` | numeric | Check-out GPS |
| `meta_data`, `additional_data` | JSON | Flexible service data |
| `meta_distance` | JSON | Distance calculations |
| `realization_date` | date | Actual service date |

### m_customer_kontrak (8 columns)
Service contracts.

| Key Columns | Type | Purpose |
|-------------|------|---------|
| `id`, `no_kontrak` | identity | Contract number |
| `id_customer` | FK | Customer reference |
| `start_date`, `end_date` | date | Contract period |
| `is_active` | enum | Active status |
| `kode_akses` | varchar | Access code |

---

## 📍 Geographic Hierarchy

```mermaid
flowchart LR
    COUNTRY["m_country"] --> PROVINCE["m_province"]
    PROVINCE --> CITY["m_city<br/>~500 cities"]
    CITY --> KECAMATAN["m_kecamatan<br/>~7K districts"]
    KECAMATAN --> KELURAHAN["m_kelurahan<br/>~80K villages"]
```

---

## 🔗 Entity Relationship Summary

```mermaid
erDiagram
    m_client ||--o{ m_customer : "has"
    m_client ||--o{ p_user : "employs"
    m_client ||--o{ m_outlet : "operates"
    
    m_customer ||--o{ m_customer_kontrak : "signs"
    m_customer ||--o{ t_road_plan : "receives"
    
    m_customer_kontrak ||--o{ t_road_plan : "schedules"
    m_customer_kontrak ||--o{ m_customer_kontrak_area : "covers"
    
    t_road_plan ||--|| t_visit : "executed as"
    t_road_plan ||--o{ t_road_plan_area : "includes"
    t_road_plan ||--o{ t_road_plan_foto : "documented by"
    
    p_user ||--o{ t_road_plan : "assigned to"
    p_user ||--o{ t_visit : "performs"
    
    t_visit ||--o{ t_visit_data : "records"
    t_visit ||--o{ t_visit_product : "uses"
```

---

## 📱 Supporting Modules

### Notifications (`t_notif`)
- 13,346 notification records
- Push notifications to mobile app

### Membership (`m_membership_*`)
- Customer loyalty program
- Level-based benefits

### Ticketing (`t_ticket`, `m_ticket_*`)
- Customer complaint handling
- SLA tracking

### Events (`t_event`, `t_event_*`)
- Special event scheduling
- Event assignments & results

---

## 📈 Data Points Summary

| Category | Available Data Points |
|----------|----------------------|
| **Customer Profile** | name, address, contact, segment, group, GPS, ownership |
| **Contract** | number, period, areas, status |
| **Scheduling** | date, type, technician, status, approval |
| **Execution** | check-in/out time, GPS location, duration, distance |
| **Evidence** | photos, notes, findings |
| **Products** | items used per visit |
| **Billing** | invoice, payment, order |
| **Performance** | targets vs actuals, area coverage |

---

## 🎯 Key Analytics Opportunities

1. **Technician Performance**
   - Visit completion rate
   - Average service time (check_out - check_in)
   - Geographic coverage
   - On-time arrival

2. **Customer Analytics**
   - Contract renewal rate
   - Service frequency
   - Area distribution

3. **Operational Efficiency**
   - Route optimization (GPS data)
   - Resource allocation
   - SLA compliance

4. **Revenue Analytics**
   - Contract value by segment
   - Service revenue by type
   - Payment collection rate
