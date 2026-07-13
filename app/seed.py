"""Demo data for the dev environment.

Runs at startup only when SEED_DEMO_DATA is set (1/true/yes) — set it as a
Coolify env var on the *dev* app only, never on main. Seeding is idempotent:
if the first demo user already exists, nothing happens. Since dev runs
without a persistent volume, every redeploy starts from an empty database
and reseeds fresh demo data automatically.

Seeded content (all logins use password "demo123"):
- Users: anna@demo.de, ben@demo.de, clara@demo.de (clara has no data — safe
  to delete when testing user management)
- A finished 4-person match day owned by Anna (full point-by-point + stats)
- A live 6-person match day owned by Ben (finished, in-progress and
  upcoming matches) with stable links:
  /watchday/demoday2 and /scoreday/demoscorer02
"""

import logging
import os
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from .auth import hash_password
from .database import async_session
from .models import Match, MatchDay, User
from .scoring import create_initial_state, score_point

logger = logging.getLogger(__name__)

DEMO_PASSWORD = "demo123"
DEMO_USERS = [
    {"email": "anna@demo.de", "display_name": "Anna Beispiel"},
    {"email": "ben@demo.de", "display_name": "Ben Tester"},
    {"email": "clara@demo.de", "display_name": "Clara Löschbar"},
]

_SERVER_OUTCOMES = ["ace", "winner", "winner", "forced_error", "unforced_error"]
_RECEIVER_OUTCOMES = ["double_fault", "winner", "unforced_error", "unforced_error", "forced_error"]


def seed_enabled() -> bool:
    return os.getenv("SEED_DEMO_DATA", "").strip().lower() in ("1", "true", "yes")


def _simulate(match: Match, rng: random.Random, bias: float, start: datetime,
              max_points: int | None = None, tag_share: float = 0.7) -> None:
    """Play a match point by point through the real scoring engine.

    bias is the probability that team A wins any given point. With
    max_points set, the match is left unfinished (live) at that point.
    """
    state = {**create_initial_state(), "serving": rng.randint(0, 1), "initial_server_set": True}
    log = []
    t = start

    while state.get("winner") is None:
        if max_points is not None and len(log) >= max_points:
            break
        team = 0 if rng.random() < bias else 1
        server = state.get("serving")
        set_before = state.get("current_set", 0)
        state = score_point(state, team, match.super_tiebreak_final_set)
        t += timedelta(seconds=rng.randint(25, 75))
        entry = {"winner": team, "server": server, "set": set_before, "outcome": None, "ts": t.isoformat()}
        if rng.random() < tag_share:
            entry["outcome"] = rng.choice(_SERVER_OUTCOMES if team == server else _RECEIVER_OUTCOMES)
        log.append(entry)

    match.score_state = state
    match.point_log = log
    match.history = []
    match.started_at = start
    match.updated_at = t
    match.finished_at = t if state.get("winner") is not None else None


async def seed_demo_data() -> None:
    if not seed_enabled():
        return

    async with async_session() as db:
        existing = await db.execute(select(User).where(User.email == DEMO_USERS[0]["email"]))
        if existing.scalar_one_or_none():
            logger.info("Demo data already present — skipping seed (delete the DB to reseed)")
            return

        rng = random.Random(42)  # deterministic: every fresh deploy seeds identical data
        pw_hash = hash_password(DEMO_PASSWORD)

        users = []
        for spec in DEMO_USERS:
            user = User(email=spec["email"], password_hash=pw_hash,
                        display_name=spec["display_name"], is_superadmin=False)
            db.add(user)
            users.append(user)
        await db.flush()
        anna, ben, _clara = users

        now = datetime.utcnow()

        # ---- Match day 1: finished 4-person tie, owned by Anna ----
        md1_start = now - timedelta(days=7, hours=5)
        team_a1 = ["Lukas Brandt", "Jonas Keller", "Felix Sommer", "David Winter"]
        team_b1 = ["Tim Berger", "Paul Vogt", "Nico Frank", "Jan Albrecht"]
        md1 = MatchDay(
            name="TC Demo Blau vs TSV Demo Rot",
            format="4_person",
            share_code="demoday1",
            scorer_token="demoscorer01",
            team_a_name="TC Demo Blau",
            team_b_name="TSV Demo Rot",
            team_a_players=team_a1,
            team_b_players=team_b1,
            category="Herren",
            owner_id=anna.id,
            is_public=True,
            created_at=md1_start,
            venue="Demo Tennispark",
        )
        db.add(md1)
        await db.flush()

        # 4 finished singles with varying favourites, then 2 finished doubles
        biases = [0.62, 0.45, 0.58, 0.40]
        for i in range(4):
            m = Match(
                match_day_id=md1.id, match_number=i + 1, match_type="singles",
                team_a_name=md1.team_a_name, team_b_name=md1.team_b_name,
                player_a1=team_a1[i], player_b1=team_b1[i],
                score_state=create_initial_state(), history=[], point_log=[],
                best_of=3, super_tiebreak_final_set=True,
                created_at=md1_start,
            )
            db.add(m)
            _simulate(m, rng, biases[i], md1_start + timedelta(minutes=10 + i * 5))

        doubles_pairs = [((0, 1), 0.57), ((2, 3), 0.44)]
        for j, ((p1, p2), bias) in enumerate(doubles_pairs):
            m = Match(
                match_day_id=md1.id, match_number=5 + j, match_type="doubles",
                team_a_name=md1.team_a_name, team_b_name=md1.team_b_name,
                player_a1=team_a1[p1], player_a2=team_a1[p2],
                player_b1=team_b1[p1], player_b2=team_b1[p2],
                score_state=create_initial_state(), history=[], point_log=[],
                best_of=3, super_tiebreak_final_set=True,
                created_at=md1_start,
            )
            db.add(m)
            _simulate(m, rng, bias, md1_start + timedelta(hours=2, minutes=15 + j * 5))

        # ---- Match day 2: live 6-person tie, owned by Ben ----
        md2_start = now - timedelta(hours=2)
        team_a2 = ["Max Hoffmann", "Leon Schuster", "Erik Wagner",
                   "Tom Fischer", "Ben Krause", "Ole Neumann"]
        team_b2 = ["Finn Weber", "Noah Schmid", "Luis Becker",
                   "Emil Roth", "Anton Meier", "Karl Busch"]
        md2 = MatchDay(
            name="TC Demo Grün vs SV Demo Gelb",
            format="6_person",
            share_code="demoday2",
            scorer_token="demoscorer02",
            team_a_name="TC Demo Grün",
            team_b_name="SV Demo Gelb",
            team_a_players=team_a2,
            team_b_players=team_b2,
            category="Herren 30",
            owner_id=ben.id,
            is_public=True,
            created_at=md2_start,
            venue="Demo Anlage Süd",
        )
        db.add(md2)
        await db.flush()

        # Matches 1-2 finished, 3-4 live mid-match, 5-6 not started
        plans = [(0.61, None), (0.42, None), (0.55, 55), (0.47, 78), (None, None), (None, None)]
        for i, (bias, max_points) in enumerate(plans):
            m = Match(
                match_day_id=md2.id, match_number=i + 1, match_type="singles",
                team_a_name=md2.team_a_name, team_b_name=md2.team_b_name,
                player_a1=team_a2[i], player_b1=team_b2[i],
                score_state=create_initial_state(), history=[], point_log=[],
                best_of=3, super_tiebreak_final_set=True,
                created_at=md2_start,
            )
            db.add(m)
            if bias is not None:
                _simulate(m, rng, bias, md2_start + timedelta(minutes=5 + i * 3), max_points=max_points)

        await db.commit()

    logger.info(
        "Demo data seeded: %d users (password '%s'), 2 match days — "
        "live day: /watchday/demoday2, scorer: /scoreday/demoscorer02",
        len(DEMO_USERS), DEMO_PASSWORD,
    )
