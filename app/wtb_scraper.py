"""WTB website scraper for clubs and players."""

import httpx
from bs4 import BeautifulSoup
import re
from typing import List, Dict, Optional
import asyncio
from datetime import datetime

BASE_URL = "https://www.wtb-tennis.de"
CLUBS_URL = "https://www.wtb-tennis.de/spielbetrieb/vereine.html"
CLUBS_PARAMS = {
    "tx_nuportalrs_clubs[controller]": "nuCore",
    "cHash": "9f1ab9c76668b46aee3522471919da87",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


async def scrape_all_clubs() -> List[Dict]:
    """
    Scrape all clubs from WTB website (all pages).

    Returns:
        List of club dictionaries with wtb_id, name, location, district, url
    """
    clubs = []

    seen_ids = set()

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        try:
            # GET first page
            response = await client.get(CLUBS_URL, params=CLUBS_PARAMS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # Parse first page
            page_clubs = _parse_clubs_page(soup)
            for c in page_clubs:
                seen_ids.add(c["wtb_id"])
            clubs.extend(page_clubs)

            # Determine total pages from pagination
            total_pages = _get_total_pages(soup)

            # Extract TYPO3 form tokens from first page (reused for all subsequent POSTs)
            form_data = _extract_form_data(soup)

            # Fetch remaining pages
            for page in range(2, total_pages + 1):
                await asyncio.sleep(1.0)  # Be polite

                offset = (page - 1) * 100
                post_data = {
                    **form_data,
                    "tx_nuportalrs_clubs[clubsFilter][firstResult]": str(offset),
                }
                response = await client.post(
                    CLUBS_URL, params=CLUBS_PARAMS, data=post_data
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "lxml")

                page_clubs = _parse_clubs_page(soup)
                # Deduplicate: stop if all clubs on this page were already seen
                new_clubs = [c for c in page_clubs if c["wtb_id"] not in seen_ids]
                if not new_clubs:
                    break
                for c in new_clubs:
                    seen_ids.add(c["wtb_id"])
                clubs.extend(new_clubs)

        except Exception as e:
            print(f"Error scraping clubs: {e}")
            raise

    return clubs


def _extract_form_data(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract all form inputs from clubsFilterForm (TYPO3 security tokens)."""
    form = soup.find("form", id="clubsFilterForm")
    if not form:
        return {}
    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name:
            data[name] = inp.get("value") or ""
    return data


def _get_total_pages(soup: BeautifulSoup) -> int:
    """Extract total number of pages from pagination onclick attributes."""
    offsets = []
    for a in soup.select("ul.pagination li.page-item a.page-link"):
        onclick = a.get("onclick", "")
        # Extract the .value = N assignment (offset) from the onclick handler
        m = re.search(r"\.value\s*=\s*(\d+)", onclick)
        if m:
            offsets.append(int(m.group(1)))
    if offsets:
        return max(offsets) // 100 + 1
    return 1


def _parse_clubs_page(soup: BeautifulSoup) -> List[Dict]:
    """Parse a single page of clubs from the table."""
    clubs = []

    table = soup.find("table", class_=re.compile(r"\bclubs\b"))
    if not table:
        return clubs

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

    for tr in rows:
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue

        try:
            verein_cell = cells[0]
            link = verein_cell.find("a")
            name = link.get_text(strip=True) if link else verein_cell.get_text(strip=True)

            # Extract 5-digit WTB ID from cell text
            cell_text = verein_cell.get_text(" ", strip=True)
            id_match = re.search(r"\b(\d{5})\b", cell_text)
            wtb_id = id_match.group(1) if id_match else None

            if not wtb_id:
                continue

            # Strip the ID from the name if it got concatenated
            if name.endswith(wtb_id):
                name = name[: -len(wtb_id)].strip()

            location = cells[1].get_text(strip=True)
            district = cells[2].get_text(strip=True)

            href = link.get("href", "") if link else ""
            club_url = BASE_URL + href if href.startswith("/") else href

            clubs.append({
                "wtb_id": wtb_id,
                "name": name,
                "location": location,
                "district": district,
                "url": club_url,
            })

        except Exception as e:
            print(f"Error parsing club row: {e}")
            continue

    return clubs


async def scrape_all_clubs_with_progress():
    """
    Scrape all clubs from WTB website, yielding progress after each page.

    Yields:
        {"type": "progress", "page": N, "total_pages": N, "clubs_so_far": count}  — after each page
        {"type": "complete", "total_clubs": N, "clubs": [...]}  — at the end
    """
    clubs = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        # GET first page
        response = await client.get(CLUBS_URL, params=CLUBS_PARAMS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        # Determine total pages from pagination
        total_pages = _get_total_pages(soup)

        # Parse first page
        page_clubs = _parse_clubs_page(soup)
        for c in page_clubs:
            seen_ids.add(c["wtb_id"])
        clubs.extend(page_clubs)

        # Extract TYPO3 form tokens from first page (reused for all subsequent POSTs)
        form_data = _extract_form_data(soup)

        yield {
            "type": "progress",
            "page": 1,
            "total_pages": total_pages,
            "clubs_so_far": len(clubs),
        }

        # Fetch remaining pages
        for page in range(2, total_pages + 1):
            await asyncio.sleep(1.0)  # Be polite

            offset = (page - 1) * 100
            post_data = {
                **form_data,
                "tx_nuportalrs_clubs[clubsFilter][firstResult]": str(offset),
            }
            response = await client.post(
                CLUBS_URL, params=CLUBS_PARAMS, data=post_data
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            page_clubs = _parse_clubs_page(soup)
            new_clubs = [c for c in page_clubs if c["wtb_id"] not in seen_ids]
            if not new_clubs:
                break
            for c in new_clubs:
                seen_ids.add(c["wtb_id"])
            clubs.extend(new_clubs)

            yield {
                "type": "progress",
                "page": page,
                "total_pages": total_pages,
                "clubs_so_far": len(clubs),
            }

    yield {"type": "complete", "total_clubs": len(clubs), "clubs": clubs}


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
                    rang_cell = cells[0].text.strip()
                    ranking = int(rang_cell) if rang_cell.isdigit() else None
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
                            "wtb_id_nummer": wtb_id_cell,
                            "ranking": ranking,
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
    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        response = await client.get(CLUBS_URL, params=CLUBS_PARAMS)
        soup = BeautifulSoup(response.text, "lxml")
        clubs = _parse_clubs_page(soup)

    print(f"Found {len(clubs)} clubs on first page")
    if clubs:
        print(f"Sample: {clubs[0]}")

    print("\nTest complete!")


if __name__ == "__main__":
    # Run test
    asyncio.run(test_scraper())
