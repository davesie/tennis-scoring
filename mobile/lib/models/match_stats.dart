/// Per-team point statistics, mirror of `compute_match_stats` in app/scoring.py.
class TeamStats {
  final int pointsWon;
  final int aces;
  final int doubleFaults;
  final int winners;
  final int unforcedErrors;
  final int forcedErrors;

  const TeamStats({
    required this.pointsWon,
    required this.aces,
    required this.doubleFaults,
    required this.winners,
    required this.unforcedErrors,
    required this.forcedErrors,
  });

  factory TeamStats.fromJson(Map<String, dynamic> j) => TeamStats(
        pointsWon: (j['points_won'] as num?)?.toInt() ?? 0,
        aces: (j['aces'] as num?)?.toInt() ?? 0,
        doubleFaults: (j['double_faults'] as num?)?.toInt() ?? 0,
        winners: (j['winners'] as num?)?.toInt() ?? 0,
        unforcedErrors: (j['unforced_errors'] as num?)?.toInt() ?? 0,
        forcedErrors: (j['forced_errors'] as num?)?.toInt() ?? 0,
      );
}

class MatchStats {
  final TeamStats a;
  final TeamStats b;
  final int tagged;
  final int total;

  const MatchStats({
    required this.a,
    required this.b,
    required this.tagged,
    required this.total,
  });

  factory MatchStats.fromJson(Map<String, dynamic> j) => MatchStats(
        a: TeamStats.fromJson((j['a'] as Map).cast<String, dynamic>()),
        b: TeamStats.fromJson((j['b'] as Map).cast<String, dynamic>()),
        tagged: (j['tagged'] as num?)?.toInt() ?? 0,
        total: (j['total'] as num?)?.toInt() ?? 0,
      );
}
