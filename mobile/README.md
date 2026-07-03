# Tennis Scoring — Flutter client (iOS / Android / Web)

One Flutter codebase that runs as an **iOS app, an Android app, and a website**,
talking to the existing FastAPI backend over REST + WebSocket. The backend stays
the single source of truth — the app never computes tennis scoring itself, it
renders the server's `score_state` / `score_cells` / `point_display` and posts
scoring actions.

**v1 scope:** scorer + spectator. Match-day creation and WTB sync remain on the
existing web admin for now.

## Prerequisites

- Flutter SDK (stable, 3.x). This repo's CI environment does **not** ship
  Flutter, so `flutter pub get` / builds are run on a machine with Flutter.
- The backend running (see repo root README). It exposes the JSON auth endpoints
  and serves this app's web build at `/app`.

## Getting started

```bash
cd mobile
flutter pub get

# Run on a device/emulator (mobile). Point it at your backend:
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator
flutter run --dart-define=API_BASE_URL=http://localhost:8000  # iOS simulator

# Run in the browser during development:
flutter run -d chrome
```

On **web** the app auto-targets the same origin that serves it (via `Uri.base`),
so no `API_BASE_URL` is needed there.

> First run needs the platform folders. If `android/`, `ios/`, `web/` are not
> present for your Flutter version, run once:
> `flutter create --platforms=ios,android,web .`
> (the app sources under `lib/` and `web/index.html` here are preserved).

## Building the web bundle (served by FastAPI)

```bash
flutter build web --base-href /app/
```

This writes `mobile/build/web`, which the backend mounts at `/app` (same origin,
no CORS). Open `http://<backend-host>/app` — it coexists with the existing Jinja
site (`/archive`, `/admin`, `/watchday/...`).

## Building the apps

```bash
flutter build appbundle --dart-define=API_BASE_URL=https://your-host  # Android
flutter build ios       --dart-define=API_BASE_URL=https://your-host  # iOS
```

## Project layout

```
lib/
  config/api_config.dart        Same-origin (web) / --dart-define (mobile) base URL
  models/                       JSON mirrors of Match, MatchDay, score_state, stats
  services/
    api_client.dart             REST; injects Bearer + X-Scorer-Token
    live_connection.dart        WebSocket with exponential-backoff reconnect
    auth_store.dart             Token storage (secure on mobile, browser on web)
  theme/                        "Broadcast Court" light/dark ThemeData + fonts
  widgets/scoreboard.dart       TV-style scoreboard from score_cells/point_display
  screens/                      entry, match-day dashboard, match (scorer+spectator)
  router.dart                   go_router URL routes (deep links == web URLs)
  main.dart                     Bootstrap + MaterialApp.router
```

## Auth model

- **Watcher:** opens a `/watchday/{code}` or `/watch/{code}` link — no login.
- **Scorer:** opens a `/scoreday/{token}` link — the 12-char token is stored and
  sent as `X-Scorer-Token` for scoring calls.
- **Owner:** signs in on the entry screen (`POST /api/auth/login`) and gets a
  bearer token used as `Authorization: Bearer <token>`.

## Notes

- Models use hand-written `fromJson` to avoid a build_runner codegen step in the
  scaffold. Swapping to `freezed`/`json_serializable` later is straightforward.
