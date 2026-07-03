/// Mirror of the backend `score_state` dict (see app/scoring.py).
///
/// The app never *computes* scoring — the server is the single source of
/// truth. These models exist only to render what the backend sends.
class ScoreState {
  final List<int> points; // current game points [a, b]
  final List<List<int>> games; // games per set
  final List<int> sets; // sets won [a, b]
  final int currentSet;
  final int serving; // 0 = Team A, 1 = Team B
  final bool isTiebreak;
  final bool isSuperTiebreak;
  final List<int> tiebreakPoints;
  final int? winner; // null | 0 | 1
  final int? deuceAdvantage;
  final bool initialServerSet;

  const ScoreState({
    required this.points,
    required this.games,
    required this.sets,
    required this.currentSet,
    required this.serving,
    required this.isTiebreak,
    required this.isSuperTiebreak,
    required this.tiebreakPoints,
    required this.winner,
    required this.deuceAdvantage,
    required this.initialServerSet,
  });

  bool get isFinished => winner != null;

  factory ScoreState.fromJson(Map<String, dynamic> j) {
    List<int> ints(dynamic v) =>
        (v as List? ?? const []).map((e) => (e as num).toInt()).toList();
    return ScoreState(
      points: ints(j['points']),
      games: (j['games'] as List? ?? const [])
          .map((row) => ints(row))
          .toList(),
      sets: ints(j['sets']),
      currentSet: (j['current_set'] as num?)?.toInt() ?? 0,
      serving: (j['serving'] as num?)?.toInt() ?? 0,
      isTiebreak: j['is_tiebreak'] == true,
      isSuperTiebreak: j['is_super_tiebreak'] == true,
      tiebreakPoints: ints(j['tiebreak_points']),
      winner: (j['winner'] as num?)?.toInt(),
      deuceAdvantage: (j['deuce_advantage'] as num?)?.toInt(),
      initialServerSet: j['initial_server_set'] == true,
    );
  }
}

/// One rendered set column, from the backend `score_cells`.
class ScoreCell {
  final String a;
  final String b;
  final String? aSup; // tiebreak superscript
  final String? bSup;
  final bool show;

  const ScoreCell({
    required this.a,
    required this.b,
    this.aSup,
    this.bSup,
    required this.show,
  });

  factory ScoreCell.fromJson(Map<String, dynamic> j) => ScoreCell(
        a: '${j['a'] ?? ''}',
        b: '${j['b'] ?? ''}',
        aSup: j['a_sup']?.toString(),
        bSup: j['b_sup']?.toString(),
        show: j['show'] == true,
      );
}
