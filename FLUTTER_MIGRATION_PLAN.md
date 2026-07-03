# Flutter Migration Plan — Tennis Scoring App

## Context

This repo is a real-time tennis scoring **web** app: Python 3.11 + FastAPI + SQLAlchemy
(async) + SQLite, Jinja2 templates, vanilla JS, and WebSockets for live updates. The
latest code lives on the **`dev`** branch (v2.1.0) and is ahead of `main` with two big
features: a multi-user platform (registration/login/ownership, v2.0.0) and per-point
match statistics with scorer tagging (v2.1.0).

The goal is to use this product as a native **iOS app, Android app, and website**. The key
finding from exploring the codebase: the backend already exposes nearly everything a client
needs as JSON REST + two WebSocket endpoints, and the tennis scoring engine
(`app/scoring.py`) is pure, side-effect-free Python. So the migration is overwhelmingly a
*client* project, not a backend rewrite.

### Decisions locked in

1. **Strategy: Native Flutter client.** Keep the FastAPI backend untouched as the single
   source of truth; build a real Flutter app that consumes its REST + WebSocket API.
2. **v1 scope: Scorer + Spectator.** Live scoring (points/games/undo/reset/server
   selection/per-point stat tagging) and live watching via share links. Admin match-day
   creation and WTB sync stay **web-only** for now.
3. **Online-only.** Every scoring action calls the backend; no local Dart scoring engine
   in v1. (`scoring.py` stays the only scoring implementation.)
4. **Auth: token links + JSON login.** Add a small JSON bearer-token login for account
   holders; also open scorer (12-char) and watcher (8-char) share links directly.
5. **Three targets from one codebase: iOS + Android + Web.** The same Flutter project also
   compiles to Web. The web build is served by the existing FastAPI backend at the **same
   origin** (like the current `/static` mount) → no CORS needed. The existing Jinja/JS
   website **coexists** for now: Flutter covers scorer + spectator on all three platforms;
   the Jinja site keeps admin match-day creation + WTB sync until/if those are rebuilt in
   Flutter later.

## Goal

Ship one Flutter codebase that runs as an **iOS app, an Android app, and a website**,
letting a scorer run a match day live and anyone watch in real time, backed by the
existing `dev` backend with only minimal, additive backend changes.

---

## Part A — Backend changes (small, additive, on `dev`)

The current auth is **cookie + form** based (`app/auth.py`), which is awkward for a native
app. We add a JSON token path *alongside* the existing cookie path — no existing behavior
changes.

1. **JSON auth endpoints** (new, in `app/main.py`, reusing `app/auth.py` helpers):
   - `POST /api/auth/login` → body `{email, password}`; verify via existing
     `verify_password()` + `hash_password()` (`app/auth.py:24-31`), create an
     `AdminSession` via existing `create_session()` (`app/auth.py:34-39`), and return
     `{token: <session_id>, user: {...}}` as JSON instead of setting a cookie.
   - `POST /api/auth/register` → JSON mirror of the existing form `POST /register`
     handler, returning the same token shape.
   - `GET /api/auth/me` → returns the current user; `POST /api/auth/logout` → deletes the
     session.
2. **Accept the token as a bearer header.** Extend `get_current_user()`
   (`app/auth.py:42-54`) to also read `Authorization: Bearer <session_id>` (and/or an
   `X-Session-Token` header), falling back to the existing `admin_session` cookie. The
   session lookup/expiry logic is reused unchanged. This makes every existing
   session-protected JSON route (e.g. `POST /api/matchdays`) usable from the app later
   without further changes.
3. **Scorer/watcher tokens already work for v1.** Scorer scoring calls authenticate with
   the existing `X-Scorer-Token` header via `verify_scorer_for_match()`
   (`app/auth.py:74-120`); spectator reads use the public `share_code` routes. No change
   needed for the core v1 flows.
4. **Serve the Flutter web build (no CORS).** Native iOS/Android never hit CORS. The
   Flutter **Web** build is served by FastAPI at the same origin, so CORS is still not
   needed. Add a `StaticFiles` mount (mirroring the existing `/static` mount,
   `app/main.py:251`) that serves the compiled `mobile/build/web` bundle at a dedicated
   path — e.g. `/app` — with a catch-all fallback to `index.html` so Flutter's
   client-side routing (deep-link URLs like `/app/scoreday/{token}`) survives a page
   refresh. The existing Jinja routes (`/`, `/archive`, `/admin`, `/watchday/...`) are
   untouched and coexist. (Only add `CORSMiddleware` if you later choose to host the web
   build on a separate domain.)
5. **Version bump** in `pyproject.toml` per repo convention (minor bump for the new JSON
   auth feature, e.g. `2.2.0`).

Everything else the app needs already exists:
- Match read: `GET /api/matches/{id}`, `GET /api/matches/share/{share_code}`
- Scoring: `POST /api/matches/{id}/score`, `/game`, `/undo`, `/reset`, `/set-server`,
  `/point-outcome`, `PATCH /players`, `PATCH /score` (`app/main.py:469-706`)
- Match day read: `GET /api/matchdays/{id}` (+ `share_code`-scoped reads)
- Live updates: `ws://…/ws/{match_id}` and `ws://…/ws/matchday/{match_day_id}`
  (`app/main.py:1612-1659`), messages `{type: initial|score_update|match_update, ...}`

---

## Part B — Flutter app

New top-level directory **`mobile/`** in the same repo (keeps backend + app versioned
together). Standard Flutter project (`flutter create --platforms=ios,android,web`),
targeting **iOS + Android + Web from one codebase**.

### Architecture
- **State management:** Riverpod (or Bloc) — pick one; plan assumes Riverpod.
- **Networking:** `dio` for REST, `web_socket_channel` for the live feeds. Both run on
  iOS, Android, **and Web** — `web_socket_channel` uses the browser `WebSocket` on web and
  dart:io sockets on mobile, transparently.
- **Cross-platform hygiene (so Web keeps working):** never import `dart:io` in shared code
  (breaks web) — use conditional imports or platform-abstracting packages. Resolve the API
  and WS base URL in one place (`ApiConfig`): absolute base URL on mobile
  (`--dart-define`), same-origin on web via `Uri.base`, so the web build auto-targets
  whatever host serves it.
- **Routing:** `go_router` with URL-based paths so the same routes act as deep links on
  mobile and real browser URLs on web (`/scoreday/{token}`, `/watchday/{code}`,
  `/watch/{code}`, `/match/{id}`, `/matchday/{id}`). Build the web bundle with a `/app/`
  base href to sit under the FastAPI mount.
- **Models:** Dart data classes mirroring the JSON in `Match.to_dict()`
  (`app/models.py:164`), `score_state`, `score_cells`, `point_display`, `stats`, plus
  `MatchDay`. Use `json_serializable`/`freezed`. **Do not port scoring logic** — the app
  renders server-computed `score_state`/`score_cells`/`point_display` and posts actions.
- **Config:** backend base URL via `--dart-define` (dev vs prod); web defaults to
  same-origin.

### Core services
- `ApiClient` — wraps REST calls; injects `Authorization: Bearer` (account login) and
  `X-Scorer-Token` (scorer) headers, matching the JS `getAuthHeaders()` pattern.
- `LiveConnection` — wraps a WebSocket to `/ws/{matchId}` or `/ws/matchday/{id}` with
  exponential-backoff reconnect (mirror the JS client: max ~10 attempts, capped ~30s) and
  a connection-status stream (connected / reconnecting / disconnected).
- `AuthStore` — persists bearer token (`flutter_secure_storage`) and scorer/watcher
  tokens.

### Screens (v1)
1. **Entry / Connect** — open by pasting or deep-linking a scorer/watcher URL, or log in
   with email/password (calls `POST /api/auth/login`). Parse `/scoreday/{token}`,
   `/watchday/{code}`, `/watch/{code}`, `/match/{id}` URL shapes.
2. **Match Day dashboard** — list of match cards (singles then doubles), live team score
   pill, live indicator, per-match status (Upcoming/Live/Final), elapsed timers. Drives
   off `/ws/matchday/{id}` `match_update` messages. 6-person = 6 singles + 3 doubles;
   4-person = 4 singles + 2 doubles. "Enter Score" on a card → scoring screen (scorers
   only). Spectators get read-only cards.
3. **Match scoring screen (scorer)** — TV-style scoreboard (sets columns + points column,
   serve indicator, current-set highlight, tiebreak/deuce/advantage state text) rendered
   from `score_cells`/`point_display`. Large Point A / Point B buttons, Game A / Game B
   buttons (hidden during tiebreak), Undo, Reset (with confirm). "Who serves first?"
   overlay before the first point (`POST /set-server`). After each point, a context-aware
   **outcome tag sheet** (Ace/Winner/Unforced/Forced, or Double Fault when receiver won),
   auto-dismiss ~12s → `POST /point-outcome`. Haptics via Flutter `HapticFeedback`
   mirroring the JS vibration patterns. Live stats panel.
4. **Match spectator view** — same scoreboard, scoring controls hidden, "watching live"
   notice, post-match stats + winner banner. Same screen with a `readOnly` flag.

### Cross-cutting
- **Design system ("Broadcast Court"):** define a Flutter `ThemeData` (light + dark) from
  the CSS tokens in `static/css/style.css` — Barlow Condensed (display), Chakra Petch
  (scores), DM Sans (body) via `google_fonts`; colors `--bc-bg/-text/-team-a/-team-b/`
  `-accent (#C6EF3E)` and the `--match-scoreboard-*` layer; spacing/radius/shadow scales.
  Persist light/dark choice (`shared_preferences`), mirroring the JS `localStorage` theme.
- **Deep links / share:** on mobile, register URL schemes / universal links so scorer &
  watcher links open the app; on web the same `go_router` URLs work natively. Use
  `share_plus` + `Clipboard` for share codes; guard mobile-only APIs (haptics, secure
  storage) behind `kIsWeb`/capability checks so web degrades gracefully.
- **Token storage:** `flutter_secure_storage` on mobile; on web it falls back to a
  browser-backed store — acceptable for session tokens. Keep it behind the `AuthStore`
  abstraction so the platform difference is invisible to the rest of the app.
- **Helpers to port from `static/js/common.js`:** `parseLK`/`stripLK` (player name + LK
  badge), `formatElapsed`, `parseUtc`, toast/snackbar feedback.

### Build & release
- **Web:** `flutter build web --base-href /app/`; the output (`mobile/build/web`) is served
  by FastAPI's static mount (Part A #4). Add a small build step/Make target so a backend
  deploy ships the current web bundle.
- **Android:** app bundle + signing; **iOS:** Xcode project, signing, App Store assets.
- App icons / splash for all targets; permissions are minimal (network only; haptics
  need none special).

---

## Suggested phasing

1. **Backend:** add JSON auth endpoints + bearer support + the Flutter-web static mount
   (Part A). Verify with `curl`.
2. **Flutter spike (all three platforms early):** project scaffold with
   `--platforms=ios,android,web`, `go_router`, models, `ApiClient`, read-only **spectator**
   match view over REST + `/ws/{matchId}`. Run it on an emulator **and** `flutter run -d
   chrome` from day one so web never silently rots.
3. **Match Day dashboard** (spectator) over `/ws/matchday/{id}`.
4. **Scorer flow:** scoring buttons, server overlay, undo/reset, outcome tagging, stats.
5. **Auth + entry screen + deep links / web routes;** theming polish (light/dark, fonts).
6. **Wire the web build into the backend:** `flutter build web --base-href /app/`, serve
   from FastAPI, confirm `/app` works same-origin next to the existing Jinja site.
7. **Release hardening:** app icons, store metadata, signing, device + browser testing.

---

## Files / references

**Backend (edit on `dev`):**
- `app/auth.py` — reuse `hash_password`/`verify_password` (24-31), `create_session`
  (34-39); extend `get_current_user` (42-54) to accept a bearer token.
- `app/main.py` — add `/api/auth/*` routes near the existing `/admin/login`,`/register`
  handlers; add the Flutter-web `StaticFiles` mount; all scoring/match-day/WebSocket routes
  already present (469-706, 708-936, 1612-1659).
- `app/models.py` — `Match.to_dict()` (164) and `score_state` shape are the JSON contract
  the Dart models mirror; `User`/`AdminSession` (23-48) back the JSON auth.
- `pyproject.toml` — version bump.

**Frontend reference (reproduce in Flutter, not edited):**
- `templates/match.html`, `templates/matchday.html` — scoreboard layout, WS client,
  tag-sheet UX, reconnect logic.
- `static/css/style.css` — full "Broadcast Court" design tokens (light/dark).
- `static/js/common.js` — `getAuthHeaders`, `parseLK`, `formatElapsed`, theme toggle,
  clipboard.

**New:**
- `mobile/` — the single Flutter project that builds to iOS, Android, and Web.
- `mobile/build/web` (git-ignored build output) — the compiled web bundle FastAPI serves
  at `/app`.

---

## Verification

- **Backend:** start `uvicorn app.main:app --reload`; `curl -X POST /api/auth/login` →
  confirm a token comes back; call `GET /api/matchdays/{id}` and a scoring `POST` with the
  bearer token and with `X-Scorer-Token` to confirm both auth paths work; confirm cookie
  login (web) still works unchanged.
- **Flutter (mobile):** `flutter run` on Android emulator + iOS simulator. Open a watcher
  link → confirm scoreboard renders and updates live when a point is scored from the
  existing web app (validates `/ws/{matchId}`). Open a scorer link → score points/games,
  undo, reset, set server, tag an outcome → confirm the existing web spectator view updates
  simultaneously (validates the shared backend is the single source of truth).
- **Flutter (web):** `flutter run -d chrome` during dev, then `flutter build web
  --base-href /app/` and load `/app` from the FastAPI server → confirm the same scorer and
  spectator flows work in-browser, that deep-link URLs (`/app/watchday/{code}`) resolve on
  refresh, and that the WebSocket connects same-origin with no CORS errors in the console.
- **Coexistence:** confirm the existing Jinja routes (`/archive`, `/admin`, `/watchday/…`)
  still render normally alongside the new `/app` mount.
- **Cross-platform parity:** score a full set incl. a tiebreak on mobile, web, and the old
  site simultaneously and confirm all three show identical `score_cells`/points live (they
  all render the same server state).
