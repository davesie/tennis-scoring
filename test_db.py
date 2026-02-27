"""Test database contents."""
import asyncio
import sys
from sqlalchemy import select, func
from app.database import async_session, init_db
from app.models import Club, Player
from app.wtb_scraper import scrape_all_clubs, scrape_club_players


async def check_database():
    """Check what's in the database."""
    # Initialize database
    await init_db()

    async with async_session() as db:
        # Check clubs
        result = await db.execute(select(func.count()).select_from(Club))
        club_count = result.scalar()
        print(f"Total clubs in database: {club_count}")

        # Get first 10 clubs
        result = await db.execute(select(Club).limit(10))
        clubs = result.scalars().all()

        if clubs:
            print("\nFirst 10 clubs:")
            for club in clubs:
                print(f"  - {club.name} (WTB ID: {club.wtb_id}, Location: {club.location})")
        else:
            print("\nNo clubs found in database!")

        # Check players
        result = await db.execute(select(func.count()).select_from(Player))
        player_count = result.scalar()
        print(f"\nTotal players in database: {player_count}")


async def test_sync():
    """Test syncing clubs."""
    print("\n" + "="*60)
    print("TESTING CLUB SYNC")
    print("="*60)

    # Initialize database first
    await init_db()

    print("\nScraping all clubs from WTB website...")
    clubs_data = await scrape_all_clubs()
    print(f"Scraped {len(clubs_data)} clubs")

    if clubs_data:
        print("\nFirst 5 scraped clubs:")
        for club in clubs_data[:5]:
            print(f"  - {club['name']} (WTB ID: {club['wtb_id']}, Location: {club.get('location', 'N/A')})")

    # Now insert into database
    async with async_session() as db:
        synced = 0
        for club_data in clubs_data:
            # Check if club already exists
            result = await db.execute(
                select(Club).where(Club.wtb_id == club_data["wtb_id"])
            )
            existing_club = result.scalar_one_or_none()

            if existing_club:
                # Update existing
                existing_club.name = club_data["name"]
                existing_club.location = club_data.get("location")
                existing_club.district = club_data.get("district")
                existing_club.url = club_data.get("url")
            else:
                # Create new
                new_club = Club(
                    wtb_id=club_data["wtb_id"],
                    name=club_data["name"],
                    location=club_data.get("location"),
                    district=club_data.get("district"),
                    url=club_data.get("url"),
                )
                db.add(new_club)

            synced += 1

        await db.commit()
        print(f"\n✓ Synced {synced} clubs to database")

    # Verify
    print("\nVerifying database after sync...")
    await check_database()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        asyncio.run(test_sync())
    else:
        asyncio.run(check_database())
