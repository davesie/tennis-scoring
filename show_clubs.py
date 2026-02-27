"""Show all synced clubs."""
import asyncio
from sqlalchemy import select
from app.database import async_session, init_db
from app.models import Club


async def show_all_clubs():
    """Show all clubs in database."""
    await init_db()

    async with async_session() as db:
        result = await db.execute(select(Club).order_by(Club.wtb_id))
        clubs = result.scalars().all()

        print(f"Total clubs in database: {len(clubs)}\n")
        print("="*80)
        print(f"{'WTB ID':<10} {'Name':<40} {'Location':<20}")
        print("="*80)

        for club in clubs:
            print(f"{club.wtb_id:<10} {club.name:<40} {club.location or 'N/A':<20}")

        print("="*80)
        print(f"\nTotal: {len(clubs)} clubs")


if __name__ == "__main__":
    asyncio.run(show_all_clubs())
