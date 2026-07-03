import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/match.dart';
import '../models/match_stats.dart';
import '../providers.dart';
import '../services/live_connection.dart';
import '../theme/broadcast_court.dart';
import '../utils/format.dart';
import '../widgets/connection_dot.dart';
import '../widgets/scoreboard.dart';

class MatchScreen extends ConsumerStatefulWidget {
  const MatchScreen._(this.value, this.byShareCode, {required this.canScore});

  factory MatchScreen.spectator(String shareCode) =>
      MatchScreen._(shareCode, true, canScore: false);
  factory MatchScreen.byId(String id, {bool canScore = false}) =>
      MatchScreen._(id, false, canScore: canScore);

  final String value;
  final bool byShareCode;
  final bool canScore;

  @override
  ConsumerState<MatchScreen> createState() => _MatchScreenState();
}

class _MatchScreenState extends ConsumerState<MatchScreen> {
  TennisMatch? _match;
  LiveConnection? _live;
  ConnectionStatus _status = ConnectionStatus.connecting;
  Timer? _timer;
  String _elapsed = '';
  bool _loading = true;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = ref.read(apiClientProvider);
    try {
      final m = widget.byShareCode
          ? await api.getMatchByShareCode(widget.value)
          : await api.getMatch(widget.value);
      setState(() {
        _match = m;
        _loading = false;
      });
      _connectLive(m.id);
      _startTimer();
    } catch (_) {
      setState(() {
        _error = 'Could not load this match.';
        _loading = false;
      });
    }
  }

  void _connectLive(String matchId) {
    final live = LiveConnection.match(matchId);
    _live = live;
    live.status.listen((s) {
      if (mounted) setState(() => _status = s);
    });
    live.messages.listen((msg) {
      if (!mounted) return;
      if ((msg['type'] == 'score_update' || msg['type'] == 'initial') &&
          msg['match'] != null) {
        setState(() => _match =
            TennisMatch.fromJson((msg['match'] as Map).cast<String, dynamic>()));
      }
    });
    live.connect();
  }

  void _startTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      final m = _match;
      if (m == null) return;
      if (m.isFinished) {
        setState(() => _elapsed = m.durationFormatted ?? '');
        return;
      }
      if (m.startedAt != null) {
        final secs = DateTime.now().difference(m.startedAt!).inSeconds;
        setState(() => _elapsed = formatElapsed(secs));
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _live?.dispose();
    super.dispose();
  }

  // ---- Scorer actions ----

  Future<void> _guard(Future<TennisMatch> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final updated = await action();
      if (mounted) setState(() => _match = updated);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Action failed — check connection.')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _scorePoint(int team) async {
    final m = _match!;
    final serverBefore = m.scoreState.serving;
    HapticFeedback.selectionClick();
    await _guard(() => ref.read(apiClientProvider).scorePoint(m.id, team));
    final after = _match;
    if (after != null && !after.isFinished) {
      _showTagSheet(pointWinner: team, serverWon: team == serverBefore);
    }
  }

  Future<void> _scoreGame(int team) async {
    HapticFeedback.mediumImpact();
    await _guard(() => ref.read(apiClientProvider).scoreGame(_match!.id, team));
  }

  Future<void> _setServer(int team) =>
      _guard(() => ref.read(apiClientProvider).setServer(_match!.id, team));

  Future<void> _undo() async {
    HapticFeedback.lightImpact();
    await _guard(() => ref.read(apiClientProvider).undo(_match!.id));
  }

  Future<void> _reset() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Reset match?'),
        content: const Text('This clears all scoring for this match.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Reset')),
        ],
      ),
    );
    if (ok == true) {
      HapticFeedback.heavyImpact();
      await _guard(() => ref.read(apiClientProvider).reset(_match!.id));
    }
  }

  void _showTagSheet({required int pointWinner, required bool serverWon}) {
    final m = _match!;
    final winnerName =
        pointWinner == 0 ? stripLK(m.teamALabel) : stripLK(m.teamBLabel);
    final outcomes = <MapEntry<String, String>>[
      if (serverWon) const MapEntry('ace', 'Ace'),
      if (!serverWon) const MapEntry('double_fault', 'Double Fault'),
      const MapEntry('winner', 'Winner'),
      const MapEntry('unforced_error', 'Unforced Error'),
      const MapEntry('forced_error', 'Forced Error'),
    ];
    Timer? auto;
    showModalBottomSheet<void>(
      context: context,
      builder: (c) {
        auto = Timer(const Duration(seconds: 12), () {
          if (Navigator.canPop(c)) Navigator.pop(c);
        });
        return Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Point to $winnerName — how?',
                  style: BC.display(const TextStyle(
                      fontSize: 18, fontWeight: FontWeight.w700))),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final o in outcomes)
                    OutlinedButton(
                      onPressed: () {
                        ref
                            .read(apiClientProvider)
                            .tagOutcome(m.id, o.key)
                            .catchError((_) {});
                        Navigator.pop(c);
                      },
                      child: Text(o.value),
                    ),
                  TextButton(
                      onPressed: () => Navigator.pop(c),
                      child: const Text('Skip')),
                ],
              ),
            ],
          ),
        );
      },
    ).whenComplete(() => auto?.cancel());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.canScore ? 'Score match' : 'Watch match',
            style: BC.display(const TextStyle(fontWeight: FontWeight.w700))),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Center(child: ConnectionDot(_status)),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!))
              : _content(context),
    );
  }

  Widget _content(BuildContext context) {
    final m = _match!;
    final needsServer = widget.canScore &&
        !m.scoreState.initialServerSet &&
        !m.isFinished;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_elapsed.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_elapsed,
                    textAlign: TextAlign.center,
                    style: BC.score(TextStyle(
                        color: Theme.of(context).disabledColor))),
              ),
            Scoreboard(m),
            const SizedBox(height: 8),
            _stateLine(context, m),
            if (m.isFinished) _winnerBanner(context, m),
            if (needsServer) _serverPicker(context, m),
            if (widget.canScore && !m.isFinished && m.scoreState.initialServerSet)
              _scoringControls(context, m),
            if (!widget.canScore && !m.isFinished) _watchingNote(context),
            if (m.stats != null) _statsPanel(context, m),
          ],
        ),
      ),
    );
  }

  Widget _stateLine(BuildContext context, TennisMatch m) {
    String? text;
    final s = m.scoreState;
    if (s.isSuperTiebreak) {
      text = 'SUPER TIEBREAK (First to 10)';
    } else if (s.isTiebreak) {
      text = 'TIEBREAK';
    } else if (s.deuceAdvantage != null) {
      text = 'ADVANTAGE';
    } else if (s.points.length == 2 && s.points[0] >= 3 && s.points[1] >= 3) {
      text = 'DEUCE';
    }
    if (text == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Text(text,
          textAlign: TextAlign.center,
          style: BC.score(TextStyle(
              letterSpacing: 1.5,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.secondary))),
    );
  }

  Widget _winnerBanner(BuildContext context, TennisMatch m) {
    final w = m.scoreState.winner!;
    final name = w == 0 ? stripLK(m.teamALabel) : stripLK(m.teamBLabel);
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 12),
      padding: const EdgeInsets.symmetric(vertical: 18),
      width: double.infinity,
      decoration: BoxDecoration(
        color: BC.accent,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text('${name.toUpperCase()} WINS!',
          textAlign: TextAlign.center,
          style: BC.display(const TextStyle(
              fontSize: 26,
              fontWeight: FontWeight.w800,
              color: Color(0xFF12140A)))),
    );
  }

  Widget _serverPicker(BuildContext context, TennisMatch m) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Text('Who serves first?',
                style: BC.display(const TextStyle(
                    fontSize: 18, fontWeight: FontWeight.w700))),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: FilledButton(
                    onPressed: _busy ? null : () => _setServer(0),
                    child: Text(stripLK(m.teamALabel)),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: _busy ? null : () => _setServer(1),
                    child: Text(stripLK(m.teamBLabel)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _scoringControls(BuildContext context, TennisMatch m) {
    final sb = Theme.of(context).extension<ScoreboardColors>()!;
    final inTiebreak = m.scoreState.isTiebreak || m.scoreState.isSuperTiebreak;
    Widget bigButton(String label, String sub, Color color, VoidCallback onTap) {
      return Expanded(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Material(
            color: color,
            borderRadius: BorderRadius.circular(12),
            child: InkWell(
              onTap: _busy ? null : onTap,
              borderRadius: BorderRadius.circular(12),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 22),
                alignment: Alignment.center,
                child: Column(
                  children: [
                    Text(label,
                        style: BC.display(const TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                            color: Colors.white))),
                    Text(sub,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: Colors.white70)),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }

    return Column(
      children: [
        const SizedBox(height: 16),
        Row(
          children: [
            bigButton('POINT', stripLK(m.teamALabel), sb.teamA,
                () => _scorePoint(0)),
            bigButton('POINT', stripLK(m.teamBLabel), sb.teamB,
                () => _scorePoint(1)),
          ],
        ),
        if (!inTiebreak) ...[
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _busy ? null : () => _scoreGame(0),
                  child: Text('Game ${stripLK(m.teamALabel)}'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  onPressed: _busy ? null : () => _scoreGame(1),
                  child: Text('Game ${stripLK(m.teamBLabel)}'),
                ),
              ),
            ],
          ),
        ],
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _busy ? null : _undo,
                icon: const Icon(Icons.undo),
                label: const Text('Undo'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _busy ? null : _reset,
                icon: const Icon(Icons.restart_alt),
                label: const Text('Reset'),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _watchingNote(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Column(
          children: [
            Icon(Icons.visibility_outlined,
                color: Theme.of(context).disabledColor),
            const SizedBox(height: 6),
            const Text('You are watching this match in real time.'),
            Text('Scores update automatically.',
                style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      );

  Widget _statsPanel(BuildContext context, TennisMatch m) {
    final s = m.stats!;
    return Card(
      margin: const EdgeInsets.only(top: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                    child: Text(stripLK(m.teamALabel),
                        style: BC.display(const TextStyle(
                            fontWeight: FontWeight.w700)))),
                Text('Statistics',
                    style: Theme.of(context).textTheme.labelMedium),
                Expanded(
                    child: Text(stripLK(m.teamBLabel),
                        textAlign: TextAlign.right,
                        style: BC.display(const TextStyle(
                            fontWeight: FontWeight.w700)))),
              ],
            ),
            const Divider(),
            _statRows(s),
            const SizedBox(height: 6),
            Text('${s.tagged}/${s.total} points tagged',
                style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }

  Widget _statRows(MatchStats s) {
    Widget row(String label, int a, int b) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            children: [
              SizedBox(width: 44, child: Text('$a', textAlign: TextAlign.center)),
              Expanded(
                  child: Text(label,
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontSize: 12))),
              SizedBox(width: 44, child: Text('$b', textAlign: TextAlign.center)),
            ],
          ),
        );
    return Column(
      children: [
        row('Points won', s.a.pointsWon, s.b.pointsWon),
        row('Aces', s.a.aces, s.b.aces),
        row('Double faults', s.a.doubleFaults, s.b.doubleFaults),
        row('Winners', s.a.winners, s.b.winners),
        row('Unforced errors', s.a.unforcedErrors, s.b.unforcedErrors),
        row('Forced errors', s.a.forcedErrors, s.b.forcedErrors),
      ],
    );
  }
}
