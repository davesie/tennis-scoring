import 'package:go_router/go_router.dart';

import 'screens/entry_screen.dart';
import 'screens/match_day_screen.dart';
import 'screens/match_screen.dart';

/// URL-based routes. Deep links on mobile == real browser URLs on web, and the
/// paths intentionally match the site's URLs so a shared link works everywhere.
final router = GoRouter(
  routes: [
    GoRoute(path: '/', builder: (_, __) => const EntryScreen()),

    // Match day — spectator (share code) / scorer (token) / owner (id)
    GoRoute(
      path: '/watchday/:code',
      builder: (_, s) => MatchDayScreen.spectator(s.pathParameters['code']!),
    ),
    GoRoute(
      path: '/scoreday/:token',
      builder: (_, s) => MatchDayScreen.scorer(s.pathParameters['token']!),
    ),
    GoRoute(
      path: '/matchday/:id',
      builder: (_, s) => MatchDayScreen.byId(s.pathParameters['id']!),
    ),

    // Single match — spectator (share code) / by id
    GoRoute(
      path: '/watch/:code',
      builder: (_, s) => MatchScreen.spectator(s.pathParameters['code']!),
    ),
    GoRoute(
      path: '/match/:id',
      builder: (_, s) => MatchScreen.byId(
        s.pathParameters['id']!,
        canScore: s.uri.queryParameters['score'] == '1',
      ),
    ),
  ],
);
