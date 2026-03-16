# SanoCare Data Platform: End-to-End Architecture

```mermaid
graph TD
    %% Source Systems
    subgraph "Operational Layer (Kelava App)"
        A[Technician App] -->|Check-in/Out, Photos| B(Postgres DB)
        A -->|GPS/Timestamp| B
        C[Ops Manager] -->|Schedule Plan| B
    end

    %% Data Pipeline (The "Agent")
    subgraph "Analytics Layer (KPI Agent)"
        B -->|SSH Tunnel Extract| D[Staging SQLite]
        D -->|Step 2.1 DQ| E{Data Quality Gate}
        E -->|Fail| F[Alert Notification]
        E -->|Pass| G[KPI Engine]
        
        G -->|Calculate| H[Scoring Tables]
        H -->|Mode: STRICT| I[Audit Data]
        H -->|Mode: FAIR| J[Bonus Data]
        
        I & J -->|Step 3.2 Acceptance| K{Iron Gate}
        K -->|Fail| F
        K -->|Pass| L[Versioned Output]
    end

    %% Presentation Layer
    subgraph "Visualization Layer (Enterprise Dashboard)"
        L -->|JSON/CSV Artifacts| M[Data API / Static Hosting]
        M -->|Fetch| N[SanoCare Command Center]
        
        N -->|View: Executive| O[CEO/Owner Dashboard]
        N -->|View: Operations| P[Ops Control Room]
        N -->|View: Personal| Q[Technician Report Card]
    end

    %% Feedback Loop
    P -->|Action Plans| C
    Q -->|Behavior Change| A
```

## Data Flow Description

1.  **Ingest**: Transactional data (Postgres) is extracted daily via secure tunnel.
2.  **Process**: The `KPI Agent` cleans, scores, and audits data using `kpi_config.yaml` rules.
3.  **Validate**: Iron Gate (Step 3.2) ensures no "bad math" reaches the dashboard.
4.  **Publish**: Validated data is published as static artifacts (CSVs, JSONs) in `runs/LATEST/`.
5.  **Visualize**: The **Enterprise Dashboard** reads these artifacts to render professional UIs.
