"""Import WTB JSON data into database."""
import asyncio
import json
import sys
from datetime import datetime
from sqlalchemy import select
from app.database import async_session, init_db
from app.models import Club, Player


async def import_from_json(json_file: str):
    """Import clubs and players from JSON file into database."""
    print("="*80)
    print("WTB DATA IMPORT TO DATABASE")
    print("="*80)
    print(f"Started at: {datetime.now()}\n")

    # Load JSON data
    print(f"Loading data from {json_file}...")
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"Loaded {len(data)} club entries\n")

    # Deduplicate clubs by wtb_id
    clubs_by_id = {}
    for item in data:
        club = item['club']
        wtb_id = club['wtb_id']

        if wtb_id not in clubs_by_id:
            clubs_by_id[wtb_id] = {
                'club': club,
                'players': item['players']
            }
        else:
            # Merge players (avoid duplicates)
            existing_player_ids = {p['id_nummer'] for p in clubs_by_id[wtb_id]['players']}
            for player in item['players']:
                if player['id_nummer'] not in existing_player_ids:
                    clubs_by_id[wtb_id]['players'].append(player)
                    existing_player_ids.add(player['id_nummer'])

    print(f"After deduplication: {len(clubs_by_id)} unique clubs\n")

    # Initialize database
    await init_db()

    async with async_session() as db:
        clubs_synced = 0
        players_synced = 0

        for wtb_id, item in clubs_by_id.items():
            club_data = item['club']
            players_data = item['players']

            # Check if club exists
            result = await db.execute(
                select(Club).where(Club.wtb_id == wtb_id)
            )
            existing_club = result.scalar_one_or_none()

            if existing_club:
                # Update existing club
                existing_club.name = club_data['name']
                existing_club.location = club_data.get('location')
                existing_club.district = club_data.get('district')
                existing_club.url = club_data.get('url')
                existing_club.last_synced = datetime.utcnow()
                club_id = existing_club.id
            else:
                # Create new club
                new_club = Club(
                    wtb_id=wtb_id,
                    name=club_data['name'],
                    location=club_data.get('location'),
                    district=club_data.get('district'),
                    url=club_data.get('url'),
                    last_synced=datetime.utcnow()
                )
                db.add(new_club)
                await db.flush()  # Get the ID
                club_id = new_club.id

            clubs_synced += 1

            # Delete existing players for this club
            result = await db.execute(
                select(Player).where(Player.club_id == club_id)
            )
            existing_players = result.scalars().all()
            for player in existing_players:
                await db.delete(player)

            # Add new players
            for player_data in players_data:
                new_player = Player(
                    name=player_data['name'],
                    birth_year=player_data.get('birth_year'),
                    category=player_data['category'],
                    wtb_id_nummer=player_data.get('id_nummer'),
                    club_id=club_id
                )
                db.add(new_player)
                players_synced += 1

            if clubs_synced % 50 == 0:
                print(f"Progress: {clubs_synced}/{len(clubs_by_id)} clubs, {players_synced} players...")

        await db.commit()

    print("\n" + "="*80)
    print("IMPORT COMPLETE!")
    print("="*80)
    print(f"Clubs imported: {clubs_synced}")
    print(f"Players imported: {players_synced}")
    print(f"Finished at: {datetime.now()}")
    print("="*80)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_wtb_to_db.py <json_file>")
        print("Example: python import_wtb_to_db.py wtb_data_20260216_172541.json")
        sys.exit(1)

    json_file = sys.argv[1]
    asyncio.run(import_from_json(json_file))
