from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tennis.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async_session_maker = async_session


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrations: add columns if they don't exist yet
        try:
            await conn.execute(text("ALTER TABLE players ADD COLUMN ranking INTEGER"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE players ADD COLUMN is_captain BOOLEAN DEFAULT 0"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE players ADD COLUMN lk TEXT"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE match_days ADD COLUMN club_a_id TEXT REFERENCES clubs(id)"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE match_days ADD COLUMN club_b_id TEXT REFERENCES clubs(id)"))
        except Exception:
            pass
        for col_def in [
            "ALTER TABLE match_days ADD COLUMN scheduled_date DATETIME",
            "ALTER TABLE match_days ADD COLUMN venue TEXT",
            "ALTER TABLE match_days ADD COLUMN wtb_meeting_id TEXT",
            "ALTER TABLE match_days ADD COLUMN wtb_team_id TEXT",
            "ALTER TABLE match_days ADD COLUMN wtb_club_id TEXT",
            "ALTER TABLE match_days ADD COLUMN category TEXT",
            "ALTER TABLE match_days ADD COLUMN owner_id TEXT REFERENCES users(id)",
            "ALTER TABLE match_days ADD COLUMN is_public BOOLEAN DEFAULT 1",
            "ALTER TABLE admin_sessions ADD COLUMN user_id TEXT REFERENCES users(id)",
        ]:
            try:
                await conn.execute(text(col_def))
            except Exception:
                pass
        try:
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_match_days_wtb_meeting_id ON match_days (wtb_meeting_id)"
            ))
        except Exception:
            pass


async def ensure_superadmin():
    """Create superadmin user from env vars if no superadmin exists yet.
    Also backfill ownerless match days to the superadmin."""
    from .models import User, MatchDay
    from .auth import hash_password

    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_password:
        return

    async with async_session() as db:
        result = await db.execute(
            text("SELECT id FROM users WHERE is_superadmin = 1 LIMIT 1")
        )
        existing = result.first()
        if existing:
            return

        admin_email = os.getenv("ADMIN_EMAIL", "admin@localhost")
        from .models import generate_uuid
        user_id = generate_uuid()
        pw_hash = hash_password(admin_password)

        await db.execute(text(
            "INSERT INTO users (id, email, password_hash, display_name, is_superadmin) "
            "VALUES (:id, :email, :pw, :name, 1)"
        ), {"id": user_id, "email": admin_email, "pw": pw_hash, "name": "Admin"})

        await db.execute(text(
            "UPDATE match_days SET owner_id = :uid WHERE owner_id IS NULL"
        ), {"uid": user_id})

        await db.execute(text(
            "UPDATE admin_sessions SET user_id = :uid WHERE user_id IS NULL"
        ), {"uid": user_id})

        await db.commit()
