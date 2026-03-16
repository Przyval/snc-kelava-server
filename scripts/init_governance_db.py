from kil.db.kelava_db import get_kelava_connection


def execute_ddl(sql, params=None):
    conn = get_kelava_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            # No fetchall for DDL
    finally:
        conn.close()


def init_governance_tables():
    print("Initializing Governance Tables...")

    # 1. operational_governance
    # Stores the "human state" of an account
    # Removed REFERENCES m_customer(id) and REFERENCES p_user(id) due to permissions
    sql_gov = """
    CREATE TABLE IF NOT EXISTS operational_governance (
        id SERIAL PRIMARY KEY,
        id_customer INT,
        review_status VARCHAR(50) DEFAULT 'OPEN',     
        escalation_level VARCHAR(50) DEFAULT 'WATCH', 
        last_review_at TIMESTAMP,
        last_reviewer_id INT,
        review_note TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT unique_customer_governance UNIQUE (id_customer) 
    );
    """
    execute_ddl(sql_gov)
    print("Created operational_governance table.")

    # 2. governance_audit_log
    # Immutable record of state changes
    sql_audit = """
    CREATE TABLE IF NOT EXISTS governance_audit_log (
        id SERIAL PRIMARY KEY,
        id_customer INT,
        action VARCHAR(50),           
        previous_state JSONB,
        new_state JSONB,
        actor_id INT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    execute_ddl(sql_audit)
    print("Created governance_audit_log table.")

    # 3. Add index for audit log performance
    execute_ddl(
        "CREATE INDEX IF NOT EXISTS idx_audit_customer ON governance_audit_log(id_customer);"
    )
    print("Created index on governance_audit_log.")

    print("Governance Tables Initialization Completed.")


if __name__ == "__main__":
    init_governance_tables()
