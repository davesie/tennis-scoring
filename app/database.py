from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tennis.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Exported session factory for use outside FastAPI dependency injection
async_session_maker = async_session


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migration: add ranking column if it doesn't exist yet
        try:
            await conn.execute(text("ALTER TABLE players ADD COLUMN ranking INTEGER"))
        except Exception:
            pass  # Column already exists
