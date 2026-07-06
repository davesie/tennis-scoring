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
            "ALTER TABLE matches ADD COLUMN point_log JSON",
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
    """Sync the superadmin account with ADMIN_EMAIL / ADMIN_PASSWORD on every boot.

    The env vars are the source of truth: the account is created if missing,
    promoted if it exists as a normal user, and its password is reset to the
    env value — so updating the vars (e.g. in Coolify) and redeploying always
    yields a working admin login. Also backfills ownerless match days.
    """
    import logging
    from .auth import hash_password
    from .models import generate_uuid

    logger = logging.getLogger(__name__)

    admin_email = os.getenv("ADMIN_EMAIL", "").strip()
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    if not admin_password:
        logger.warning(
            "No ADMIN_PASSWORD set — skipping admin bootstrap. "
            "Set ADMIN_EMAIL and ADMIN_PASSWORD (e.g. in Coolify env vars) "
            "to get a superadmin login; normal users can register at /register."
        )
        return

    if not admin_email:
        admin_email = "admin@localhost"
        logger.warning("ADMIN_EMAIL not set — using default '%s'", admin_email)

    pw_hash = hash_password(admin_password)

    async with async_session() as db:
        result = await db.execute(
            text("SELECT id, is_superadmin FROM users WHERE email = :email"),
            {"email": admin_email},
        )
        row = result.first()

        if row:
            user_id = row[0]
            await db.execute(text(
                "UPDATE users SET password_hash = :pw, is_superadmin = 1 WHERE id = :id"
            ), {"pw": pw_hash, "id": user_id})
            action = "updated (password synced from env)" if row[1] else "promoted from normal user"
        else:
            user_id = generate_uuid()
            await db.execute(text(
                "INSERT INTO users (id, email, password_hash, display_name, is_superadmin) "
                "VALUES (:id, :email, :pw, :name, 1)"
            ), {"id": user_id, "email": admin_email, "pw": pw_hash, "name": "Admin"})
            action = "created"

        await db.execute(text(
            "UPDATE match_days SET owner_id = :uid WHERE owner_id IS NULL"
        ), {"uid": user_id})

        await db.execute(text(
            "UPDATE admin_sessions SET user_id = :uid WHERE user_id IS NULL"
        ), {"uid": user_id})

        await db.commit()
        logger.info("Superadmin %s: %s (login at /admin/login)", action, admin_email)
