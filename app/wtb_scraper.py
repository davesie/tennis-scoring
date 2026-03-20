"""WTB website scraper for clubs and players."""

import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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
    async for event in scrape_all_clubs_with_progress():
        if event["type"] == "complete":
            return event["clubs"]
    return []


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
            logger.warning(f"Error parsing club row: {e}")
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

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            # Find the target category by link text, not by hardcoded collapse ID.
            # Collapse IDs vary per club (e.g. Herren can be #collapse11, #collapse26).
            # Pages may have multiple season sections (e.g. "VR-Talentiade Winter 2025/2026"
            # and "Winter 2025/2026"). Use the LAST matching link — the main season always
            # follows sub-events like VR-Talentiade, which only have youth categories anyway.
            collapse_id = None
            for a_tag in soup.find_all('a', href=re.compile(r'^#collapse\d+')):
                if a_tag.get_text(strip=True) == category:
                    collapse_id = a_tag['href'].lstrip('#')

            if not collapse_id:
                return players

            section = soup.find(id=collapse_id)
            if not section:
                return players

            table = section.find('table')
            if not table:
                return players

            rows = table.find_all('tr')

            # Skip header row
            for row in rows[1:]:
                cells = row.find_all('td')

                if len(cells) < 4:
                    continue

                # Cell structure: [Rang, LK, Name (Birth Year), ID-Nummer, Nation]
                # Rang can be "1", "2 MF", etc. — extract leading number for rank,
                # detect "MF" flag (Mannschaftsführer / team captain)
                rang_cell = cells[0].text.strip()
                rang_match = re.match(r'^(\d+)', rang_cell)
                ranking = int(rang_match.group(1)) if rang_match else None
                is_captain = 'MF' in rang_cell

                lk_raw = cells[1].text.strip() if len(cells) > 1 else ""
                # Strip "LK" prefix — store only the numeric value (e.g. "4,0")
                lk_cell = re.sub(r'^LK\s*', '', lk_raw)

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
                        "category": category,
                        "wtb_id_nummer": wtb_id_cell,
                        "ranking": ranking,
                        "is_captain": is_captain,
                        "lk": lk_cell or None,
                    })

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error scraping players for club {wtb_id}: {e}")
            return []
        except Exception as e:
            logger.warning(f"Error scraping players for club {wtb_id}: {e}")
            return []

    return players


async def scrape_club_teams(wtb_id: str, category_filter: Optional[str] = "Herren") -> List[Dict]:
    """
    Scrape all teams for a club from the WTB Mannschaften page.
    Teams are organized under level sections (e.g. "Verband", "Bezirk A/B/C/...").
    This function iterates all sections to collect every team.

    Args:
        wtb_id: Club WTB ID (e.g., "20099")
        category_filter: Filter by category prefix (e.g., "Herren"). None = all teams.

    Returns:
        List of team dicts: team_id, team_name, league, format, captain_name, level
    """
    url = f"{BASE_URL}/spielbetrieb/vereine/verein/mannschaften/v/{wtb_id}.html"
    teams = []

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # The page has H3 section headers like "Verband 2025/26 / Winter"
            # or "Bezirk A 2025/26 / Winter", each followed by a table of teams.
            # Iterate all H3 headers and find their associated tables.
            for h3 in soup.find_all("h3"):
                section_text = h3.get_text(strip=True)
                # Only process sections that look like competition levels
                # (contain "Verband", "Bezirk", "Sommer", "Winter", etc.)
                if not any(kw in section_text for kw in ("Verband", "Bezirk", "Sommer", "Winter")):
                    continue

                # Extract the level name (e.g. "Verband", "Bezirk A")
                level = section_text.split("/")[0].strip() if "/" in section_text else section_text
                # Remove year info like "2025/26"
                level = re.sub(r"\s*\d{4}(?:/\d{2,4})?\s*", " ", level).strip()

                # Find the next table after this H3
                table = h3.find_next("table")
                if not table:
                    continue

                for row in table.find_all("tr")[1:]:  # Skip header
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue

                    try:
                        name_cell = cells[0]
                        link = name_cell.find("a")
                        if not link:
                            continue

                        team_name = link.get_text(strip=True)
                        href = link.get("href", "")

                        id_match = re.search(r"/m/(\d+)\.html", href)
                        if not id_match:
                            continue
                        team_id = id_match.group(1)

                        # Apply category filter
                        if category_filter and not team_name.startswith(category_filter):
                            continue

                        # Columns: Mannschaft, Mannschaftsführer, Gruppe, Tab.-Rang, Punkte
                        captain_name = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                        league = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                        # Detect format: "(4er)" = 4 players, no suffix or "(6er)" = 6 players
                        fmt = "4_person" if "(4er)" in team_name else "6_person"

                        teams.append({
                            "team_id": team_id,
                            "team_name": team_name,
                            "league": league,
                            "format": fmt,
                            "captain_name": captain_name,
                            "level": level,
                        })

                    except Exception as e:
                        logger.warning(f"Error parsing team row for club {wtb_id}: {e}")
                        continue

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error scraping teams for club {wtb_id}: {e}")
        except Exception as e:
            logger.warning(f"Error scraping teams for club {wtb_id}: {e}")

    return teams


async def scrape_team_fixtures(wtb_id: str, team_id: str) -> List[Dict]:
    """
    Scrape the fixture schedule for a specific team.

    Args:
        wtb_id: Club WTB ID (e.g., "20099")
        team_id: Team ID from URL (e.g., "3496556")

    Returns:
        List of fixture dicts with meeting_id, scheduled_date, home_team, away_team,
        venue, score_matches, is_played
    """
    url = f"{BASE_URL}/spielbetrieb/vereine/verein/mannschaften/mannschaft/v/{wtb_id}/m/{team_id}.html"
    fixtures = []

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # Find the schedule table — has "Datum" in header, not "Rang"
            schedule_table = None
            for table in soup.find_all("table"):
                headers = [th.get_text(strip=True) for th in table.find_all("th")]
                if "Datum" in headers and "Rang" not in headers:
                    schedule_table = table
                    break

            if not schedule_table:
                return fixtures

            # Columns: Datum, Heimmannschaft, Gastmannschaft, Spielort,
            #          Matches, Sätze, Games, Spielbericht
            rows = schedule_table.find_all("tr")
            for row in rows[1:]:  # Skip header
                cells = row.find_all("td")
                if len(cells) < 8:
                    continue

                try:
                    # Column 0: Date — strip weekday prefix like "Sa, "
                    date_text = cells[0].get_text(strip=True)
                    date_text = re.sub(r"^[A-Za-z]{2},?\s*", "", date_text)
                    scheduled_date = None
                    try:
                        scheduled_date = datetime.strptime(date_text, "%d.%m.%Y %H:%M")
                    except ValueError:
                        try:
                            scheduled_date = datetime.strptime(date_text, "%d.%m.%Y")
                        except ValueError:
                            pass

                    # Columns 1-3: teams and venue
                    home_team = cells[1].get_text(strip=True)
                    away_team = cells[2].get_text(strip=True)
                    venue = cells[3].get_text(strip=True)

                    # Column 4: Matches score (e.g. "6:0" or "0:0" for unplayed)
                    score_matches = cells[4].get_text(strip=True)

                    # Determine if played: check Spielbericht column (last cell)
                    # "anzeigen" link with meetingId = played, "Vorlage" link = unplayed
                    spielbericht_cell = cells[7]
                    spielbericht_text = spielbericht_cell.get_text(strip=True)
                    is_played = spielbericht_text == "anzeigen"

                    # Extract meeting_id and full Spielbericht URL from links
                    meeting_id = None
                    spielbericht_url = None
                    for a_tag in row.find_all("a", href=True):
                        href = a_tag.get("href", "")
                        m = re.search(r"meeting(?:Id|%5BId%5D)[=%5D]*(\d+)", href)
                        if m:
                            meeting_id = m.group(1)
                            if href.startswith("/"):
                                spielbericht_url = BASE_URL + href
                            elif href.startswith("http"):
                                spielbericht_url = href
                            break

                    # For unplayed fixtures, extract meeting ID from the Vorlage link
                    if not meeting_id:
                        for a_tag in row.find_all("a", href=True):
                            href = a_tag.get("href", "")
                            m = re.search(r"meeting[=/](\d+)", href)
                            if m:
                                meeting_id = m.group(1)
                                break

                    if not meeting_id:
                        continue

                    # Format match score for display (hide "0:0" for unplayed)
                    display_score = score_matches if is_played else ""

                    fixtures.append({
                        "meeting_id": meeting_id,
                        "spielbericht_url": spielbericht_url,
                        "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
                        "home_team": home_team,
                        "away_team": away_team,
                        "venue": venue,
                        "score_matches": display_score,
                        "is_played": is_played,
                    })

                except Exception as e:
                    logger.warning(f"Error parsing fixture row for team {team_id}: {e}")
                    continue

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error scraping fixtures for team {team_id}: {e}")
        except Exception as e:
            logger.warning(f"Error scraping fixtures for team {team_id}: {e}")

    return fixtures


def _parse_player_cell(cell) -> List[Dict]:
    """
    Parse a player cell from the Spielbericht table.
    Singles: one player. Doubles: two players separated by <br/>.
    Returns list of dicts with name and lk.
    """
    players = []
    for link in cell.find_all("a", class_="external-link"):
        name = link.get_text(strip=True)
        # Strip nationality suffix like "(UZB)" from the name
        name = re.sub(r"\([A-Z]{2,4}\)$", "", name).strip()

        # Find LK from the <abbr title="Leistungsklasse"> that follows
        lk = None
        # Walk siblings after the link to find the LK abbr
        for small in cell.find_all("small"):
            abbr = small.find("abbr", title="Leistungsklasse")
            if abbr:
                lk_text = abbr.get_text(strip=True)
                # e.g. "LK 5" → "5"
                lk_match = re.match(r"LK\s+(.+)", lk_text)
                if lk_match:
                    lk = lk_match.group(1)
                    # Only take LK that comes after our player's link
                    # by checking if the link precedes this small tag
                    players.append({"name": name, "lk": lk})
                    lk = None
                    break  # Will re-find for next player

    # If the simple approach didn't match, try a more structured parse
    if not players:
        for link in cell.find_all("a", class_="external-link"):
            name = link.get_text(strip=True)
            name = re.sub(r"\([A-Z]{2,4}\)$", "", name).strip()
            players.append({"name": name, "lk": None})

    # Better approach: iterate through all links and pair with following LK abbrs
    if len(players) != len(cell.find_all("a", class_="external-link")):
        players = []
        for link in cell.find_all("a", class_="external-link"):
            name = link.get_text(strip=True)
            name = re.sub(r"\([A-Z]{2,4}\)$", "", name).strip()
            players.append({"name": name, "lk": None})

    # Now extract all LK values in order and pair them
    lk_values = []
    for abbr in cell.find_all("abbr", title="Leistungsklasse"):
        lk_text = abbr.get_text(strip=True)
        lk_match = re.match(r"LK\s+(.+)", lk_text)
        if lk_match:
            lk_values.append(lk_match.group(1))

    for i, lk_val in enumerate(lk_values):
        if i < len(players):
            players[i]["lk"] = lk_val

    return players


def _parse_set_scores(cells) -> List[List[int]]:
    """
    Parse set score cells (1. Satz, 2. Satz, 3. Satz) from Spielbericht.
    Returns list of [home_games, away_games] for each played set.
    """
    sets = []
    for cell in cells:
        text = cell.get_text(strip=True)
        if not text:
            continue
        m = re.match(r"(\d+):(\d+)", text)
        if m:
            sets.append([int(m.group(1)), int(m.group(2))])
    return sets


async def scrape_spielbericht(spielbericht_url: str) -> Optional[Dict]:
    """
    Scrape a Spielbericht (match report) page for full match details.

    Args:
        spielbericht_url: Full URL to the Spielbericht page (including season path + cHash)

    Returns:
        Dict with home_team, away_team, overall_score,
        singles (list of match dicts), doubles (list of match dicts),
        or None if the page can't be parsed.
    """
    url = spielbericht_url

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            tables = soup.find_all("table")
            if len(tables) < 2:
                return None

            # Table 0: overall match result
            score_table = tables[0]
            score_cells = score_table.find_all("td")
            home_team = ""
            away_team = ""
            overall_score = ""

            # Extract team names from th headers
            for th in score_table.find_all("th"):
                h3 = th.find("h3")
                if h3:
                    cls = th.get("class", [])
                    if "home" in cls:
                        home_team = h3.get_text(strip=True)
                    elif "guest" in cls:
                        away_team = h3.get_text(strip=True)

            if len(score_cells) >= 3:
                home_score = score_cells[0].get_text(strip=True)
                away_score = score_cells[2].get_text(strip=True)
                overall_score = f"{home_score}:{away_score}"

            # Table 1: match details (singles + doubles)
            results_table = tables[1]
            rows = results_table.find_all("tr")

            singles = []
            doubles = []
            current_section = None  # "Einzel" or "Doppel"

            for row in rows:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                # Section headers
                first_text = cells[0].get_text(strip=True)
                if first_text == "Einzel" and len(cells) == 1:
                    current_section = "singles"
                    continue
                if first_text == "Doppel" and len(cells) == 1:
                    current_section = "doubles"
                    continue

                # Skip column header rows (contain "1. Satz")
                if any("Satz" in c.get_text(strip=True) for c in cells):
                    continue

                # Skip summary rows (Einzel/Doppel/Gesamt totals — 4 cells)
                if len(cells) == 4 and first_text in ("Einzel", "Doppel", "Gesamt"):
                    continue

                # Match data rows have 8 cells
                if len(cells) != 8:
                    continue

                if not current_section:
                    continue

                home_cell = cells[0]
                away_cell = cells[1]
                set_cells = cells[2:5]  # 1. Satz, 2. Satz, 3. Satz
                matches_cell = cells[5]  # e.g. "1:0"

                home_players = _parse_player_cell(home_cell)
                away_players = _parse_player_cell(away_cell)
                set_scores = _parse_set_scores(set_cells)

                # Determine winner from matches cell (e.g. "1:0" = home wins)
                winner = None
                matches_text = matches_cell.get_text(strip=True)
                m = re.match(r"(\d+):(\d+)", matches_text)
                if m:
                    hw, aw = int(m.group(1)), int(m.group(2))
                    if hw > aw:
                        winner = 0  # home team
                    elif aw > hw:
                        winner = 1  # away team

                match_data = {
                    "home_players": home_players,
                    "away_players": away_players,
                    "sets": set_scores,
                    "winner": winner,
                }

                if current_section == "singles":
                    singles.append(match_data)
                elif current_section == "doubles":
                    doubles.append(match_data)

            return {
                "home_team": home_team,
                "away_team": away_team,
                "overall_score": overall_score,
                "singles": singles,
                "doubles": doubles,
            }

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error scraping Spielbericht {meeting_id}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error scraping Spielbericht {meeting_id}: {e}")
            return None
