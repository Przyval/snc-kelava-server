# 📊 Architecture Diagrams

Kumpulan diagram visual untuk arsitektur Safe & Care Operational Intelligence.

---

## 1. High-Level Architecture

```mermaid
flowchart TB
    subgraph Field["📱 Layer 1: Field Operations"]
        KELAVA[("🔧 Kelava<br/>(Work Orders, Visits, Evidence)")]
        TRACCAR[("📍 Traccar<br/>(GPS Tracking)")]
        CALCOM[("📅 Cal.com<br/>(Booking)")]
    end
    
    subgraph Brain["🧠 Layer 2: Event + Decision Layer"]
        direction TB
        ETL["⚙️ ETL Pipeline"]
        KPI["📊 KPI Engine"]
        ALERT["🚨 Alert Engine"]
        MART[("💾 KPI Mart<br/>PostgreSQL")]
    end
    
    subgraph UI["🖥️ Layer 3: Ops Dashboard"]
        TOWER["🗼 Control Tower"]
        LEADER["🏆 Leaderboard"]
        HEALTH["❤️ Customer Health"]
        ALERTS["⚠️ Alert Center"]
    end
    
    subgraph Action["⚡ Layer 4: Write-back"]
        API["🔌 Action API"]
        NOTIFY["📱 Notifications"]
    end
    
    KELAVA --> ETL
    TRACCAR -.-> ETL
    CALCOM -.-> ETL
    
    ETL --> KPI
    KPI --> MART
    KPI --> ALERT
    
    MART --> TOWER
    MART --> LEADER
    MART --> HEALTH
    ALERT --> ALERTS
    
    TOWER --> API
    ALERTS --> NOTIFY
    API -.-> KELAVA
    
    style KELAVA fill:#4CAF50,color:#fff
    style TRACCAR fill:#9E9E9E,color:#fff
    style CALCOM fill:#9E9E9E,color:#fff
    style MART fill:#2196F3,color:#fff
    style Brain fill:#FFF3E0
```

---

## 2. Data Flow Detail

```mermaid
flowchart LR
    subgraph Sources["Data Sources"]
        K[(Kelava DB)]
        T[(Traccar DB)]
    end
    
    subgraph ETL["ETL Process"]
        CDC["Change Data<br/>Capture"]
        TRANSFORM["Transform &<br/>Validate"]
        LOAD["Load to<br/>KPI Mart"]
    end
    
    subgraph Mart["KPI Mart"]
        FDV["fact_daily_visit"]
        FTP["fact_technician_perf"]
        FCH["fact_customer_health"]
        FDE["fact_dispatch_eff"]
    end
    
    subgraph Serve["Serving Layer"]
        API["REST API"]
        WS["WebSocket"]
    end
    
    K --> CDC
    T -.-> CDC
    CDC --> TRANSFORM
    TRANSFORM --> LOAD
    LOAD --> FDV & FTP & FCH & FDE
    FDV & FTP & FCH & FDE --> API
    FDV --> WS
    
    style K fill:#4CAF50
    style T fill:#9E9E9E
    style Mart fill:#E3F2FD
```

---

## 3. Component Placement per Phase

```mermaid
gantt
    title Implementation Phases
    dateFormat  YYYY-MM
    section Phase 1
    Data Pipeline     :done, p1a, 2026-02, 2026-02
    KPI Mart          :active, p1b, 2026-02, 2026-03
    Dashboard MVP     :p1c, 2026-03, 2026-03
    section Phase 2
    Traccar Setup     :p2a, 2026-04, 2026-04
    Live Tracking     :p2b, 2026-04, 2026-05
    Control Tower     :p2c, 2026-05, 2026-05
    section Phase 3a
    Advanced Analytics:p3a, 2026-06, 2026-06
    Dashboard Polish  :p3b, 2026-06, 2026-07
    section Phase 3b
    Write-back API    :p4a, 2026-08, 2026-09
    Platform Eval     :p4b, 2026-09, 2026-10
```

---

## 4. Decision Tree: Platform Choice

```mermaid
flowchart TD
    START((Start)) --> Q1{Kelava API<br/>available?}
    
    Q1 -->|Yes| Q2{Write-back<br/>needed?}
    Q1 -->|No| Q3{Can live with<br/>read-only?}
    
    Q2 -->|Yes| STAY1["✅ Stay Kelava<br/>+ Decision Layer<br/>+ Write-back API"]
    Q2 -->|No| STAY2["✅ Stay Kelava<br/>+ Decision Layer<br/>(read-only)"]
    
    Q3 -->|Yes| STAY2
    Q3 -->|No| Q4{ERPNext<br/>ecosystem?}
    
    Q4 -->|Yes| FRAPPE["🔄 Migrate to<br/>ERPNext/Frappe"]
    Q4 -->|No| ODOO["🔄 Evaluate<br/>Odoo + OCA"]
    
    style STAY1 fill:#4CAF50,color:#fff
    style STAY2 fill:#4CAF50,color:#fff
    style FRAPPE fill:#FF9800,color:#fff
    style ODOO fill:#FF9800,color:#fff
```

---

## 5. Dashboard Module Map

```mermaid
mindmap
    root((Ops Dashboard))
        Control Tower
            Live Map
            Job Queue
            Technician Status
            Re-assignment
        Leaderboard
            Daily Rankings
            Weekly Trends
            Segmented View
            Incentive Tracker
        Customer Health
            Churn Risk
            Service History
            Contract Status
            Feedback Score
        Alert Center
            SLA Breaches
            Anomalies
            Escalations
            Resolution Log
        Analytics
            Trend Charts
            Forecasting
            What-if Scenarios
            Export Reports
```

---

## 6. Integration Architecture

```mermaid
flowchart TB
    subgraph External["External Systems"]
        WA["📱 WhatsApp API"]
        EMAIL["📧 Email SMTP"]
        MAPS["🗺️ Google Maps"]
    end
    
    subgraph Core["Core Platform"]
        subgraph Kelava["Kelava System"]
            KDB[(Database)]
            KAPI["API"]
        end
        
        subgraph Intelligence["Intel Layer"]
            PROC["Processing"]
            STORE[(KPI Store)]
            DASH["Dashboard"]
        end
    end
    
    subgraph Future["Future Add-ons"]
        TRACCAR2["Traccar"]
        CALCOM2["Cal.com"]
        ERP["ERPNext"]
    end
    
    KDB --> PROC
    PROC --> STORE
    STORE --> DASH
    
    DASH --> WA
    DASH --> EMAIL
    DASH --> MAPS
    
    TRACCAR2 -.-> PROC
    CALCOM2 -.-> PROC
    
    KAPI <-.-> DASH
    ERP <-.-> PROC
    
    style Kelava fill:#E8F5E9
    style Intelligence fill:#E3F2FD
    style Future fill:#FFF3E0
```

---

## 7. Alerting Flow

```mermaid
sequenceDiagram
    participant K as Kelava DB
    participant E as Event Processor
    participant A as Alert Engine
    participant D as Dashboard
    participant N as Notification
    
    K->>E: New visit data
    E->>E: Calculate KPIs
    E->>A: Check thresholds
    
    alt SLA Breach Detected
        A->>D: Push alert to UI
        A->>N: Send notification
        N->>N: WhatsApp/Email
    else Normal Operation
        A->>D: Update metrics only
    end
    
    D->>D: Refresh display
```

---

## Usage Notes

### Rendering Diagrams

Diagram-diagram di atas menggunakan **Mermaid** syntax. Untuk melihatnya:

1. **GitHub/GitLab** — Otomatis di-render
2. **VS Code** — Install extension "Markdown Preview Mermaid Support"
3. **Online** — Paste ke [mermaid.live](https://mermaid.live)

### Export Options

Untuk export ke PNG/SVG:
1. Buka [mermaid.live](https://mermaid.live)
2. Paste kode diagram
3. Klik Download PNG/SVG

---

*Last Updated: 2026-02-05*
