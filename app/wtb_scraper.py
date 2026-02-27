"""WTB website scraper for clubs and players."""

import httpx
from bs4 import BeautifulSoup
import re
from typing import List, Dict, Optional
import asyncio
from datetime import datetime

BASE_URL = "https://www.wtb-tennis.de"


async def scrape_all_clubs() -> List[Dict]:
    """
    Scrape all clubs from WTB website (all pages).

    Returns:
        List of club dictionaries with wtb_id, name, location, district, url
    """
    clubs = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # First, get the first page to determine total pages
        first_page_url = f"{BASE_URL}/spielbetrieb/vereine/"

        try:
            response = await client.get(first_page_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Parse first page
            clubs.extend(_parse_clubs_page(soup))

            # Find pagination to get total pages
            total_pages = _get_total_pages(soup)

            # Scrape remaining pages
            for page in range(2, total_pages + 1):
                await asyncio.sleep(0.5)  # Rate limiting

                page_url = f"{BASE_URL}/spielbetrieb/vereine/?page={page}"
                response = await client.get(page_url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                clubs.extend(_parse_clubs_page(soup))

        except Exception as e:
            print(f"Error scraping clubs: {e}")
            raise

    return clubs


def _parse_clubs_page(soup: BeautifulSoup) -> List[Dict]:
    """Parse a single page of clubs."""
    clubs = []

    # Find all club links
    links = soup.select('a[href*="/spielbetrieb/vereine/verein/v/"]')

    for link in links:
        try:
            href = link.get('href', '')
            wtb_id = _extract_id_from_url(href)

            if not wtb_id:
                continue

            name = link.text.strip()

            # Try to get location and district from nearby text
            parent = link.parent
            if parent:
                text_content = parent.get_text(separator='|', strip=True)
                parts = text_content.split('|')

                location = parts[1] if len(parts) > 1 else None
                district = parts[2] if len(parts) > 2 else None
            else:
                location = None
                district = None

            clubs.append({
                "wtb_id": wtb_id,
                "name": name,
                "location": location,
                "district": district,
                "url": BASE_URL + href
            })

        except Exception as e:
            print(f"Error parsing club link: {e}")
            continue

    return clubs


def _get_total_pages(soup: BeautifulSoup) -> int:
    """Extract total number of pages from pagination."""
    # Look for pagination links
    pagination = soup.find_all('a', href=re.compile(r'\?page=\d+'))

    if not pagination:
        return 1

    # Extract page numbers
    page_numbers = []
    for link in pagination:
        match = re.search(r'page=(\d+)', link.get('href', ''))
        if match:
            page_numbers.append(int(match.group(1)))

    return max(page_numbers) if page_numbers else 1


def _extract_id_from_url(url: str) -> Optional[str]:
    """Extract WTB ID from club URL."""
    match = re.search(r'/v/(\d+)', url)
    return match.group(1) if match else None


async def scrape_club_players(wtb_id: str, category: str = "Herren") -> List[Dict]:
    """
    Scrape all players for a specific club in the Herren category.

    Args:
        wtb_id: Club WTB ID (e.g., "20004")
        category: Player category (default: "Herren")

    Returns:
        List of player dictionaries with name, birth_year, category, wtb_id_nummer
    """
    url = f"{BASE_URL}/spielbetrieb/vereine/verein/meldung/v/{wtb_id}.html"
    players = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Map of collapse IDs to categories
            # We only care about "Herren" for now
            category_map = {
                "collapse13": "Herren",
                "collapse14": "Herren 30",
                "collapse15": "Herren 40",
                "collapse16": "Herren 50",
            }

            # Find the Herren section
            for collapse_id, cat_name in category_map.items():
                if cat_name != "Herren":
                    continue  # Only scrape Herren for now

                section = soup.find(id=collapse_id)
                if not section:
                    continue

                table = section.find('table')
                if not table:
                    continue

                rows = table.find_all('tr')

                # Skip header row
                for row in rows[1:]:
                    cells = row.find_all('td')

                    if len(cells) < 4:
                        continue

                    # Cell structure: [Rang, LK, Name (Birth Year), ID-Nummer, Nation]
                    name_cell = cells[2].text.strip()
                    wtb_id_cell = cells[3].text.strip() if len(cells) > 3 else ""

                    # Parse name and birth year
                    match = re.match(r'^(.+?)\s*\((\d{4})\)$', name_cell)

                    if match:
                        player_name = match.group(1).strip()
                        birth_year = int(match.group(2))

                        players.append({
                            "name": player_name,
                            "birth_year": birth_year,
                            "category": cat_name,
                            "wtb_id_nummer": wtb_id_cell
                        })

        except httpx.HTTPError as e:
            print(f"HTTP error scraping players for club {wtb_id}: {e}")
            # Don't raise - some clubs may not have player pages
            return []
        except Exception as e:
            print(f"Error scraping players for club {wtb_id}: {e}")
            return []

    return players


async def test_scraper():
    """Test the scraper with a single club."""
    print("Testing WTB scraper...")

    # Test scraping a single club's players
    print("\n1. Testing player scraping for TA TSV Crailsheim (20004)...")
    players = await scrape_club_players("20004")
    print(f"Found {len(players)} Herren players")
    if players:
        print(f"Sample: {players[0]}")

    # Test scraping first page of clubs
    print("\n2. Testing club scraping (first page)...")
    clubs = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/spielbetrieb/vereine/")
        soup = BeautifulSoup(response.text, 'html.parser')
        clubs = _parse_clubs_page(soup)

    print(f"Found {len(clubs)} clubs on first page")
    if clubs:
        print(f"Sample: {clubs[0]}")

    print("\nTest complete!")


if __name__ == "__main__":
    # Run test
    asyncio.run(test_scraper())
