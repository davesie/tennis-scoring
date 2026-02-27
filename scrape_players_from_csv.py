"""Scrape Herren players for all clubs listed in data/wtb-clubs-ids.csv."""
import httpx
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime
import json
import csv
import re
from typing import List, Dict


BASE_URL = "https://www.wtb-tennis.de"
CSV_FILE = "data/wtb-clubs-ids.csv"


def load_clubs_from_csv() -> List[Dict]:
    """Load club list from CSV file."""
    clubs = []
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clubs.append({
                "wtb_id": row["ID"].strip(),
                "name": row["Verein"].strip(),
                "location": row["Ort"].strip() or None,
                "district": row["Bezirk"].strip() or None,
            })
    return clubs


async def scrape_herren_players(client: httpx.AsyncClient, wtb_id: str) -> List[Dict]:
    """
    Scrape Herren players from a club's meldung page.
    Dynamically finds the Herren section by panel-title text.
    """
    url = f"{BASE_URL}/spielbetrieb/vereine/verein/meldung/v/{wtb_id}.html"

    try:
        response = await client.get(url)

        if response.status_code != 200:
            return []

        # Skip pages with error messages
        if "Oops, an error occurred!" in response.text:
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the Herren section by looking for panel-title containing "Herren"
        herren_section = None
        panel_titles = soup.find_all('h3', class_='panel-title')

        for panel_title in panel_titles:
            link = panel_title.find('a')
            if link and 'Herren' in link.text:
                href = link.get('href', '')
                collapse_id = href.lstrip('#')
                herren_section = soup.find(id=collapse_id)
                break

        if not herren_section:
            return []

        table = herren_section.find('table')
        if not table:
            return []

        players = []
        rows = table.find_all('tr')

        # Skip header row
        for row in rows[1:]:
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            rang = cells[0].text.strip()
            lk = cells[1].text.strip()
            name_jahrgang = cells[2].text.strip()
            id_nummer = cells[3].text.strip()
            nation = cells[4].text.strip() if len(cells) > 4 else ""

            # Parse "Name (YYYY)" format
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

        return players

    except Exception:
        return []


async def scrape_all():
    """Scrape Herren players for all clubs from CSV."""
    print("=" * 80)
    print("WTB PLAYER SCRAPER - Reading from data/wtb-clubs-ids.csv")
    print("=" * 80)
    print(f"Started at: {datetime.now()}\n")

    clubs = load_clubs_from_csv()
    print(f"Loaded {len(clubs)} clubs from CSV\n")

    all_data = []
    clubs_with_players = 0
    total_players = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, club in enumerate(clubs, 1):
            print(f"[{i}/{len(clubs)}] {club['name']} (ID: {club['wtb_id']})...", end=" ", flush=True)

            players = await scrape_herren_players(client, club['wtb_id'])

            if players:
                clubs_with_players += 1
                total_players += len(players)
                print(f"✓ {len(players)} Herren players")
            else:
                print("○ No Herren players")

            all_data.append({
                "club": club,
                "players": players
            })

            # Rate limiting - be respectful to the server
            if i < len(clubs):
                await asyncio.sleep(0.3)

    # Save results
    output_file = f"wtb_players_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("SCRAPING COMPLETE!")
    print("=" * 80)
    print(f"Total clubs:              {len(clubs)}")
    print(f"Clubs with Herren players: {clubs_with_players}")
    print(f"Total Herren players:      {total_players}")
    print(f"Output file:               {output_file}")
    print(f"Finished at: {datetime.now()}")
    print("=" * 80)

    return output_file


if __name__ == "__main__":
    asyncio.run(scrape_all())
