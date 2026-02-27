"""Complete WTB scraper for all clubs and Herren players."""
import httpx
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime
import json
from typing import List, Dict
import re


BASE_URL = "https://www.wtb-tennis.de"


async def scrape_all_clubs_from_all_pages() -> List[Dict]:
    """
    Scrape ALL clubs from all 13 pages of the WTB website.

    Returns:
        List of club dictionaries with wtb_id, name, location, district, url
    """
    all_clubs = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Scrape all 13 pages
        for page in range(1, 14):  # Pages 1 to 13
            print(f"Scraping page {page}/13...")

            if page == 1:
                url = f"{BASE_URL}/spielbetrieb/vereine/"
            else:
                url = f"{BASE_URL}/spielbetrieb/vereine/?page={page}"

            try:
                response = await client.get(url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                # Parse clubs from this page
                clubs = _parse_clubs_page(soup)
                all_clubs.extend(clubs)
                print(f"  Found {len(clubs)} clubs on page {page}")

                # Rate limiting
                if page < 13:
                    await asyncio.sleep(0.5)

            except Exception as e:
                print(f"  Error scraping page {page}: {e}")
                continue

    print(f"\nTotal clubs scraped: {len(all_clubs)}")
    return all_clubs


def _parse_clubs_page(soup: BeautifulSoup) -> List[Dict]:
    """Parse a single page of clubs - improved parsing."""
    clubs = []

    # Find all club links - they follow pattern /spielbetrieb/vereine/verein/v/{id}.html
    links = soup.select('a[href*="/spielbetrieb/vereine/verein/v/"]')

    for link in links:
        try:
            href = link.get('href', '')

            # Extract club ID from URL
            match = re.search(r'/v/(\d+)', href)
            if not match:
                continue

            wtb_id = match.group(1)

            # Get club name from link text
            name = link.text.strip()

            # Remove the ID number if it's in the name (e.g., "TC Abstatt 20001" -> "TC Abstatt")
            name = re.sub(r'\s+\d{5,}$', '', name).strip()

            if not name:
                continue

            # Try to get location and district from surrounding elements
            # The structure is typically:
            # <a>Club Name</a> ID
            # City
            # District
            parent = link.parent
            location = None
            district = None

            if parent:
                # Get all text after the link
                parent_text = parent.get_text(separator='|', strip=True)
                parts = [p.strip() for p in parent_text.split('|') if p.strip()]

                # Try to extract location and district
                # Typically: [Name, ID, Location, District]
                if len(parts) >= 3:
                    location = parts[2] if parts[2] != wtb_id else None
                if len(parts) >= 4:
                    district = parts[3]

            clubs.append({
                "wtb_id": wtb_id,
                "name": name,
                "location": location,
                "district": district,
                "url": BASE_URL + href if not href.startswith('http') else href
            })

        except Exception as e:
            print(f"    Error parsing club link: {e}")
            continue

    return clubs


async def scrape_club_players_full(wtb_id: str) -> List[Dict]:
    """
    Scrape ALL player information for a specific club (Herren only).

    Gets: Rang, LK, Name (Jahrgang), ID-Nummer, Nation

    Args:
        wtb_id: Club WTB ID (e.g., "20004")

    Returns:
        List of player dictionaries with all fields
    """
    url = f"{BASE_URL}/spielbetrieb/vereine/verein/meldung/v/{wtb_id}.html"
    players = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
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

        except httpx.HTTPError as e:
            # Some clubs may not have player pages
            return []
        except Exception as e:
            print(f"    Error scraping players for club {wtb_id}: {e}")
            return []

    return players


async def scrape_all_data():
    """Scrape all clubs and all their players."""
    print("="*80)
    print("WTB COMPLETE SCRAPER")
    print("="*80)
    print(f"Started at: {datetime.now()}\n")

    # Step 1: Scrape all clubs from all pages
    print("\n📋 STEP 1: Scraping all clubs from all 13 pages...")
    print("-"*80)
    clubs = await scrape_all_clubs_from_all_pages()

    if not clubs:
        print("❌ No clubs found!")
        return

    print(f"\n✅ Successfully scraped {len(clubs)} clubs")
    print("\nFirst 5 clubs:")
    for club in clubs[:5]:
        print(f"  • {club['name']} (ID: {club['wtb_id']}, Location: {club.get('location', 'N/A')})")

    # Step 2: Scrape players for all clubs
    print(f"\n\n👥 STEP 2: Scraping Herren players for all {len(clubs)} clubs...")
    print("-"*80)
    print("This will take a while (approx. 3-5 minutes with rate limiting)...\n")

    all_data = []
    clubs_with_players = 0
    total_players = 0

    for i, club in enumerate(clubs, 1):
        print(f"[{i}/{len(clubs)}] {club['name']} (ID: {club['wtb_id']})...", end=" ")

        players = await scrape_club_players_full(club['wtb_id'])

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

        # Rate limiting - be nice to the server
        if i < len(clubs):
            await asyncio.sleep(0.5)

    # Step 3: Save results
    print(f"\n\n💾 STEP 3: Saving results...")
    print("-"*80)

    output_file = f"wtb_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    # Summary
    print("\n" + "="*80)
    print("SCRAPING COMPLETE!")
    print("="*80)
    print(f"Total clubs scraped: {len(clubs)}")
    print(f"Clubs with Herren players: {clubs_with_players}")
    print(f"Total Herren players: {total_players}")
    print(f"\nData saved to: {output_file}")
    print(f"Finished at: {datetime.now()}")
    print("="*80)

    # Show sample data
    print("\n📊 SAMPLE DATA:")
    print("-"*80)
    for item in all_data[:3]:
        club = item['club']
        players = item['players']
        print(f"\n{club['name']} (ID: {club['wtb_id']})")
        print(f"  Location: {club.get('location', 'N/A')}")
        print(f"  District: {club.get('district', 'N/A')}")
        print(f"  Herren Players: {len(players)}")
        if players:
            print(f"  Sample player: {players[0]}")

    return all_data


if __name__ == "__main__":
    asyncio.run(scrape_all_data())
