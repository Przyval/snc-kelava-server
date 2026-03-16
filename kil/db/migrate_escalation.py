#!/usr/bin/env python3
"""
Migration script for Escalation Policy Layer
Creates technician_issues and issue_actions tables in Kelava database
"""

from kil.db.kelava_db import get_kelava_connection


def run_migration():
    conn = get_kelava_connection()
    cur = conn.cursor()

    # Create technician_issues table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS technician_issues (
            id BIGSERIAL PRIMARY KEY,
            technician_id INTEGER NOT NULL,
            issue_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) DEFAULT 'review',
            status VARCHAR(20) DEFAULT 'open',
            context JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            escalated_at TIMESTAMP WITH TIME ZONE,
            resolved_at TIMESTAMP WITH TIME ZONE,
            resolution_type VARCHAR(30),
            resolution_note TEXT,
            resolved_by INTEGER,
            auto_escalated BOOLEAN DEFAULT FALSE
        );
    """)

    # Create issue_actions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS issue_actions (
            id BIGSERIAL PRIMARY KEY,
            issue_id BIGINT REFERENCES technician_issues(id) ON DELETE CASCADE,
            action_type VARCHAR(30) NOT NULL,
            actor_id INTEGER,
            actor_name VARCHAR(100),
            note TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Create indexes
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_tech_issues_tech ON technician_issues(technician_id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_tech_issues_status ON technician_issues(status);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_tech_issues_severity ON technician_issues(severity);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_actions_issue ON issue_actions(issue_id);"
    )

    conn.commit()
    print("✅ Migration completed: technician_issues and issue_actions tables created")

    cur.close()
    conn.close()


if __name__ == "__main__":
    run_migration()
