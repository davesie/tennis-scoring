import 'match_stats.dart';
import 'score_state.dart';

/// Mirror of `Match.to_dict()` in app/models.py.
class TennisMatch {
  final String id;
  final String shareCode;
  final String? matchDayId;
  final int? matchNumber;
  final String matchType; // "singles" | "doubles"
  final String teamAName;
  final String teamBName;
  final String? playerA1;
  final String? playerB1;
  final String? playerA2;
  final String? playerB2;
  final ScoreState scoreState;
  final List<ScoreCell> scoreCells;
  final Map<String, String> pointDisplay; // {"a": "40", "b": "30"}
  final int bestOf;
  final bool superTiebreakFinalSet;
  final DateTime? startedAt;
  final DateTime? finishedAt;
  final int? durationSeconds;
  final String? durationFormatted;
  final MatchStats? stats;

  const TennisMatch({
    required this.id,
    required this.shareCode,
    required this.matchDayId,
    required this.matchNumber,
    required this.matchType,
    required this.teamAName,
    required this.teamBName,
    required this.playerA1,
    required this.playerB1,
    required this.playerA2,
    required this.playerB2,
    required this.scoreState,
    required this.scoreCells,
    required this.pointDisplay,
    required this.bestOf,
    required this.superTiebreakFinalSet,
    required this.startedAt,
    required this.finishedAt,
    required this.durationSeconds,
    required this.durationFormatted,
    required this.stats,
  });

  bool get isDoubles => matchType == 'doubles';
  bool get isFinished => scoreState.isFinished;
  bool get isLive => startedAt != null && !isFinished;

  factory TennisMatch.fromJson(Map<String, dynamic> j) {
    DateTime? dt(dynamic v) {
      if (v == null) return null;
      var s = v.toString();
      // Backend timestamps are naive UTC; normalise so parsing is correct.
      if (!s.endsWith('Z') && !s.contains('+')) s = '${s}Z';
      return DateTime.tryParse(s)?.toLocal();
    }

    final pd = (j['point_display'] as Map?)?.cast<String, dynamic>() ?? const {};
    return TennisMatch(
      id: j['id'] as String,
      shareCode: j['share_code'] as String? ?? '',
      matchDayId: j['match_day_id'] as String?,
      matchNumber: (j['match_number'] as num?)?.toInt(),
      matchType: j['match_type'] as String? ?? 'singles',
      teamAName: j['team_a_name'] as String? ?? 'Team A',
      teamBName: j['team_b_name'] as String? ?? 'Team B',
      playerA1: j['player_a1'] as String?,
      playerB1: j['player_b1'] as String?,
      playerA2: j['player_a2'] as String?,
      playerB2: j['player_b2'] as String?,
      scoreState:
          ScoreState.fromJson((j['score_state'] as Map).cast<String, dynamic>()),
      scoreCells: (j['score_cells'] as List? ?? const [])
          .map((c) => ScoreCell.fromJson((c as Map).cast<String, dynamic>()))
          .toList(),
      pointDisplay: {
        'a': '${pd['a'] ?? ''}',
        'b': '${pd['b'] ?? ''}',
      },
      bestOf: (j['best_of'] as num?)?.toInt() ?? 3,
      superTiebreakFinalSet: j['super_tiebreak_final_set'] != false,
      startedAt: dt(j['started_at']),
      finishedAt: dt(j['finished_at']),
      durationSeconds: (j['duration_seconds'] as num?)?.toInt(),
      durationFormatted: j['duration_formatted'] as String?,
      stats: j['stats'] == null
          ? null
          : MatchStats.fromJson((j['stats'] as Map).cast<String, dynamic>()),
    );
  }

  /// Team A display label (single name, or "A / B" for doubles).
  String get teamALabel => _pair(playerA1, playerA2, teamAName);
  String get teamBLabel => _pair(playerB1, playerB2, teamBName);

  static String _pair(String? p1, String? p2, String fallback) {
    final a = (p1 ?? '').trim();
    final b = (p2 ?? '').trim();
    if (a.isEmpty && b.isEmpty) return fallback;
    if (b.isEmpty) return a;
    return '$a / $b';
  }
}
