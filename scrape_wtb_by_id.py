"""Scrape WTB clubs by brute-forcing ID ranges."""
import httpx
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime
import json
from typing import List, Dict, Optional
import re


BASE_URL = "https://www.wtb-tennis.de"


async def check_club_exists(client: httpx.AsyncClient, wtb_id: str) -> Optional[Dict]:
    """
    Check if a club exists and get its basic info.

    Returns:
        Club dict if exists, None if not found or error
    """
    url = f"{BASE_URL}/spielbetrieb/vereine/verein/v/{wtb_id}.html"

    try:
        response = await client.get(url)

        # Check for error messages
        if "Oops, an error occurred!" in response.text or response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Try to get club name from the page title or h1
        title = soup.find('h1')
        if not title:
            return None

        name = title.text.strip()

        # Try to get location/district from page
        location = None
        district = None

        # Look for address or location info
        # This might need adjustment based on actual HTML structure

        return {
            "wtb_id": wtb_id,
            "name": name,
            "location": location,
            "district": district,
            "url": url
        }

    except Exception as e:
        return None


async def scrape_club_players(client: httpx.AsyncClient, wtb_id: str) -> List[Dict]:
    """
    Scrape ALL Herren players for a specific club.

    Returns:
        List of player dictionaries
    """
    url = f"{BASE_URL}/spielbetrieb/vereine/verein/meldung/v/{wtb_id}.html"
    players = []

    try:
        response = await client.get(url)

        if response.status_code != 200 or "Oops, an error occurred!" in response.text:
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the Herren section by looking for panel-title with text "Herren"
        herren_section = None

        # Find all panel-title elements
        panel_titles = soup.find_all('h3', class_='panel-title')

        for panel_title in panel_titles:
            # Check if this panel is for "Herren"
            link = panel_title.find('a')
            if link and 'Herren' in link.text:
                # Get the href which points to the collapse ID
                href = link.get('href', '')
                # Extract collapse ID (e.g., "#collapse25" -> "collapse25")
                collapse_id = href.lstrip('#')

                # Find the section with this ID
                herren_section = soup.find(id=collapse_id)
                break

        if not herren_section:
            return []

        table = herren_section.find('table')
        if not table:
            return []

        rows = table.find_all('tr')

        # Skip header row, process data rows
        for row in rows[1:]:
            cells = row.find_all('td')

            if len(cells) < 5:
                continue

            # Column structure: [Rang, LK, Name (Jahrgang), ID-Nummer, Nation]
            rang = cells[0].text.strip()
            lk = cells[1].text.strip()
            name_jahrgang = cells[2].text.strip()
            id_nummer = cells[3].text.strip()
            nation = cells[4].text.strip() if len(cells) > 4 else ""

            # Parse name and birth year from "Name (YYYY)" format
            name = name_jahrgang
            birth_year = None

            match = re.match(r'^(.+?)\s*\((\d{4})\)$', name_jahrgang)
            if match:
                name = match.group(1).strip()
                birth_year = int(match.group(2))

            players.append({
                "rang": rang,
                "lk": lk,
                "name": name,
                "birth_year": birth_year,
                "id_nummer": id_nummer,
                "nation": nation,
                "category": "Herren"
            })

    except Exception as e:
        return []

    return players


async def scrape_all_clubs_by_id():
    """Scrape clubs by brute-forcing ID ranges."""
    print("=" * 80)
    print("WTB SCRAPER - BY ID RANGES")
    print("=" * 80)
    print(f"Started at: {datetime.now()}\n")

    # Define ID ranges to try
    id_ranges = [
        (20001, 21130),   # First range
        (25002, 25480),   # Second range
        (90000, 90068),   # Third range
    ]

    all_data = []
    total_checked = 0
    total_found = 0
    total_players = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for start_id, end_id in id_ranges:
            print(f"\n📋 Checking ID range {start_id} to {end_id}...")
            print("-" * 80)

            for wtb_id in range(start_id, end_id + 1):
                wtb_id_str = str(wtb_id)
                total_checked += 1

                # Check if club exists
                club = await check_club_exists(client, wtb_id_str)

                if club:
                    total_found += 1
                    print(f"[{total_checked}] ✓ Found: {club['name']} (ID: {wtb_id_str})", end=" ... ")

                    # Get players
                    players = await scrape_club_players(client, wtb_id_str)

                    if players:
                        total_players += len(players)
                        print(f"✓ {len(players)} Herren players")
                    else:
                        print("○ No Herren players")

                    all_data.append({
                        "club": club,
                        "players": players
                    })

                    # Rate limiting
                    await asyncio.sleep(0.3)
                else:
                    # Club doesn't exist, just show progress occasionally
                    if total_checked % 100 == 0:
                        print(f"[{total_checked}] Checked {total_checked} IDs, found {total_found} clubs so far...")

                    # Shorter rate limiting for non-existent clubs
                    await asyncio.sleep(0.1)

    # Save results
    print(f"\n\n💾 Saving results...")
    print("-" * 80)

    output_file = f"wtb_data_by_id_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    # Summary
    print("\n" + "=" * 80)
    print("SCRAPING COMPLETE!")
    print("=" * 80)
    print(f"Total IDs checked: {total_checked}")
    print(f"Total clubs found: {total_found}")
    print(f"Total Herren players: {total_players}")
    print(f"\nData saved to: {output_file}")
    print(f"Finished at: {datetime.now()}")
    print("=" * 80)

    # Show sample data
    if all_data:
        print("\n📊 SAMPLE DATA (first 5 clubs with players):")
        print("-" * 80)
        sample_count = 0
        for item in all_data:
            club = item['club']
            players = item['players']
            if players and sample_count < 5:
                print(f"\n{club['name']} (ID: {club['wtb_id']})")
                print(f"  Herren Players: {len(players)}")
                print(f"  Sample player: {players[0]}")
                sample_count += 1

    return all_data


if __name__ == "__main__":
    asyncio.run(scrape_all_clubs_by_id())
