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
            pass  # Column already exists
        try:
            await conn.execute(text("ALTER TABLE players ADD COLUMN is_captain BOOLEAN DEFAULT 0"))
        except Exception:
            pass  # Column already exists
        try:
            await conn.execute(text("ALTER TABLE players ADD COLUMN lk TEXT"))
        except Exception:
            pass  # Column already exists
        # MatchDay WTB fixture import fields
        for col_def in [
            "ALTER TABLE match_days ADD COLUMN scheduled_date DATETIME",
            "ALTER TABLE match_days ADD COLUMN venue TEXT",
            "ALTER TABLE match_days ADD COLUMN wtb_meeting_id TEXT UNIQUE",
            "ALTER TABLE match_days ADD COLUMN wtb_team_id TEXT",
            "ALTER TABLE match_days ADD COLUMN wtb_club_id TEXT",
        ]:
            try:
                await conn.execute(text(col_def))
            except Exception:
                pass
