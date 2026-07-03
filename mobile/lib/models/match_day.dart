import 'match.dart';

/// Mirror of `MatchDay.to_dict()` / `to_dict_private()` in app/models.py.
class MatchDay {
  final String id;
  final String shareCode;
  final String name;
  final String format; // "6_person" | "4_person"
  final String teamAName;
  final String teamBName;
  final List<String> teamAPlayers;
  final List<String> teamBPlayers;
  final String? category;
  final bool isPublic;
  final DateTime? scheduledDate;
  final String? venue;
  final String? scorerToken; // present only in the private (owner) view

  const MatchDay({
    required this.id,
    required this.shareCode,
    required this.name,
    required this.format,
    required this.teamAName,
    required this.teamBName,
    required this.teamAPlayers,
    required this.teamBPlayers,
    required this.category,
    required this.isPublic,
    required this.scheduledDate,
    required this.venue,
    required this.scorerToken,
  });

  factory MatchDay.fromJson(Map<String, dynamic> j) {
    List<String> strs(dynamic v) =>
        (v as List? ?? const []).map((e) => e.toString()).toList();
    DateTime? dt(dynamic v) {
      if (v == null) return null;
      var s = v.toString();
      if (!s.endsWith('Z') && !s.contains('+')) s = '${s}Z';
      return DateTime.tryParse(s)?.toLocal();
    }

    return MatchDay(
      id: j['id'] as String,
      shareCode: j['share_code'] as String? ?? '',
      name: j['name'] as String? ?? 'Match Day',
      format: j['format'] as String? ?? '6_person',
      teamAName: j['team_a_name'] as String? ?? 'Team A',
      teamBName: j['team_b_name'] as String? ?? 'Team B',
      teamAPlayers: strs(j['team_a_players']),
      teamBPlayers: strs(j['team_b_players']),
      category: j['category'] as String?,
      isPublic: j['is_public'] != false,
      scheduledDate: dt(j['scheduled_date']),
      venue: j['venue'] as String?,
      scorerToken: j['scorer_token'] as String?,
    );
  }
}

/// A match day plus its matches, as returned by GET /api/matchdays/{id}.
class MatchDayBundle {
  final MatchDay matchDay;
  final List<TennisMatch> matches;

  const MatchDayBundle({required this.matchDay, required this.matches});

  List<TennisMatch> get singles =>
      matches.where((m) => m.matchType == 'singles').toList();
  List<TennisMatch> get doubles =>
      matches.where((m) => m.matchType == 'doubles').toList();

  int get teamAWins =>
      matches.where((m) => m.scoreState.winner == 0).length;
  int get teamBWins =>
      matches.where((m) => m.scoreState.winner == 1).length;

  factory MatchDayBundle.fromJson(Map<String, dynamic> j) => MatchDayBundle(
        matchDay:
            MatchDay.fromJson((j['match_day'] as Map).cast<String, dynamic>()),
        matches: (j['matches'] as List? ?? const [])
            .map((m) => TennisMatch.fromJson((m as Map).cast<String, dynamic>()))
            .toList(),
      );
}
