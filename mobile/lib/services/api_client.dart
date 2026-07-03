import 'package:dio/dio.dart';

import '../config/api_config.dart';
import '../models/match.dart';
import '../models/match_day.dart';
import 'auth_store.dart';

/// Thin wrapper over the FastAPI REST API.
///
/// Injects `Authorization: Bearer <token>` (account login) and, when a scorer
/// token is present, `X-Scorer-Token` — mirroring the site's getAuthHeaders().
class ApiClient {
  ApiClient(this._auth)
      : _dio = Dio(BaseOptions(
          baseUrl: ApiConfig.httpBase,
          connectTimeout: const Duration(seconds: 15),
          receiveTimeout: const Duration(seconds: 15),
          headers: {'Content-Type': 'application/json'},
        ));

  final Dio _dio;
  final AuthStore _auth;

  Options get _authed {
    final headers = <String, String>{};
    final bearer = _auth.bearerToken;
    if (bearer != null && bearer.isNotEmpty) {
      headers['Authorization'] = 'Bearer $bearer';
    }
    final scorer = _auth.scorerToken;
    if (scorer != null && scorer.isNotEmpty) {
      headers['X-Scorer-Token'] = scorer;
    }
    return Options(headers: headers);
  }

  // ---- Auth ----

  /// Returns the bearer token on success and stores it.
  Future<String> login(String email, String password) async {
    final r = await _dio.post('/api/auth/login',
        data: {'email': email, 'password': password});
    final token = r.data['token'] as String;
    await _auth.setBearerToken(token);
    return token;
  }

  Future<String> register(String email, String password,
      {String? displayName}) async {
    final r = await _dio.post('/api/auth/register', data: {
      'email': email,
      'password': password,
      if (displayName != null) 'display_name': displayName,
    });
    final token = r.data['token'] as String;
    await _auth.setBearerToken(token);
    return token;
  }

  Future<Map<String, dynamic>> me() async {
    final r = await _dio.get('/api/auth/me', options: _authed);
    return (r.data['user'] as Map).cast<String, dynamic>();
  }

  Future<void> logout() async {
    try {
      await _dio.post('/api/auth/logout', options: _authed);
    } finally {
      await _auth.setBearerToken(null);
    }
  }

  // ---- Reads ----

  Future<TennisMatch> getMatch(String id) async {
    final r = await _dio.get('/api/matches/$id');
    return TennisMatch.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<TennisMatch> getMatchByShareCode(String code) async {
    final r = await _dio.get('/api/matches/share/$code');
    return TennisMatch.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<MatchDayBundle> getMatchDay(String id) async {
    final r = await _dio.get('/api/matchdays/$id', options: _authed);
    return MatchDayBundle.fromJson((r.data as Map).cast<String, dynamic>());
  }

  /// Public spectator read by 8-char share code.
  Future<MatchDayBundle> getMatchDayByShareCode(String code) async {
    final r = await _dio.get('/api/matchdays/share/$code');
    return MatchDayBundle.fromJson((r.data as Map).cast<String, dynamic>());
  }

  /// Scorer read by 12-char token; stores the token for subsequent scoring.
  Future<MatchDayBundle> getMatchDayByScorerToken(String token) async {
    await _auth.setScorerToken(token);
    final r = await _dio.get('/api/matchdays/by-scorer-token/$token');
    return MatchDayBundle.fromJson((r.data as Map).cast<String, dynamic>());
  }

  // ---- Scoring (scorer token or owner bearer) ----

  Future<TennisMatch> _postMatch(String path, [Object? body]) async {
    final r = await _dio.post(path, data: body, options: _authed);
    final map = (r.data as Map).cast<String, dynamic>();
    // Scoring endpoints return {"success": true, "match": {...}}.
    final match = (map['match'] as Map).cast<String, dynamic>();
    return TennisMatch.fromJson(match);
  }

  Future<TennisMatch> scorePoint(String matchId, int team) =>
      _postMatch('/api/matches/$matchId/score', {'team': team});

  Future<TennisMatch> scoreGame(String matchId, int team) =>
      _postMatch('/api/matches/$matchId/game', {'team': team});

  Future<TennisMatch> undo(String matchId) =>
      _postMatch('/api/matches/$matchId/undo');

  Future<TennisMatch> reset(String matchId) =>
      _postMatch('/api/matches/$matchId/reset');

  Future<TennisMatch> setServer(String matchId, int serving) =>
      _postMatch('/api/matches/$matchId/set-server', {'serving': serving});

  /// Tag the most recent point. One of: ace, winner, unforced_error,
  /// forced_error, double_fault. Returns nothing meaningful (no broadcast).
  Future<void> tagOutcome(String matchId, String outcome) async {
    await _dio.post('/api/matches/$matchId/point-outcome',
        data: {'outcome': outcome}, options: _authed);
  }
}
