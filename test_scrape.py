"""Quick test of WTB scraping."""
import httpx
from bs4 import BeautifulSoup
import asyncio
import re
import sys


async def test_single_page():
    """Test scraping a single page."""
    url = "https://www.wtb-tennis.de/spielbetrieb/vereine/"

    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"Fetching: {url}", flush=True)
        response = await client.get(url)
        print(f"Status: {response.status_code}", flush=True)

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find all club links
        links = soup.select('a[href*="/spielbetrieb/vereine/verein/v/"]')
        print(f"Found {len(links)} club links", flush=True)

        clubs = []
        for link in links[:10]:  # First 10 only
            href = link.get('href', '')
            match = re.search(r'/v/(\d+)', href)
            if match:
                wtb_id = match.group(1)
                name = link.text.strip()
                name = re.sub(r'\s+\d{5,}$', '', name).strip()

                clubs.append({
                    "wtb_id": wtb_id,
                    "name": name,
                    "href": href
                })

        print("\nFirst 10 clubs:", flush=True)
        for club in clubs:
            print(f"  {club['wtb_id']}: {club['name']}", flush=True)

        return clubs


async def test_players(wtb_id="20004"):
    """Test scraping players for one club."""
    url = f"https://www.wtb-tennis.de/spielbetrieb/vereine/verein/meldung/v/{wtb_id}.html"

    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"\nFetching players for club {wtb_id}...", flush=True)
        response = await client.get(url)
        print(f"Status: {response.status_code}", flush=True)

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find Herren section
        herren_section = soup.find(id='collapse13')

        if not herren_section:
            print("No Herren section found", flush=True)
            return []

        table = herren_section.find('table')
        if not table:
            print("No table found", flush=True)
            return []

        rows = table.find_all('tr')
        print(f"Found {len(rows)} rows (including header)", flush=True)

        players = []
        for row in rows[1:10]:  # Skip header, get first 9 players
            cells = row.find_all('td')
            if len(cells) >= 5:
                rang = cells[0].text.strip()
                lk = cells[1].text.strip()
                name_jahrgang = cells[2].text.strip()
                id_nummer = cells[3].text.strip()
                nation = cells[4].text.strip()

                print(f"  {rang} | {lk} | {name_jahrgang} | {id_nummer} | {nation}", flush=True)

                players.append({
                    "rang": rang,
                    "lk": lk,
                    "name": name_jahrgang,
                    "id_nummer": id_nummer,
                    "nation": nation
                })

        print(f"\nTotal players found: {len(players)}", flush=True)
        return players


if __name__ == "__main__":
    print("=== WTB Scraper Test ===\n", flush=True)

    print("TEST 1: Scraping clubs from first page", flush=True)
    clubs = asyncio.run(test_single_page())

    print("\n\nTEST 2: Scraping players for TA TSV Crailsheim", flush=True)
    players = asyncio.run(test_players("20004"))

    print("\n=== Test Complete ===", flush=True)
