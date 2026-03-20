"""Tests for WTB fixture import feature."""

import asyncio
import pytest
from app.wtb_scraper import scrape_club_teams, scrape_team_fixtures


# TC Hirschlanden — known club for testing
WTB_ID = "20099"


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestScrapeClubTeams:
    """Test scrape_club_teams against live WTB data."""

    def test_herren_teams(self, event_loop):
        teams = event_loop.run_until_complete(scrape_club_teams(WTB_ID, category_filter="Herren"))
        assert len(teams) > 0, "Expected at least one Herren team"

        for team in teams:
            assert team["team_id"], "team_id must be set"
            assert team["team_name"].startswith("Herren"), f"Expected Herren prefix, got {team['team_name']}"
            assert team["team_id"].isdigit(), f"team_id should be numeric, got {team['team_id']}"
            assert team["format"] in ("4_person", "6_person"), f"Unexpected format: {team['format']}"

    def test_all_teams(self, event_loop):
        all_teams = event_loop.run_until_complete(scrape_club_teams(WTB_ID, category_filter=None))
        herren_teams = event_loop.run_until_complete(scrape_club_teams(WTB_ID, category_filter="Herren"))
        assert len(all_teams) >= len(herren_teams), "All teams should include Herren teams"

    def test_format_detection(self, event_loop):
        teams = event_loop.run_until_complete(scrape_club_teams(WTB_ID, category_filter=None))
        # Just verify format is always valid
        for team in teams:
            assert team["format"] in ("4_person", "6_person")


class TestScrapeTeamFixtures:
    """Test scrape_team_fixtures against live WTB data."""

    def _get_first_team_id(self, event_loop):
        teams = event_loop.run_until_complete(scrape_club_teams(WTB_ID, category_filter="Herren"))
        assert len(teams) > 0, "Need at least one Herren team"
        return teams[0]["team_id"]

    def test_fixtures_returned(self, event_loop):
        team_id = self._get_first_team_id(event_loop)
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, team_id))
        # May be empty if season hasn't started, but shouldn't error
        assert isinstance(fixtures, list)

    def test_fixture_fields(self, event_loop):
        team_id = self._get_first_team_id(event_loop)
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, team_id))

        for f in fixtures:
            assert f["meeting_id"], "meeting_id must be set"
            assert f["meeting_id"].isdigit(), f"meeting_id should be numeric: {f['meeting_id']}"
            assert f["home_team"], "home_team must be set"
            assert f["away_team"], "away_team must be set"
            assert isinstance(f["is_played"], bool)

    def test_meeting_ids_unique(self, event_loop):
        team_id = self._get_first_team_id(event_loop)
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, team_id))

        meeting_ids = [f["meeting_id"] for f in fixtures]
        assert len(meeting_ids) == len(set(meeting_ids)), "meeting_ids should be unique"

    def test_date_parsing(self, event_loop):
        team_id = self._get_first_team_id(event_loop)
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, team_id))

        for f in fixtures:
            if f["scheduled_date"]:
                # Should be valid ISO format
                from datetime import datetime
                try:
                    datetime.fromisoformat(f["scheduled_date"])
                except ValueError:
                    pytest.fail(f"Invalid date format: {f['scheduled_date']}")
