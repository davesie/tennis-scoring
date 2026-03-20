"""Tests for WTB fixture import feature."""

import asyncio
import pytest
from app.wtb_scraper import scrape_club_teams, scrape_team_fixtures, scrape_spielbericht


# TC Hirschlanden — known club for testing
WTB_ID = "20099"
TEAM_ID = "3496556"  # Herren 1


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
        for team in teams:
            assert team["format"] in ("4_person", "6_person")


class TestScrapeTeamFixtures:
    """Test scrape_team_fixtures against live WTB data."""

    def test_fixtures_returned(self, event_loop):
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, TEAM_ID))
        assert isinstance(fixtures, list)
        assert len(fixtures) > 0, "Expected at least one fixture"

    def test_fixture_fields(self, event_loop):
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, TEAM_ID))

        for f in fixtures:
            assert f["meeting_id"], "meeting_id must be set"
            assert f["meeting_id"].isdigit(), f"meeting_id should be numeric: {f['meeting_id']}"
            assert f["home_team"], "home_team must be set"
            assert f["away_team"], "away_team must be set"
            assert isinstance(f["is_played"], bool)
            assert f["venue"], "venue should be set"

    def test_played_fixtures_have_scores(self, event_loop):
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, TEAM_ID))
        played = [f for f in fixtures if f["is_played"]]
        assert len(played) > 0, "Expected at least one played fixture"

        for f in played:
            assert f["score_matches"], f"Played fixture should have score: {f}"
            assert ":" in f["score_matches"]
            assert f["spielbericht_url"], "Played fixture should have spielbericht_url"

    def test_upcoming_fixtures_no_scores(self, event_loop):
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, TEAM_ID))
        upcoming = [f for f in fixtures if not f["is_played"]]
        # There may be no upcoming fixtures depending on season state
        for f in upcoming:
            assert not f["score_matches"], "Upcoming fixture should have no score"

    def test_meeting_ids_unique(self, event_loop):
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, TEAM_ID))
        meeting_ids = [f["meeting_id"] for f in fixtures]
        assert len(meeting_ids) == len(set(meeting_ids)), "meeting_ids should be unique"

    def test_date_parsing(self, event_loop):
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, TEAM_ID))
        for f in fixtures:
            if f["scheduled_date"]:
                from datetime import datetime
                try:
                    datetime.fromisoformat(f["scheduled_date"])
                except ValueError:
                    pytest.fail(f"Invalid date format: {f['scheduled_date']}")


class TestScrapeSpielbericht:
    """Test scrape_spielbericht against a known played match."""

    def _get_spielbericht_url(self, event_loop):
        fixtures = event_loop.run_until_complete(scrape_team_fixtures(WTB_ID, TEAM_ID))
        played = [f for f in fixtures if f["is_played"] and f.get("spielbericht_url")]
        assert len(played) > 0, "Need at least one played fixture with URL"
        return played[0]["spielbericht_url"]

    def test_spielbericht_basic(self, event_loop):
        url = self._get_spielbericht_url(event_loop)
        report = event_loop.run_until_complete(scrape_spielbericht(url))
        assert report is not None, "Report should not be None"
        assert report["home_team"], "home_team must be set"
        assert report["away_team"], "away_team must be set"
        assert report["overall_score"], "overall_score must be set"
        assert ":" in report["overall_score"]

    def test_spielbericht_singles(self, event_loop):
        url = self._get_spielbericht_url(event_loop)
        report = event_loop.run_until_complete(scrape_spielbericht(url))

        assert len(report["singles"]) > 0, "Should have singles matches"
        for match in report["singles"]:
            assert len(match["home_players"]) == 1, "Singles should have 1 home player"
            assert len(match["away_players"]) == 1, "Singles should have 1 away player"
            assert match["home_players"][0]["name"], "Player name must be set"
            assert len(match["sets"]) >= 2, "Should have at least 2 sets"
            assert match["winner"] in (0, 1), "Winner must be 0 or 1"

            for s in match["sets"]:
                assert len(s) == 2, "Set score should be [home, away]"
                assert isinstance(s[0], int) and isinstance(s[1], int)

    def test_spielbericht_doubles(self, event_loop):
        url = self._get_spielbericht_url(event_loop)
        report = event_loop.run_until_complete(scrape_spielbericht(url))

        assert len(report["doubles"]) > 0, "Should have doubles matches"
        for match in report["doubles"]:
            assert len(match["home_players"]) == 2, "Doubles should have 2 home players"
            assert len(match["away_players"]) == 2, "Doubles should have 2 away players"
            assert match["winner"] in (0, 1), "Winner must be 0 or 1"

    def test_spielbericht_player_lk(self, event_loop):
        url = self._get_spielbericht_url(event_loop)
        report = event_loop.run_until_complete(scrape_spielbericht(url))

        # At least some players should have LK values
        all_players = []
        for m in report["singles"] + report["doubles"]:
            all_players.extend(m["home_players"])
            all_players.extend(m["away_players"])

        lk_count = sum(1 for p in all_players if p.get("lk"))
        assert lk_count > 0, "At least some players should have LK values"
