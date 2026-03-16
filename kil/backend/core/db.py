from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from .config import settings

# 1. SQLAlchemy Engine
# Future: Use AsyncEngine for high-performance async/await support
engine = create_engine(
    settings.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20
)

# 2. Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)


def get_db():
    db = SessionLocal()
    # Auto-apply RLS context if user is authenticated
    try:
        from flask import g

        if hasattr(g, "user") and g.user:
            set_rls_context(db, g.user.id, g.user.role)
    except ImportError:
        pass  # Not running in Flask context or g not available

    try:
        yield db
    finally:
        db.close()


def set_rls_context(session: Session, user_id: str, role: str = "authenticated"):
    """
    CRITICAL: Sets the Postgres Session Variables for RLS.
    This enables valid 'current_setting()' calls in Postgres Policies.
    """
    try:
        # Sanitize inputs (basic UUID check would be good here)
        # We use 'app.current_user_id' to match the migration
        session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))
        session.execute(text(f"SET LOCAL app.current_user_role = '{role}'"))
    except Exception as e:
        # If setting context fails, rollback to prevent data leaks
        session.rollback()
        raise e
