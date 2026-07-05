import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../models/match.dart';
import '../models/match_day.dart';
import '../providers.dart';
import '../services/live_connection.dart';
import '../theme/broadcast_court.dart';
import '../theme/theme_controller.dart';
import '../widgets/connection_dot.dart';
import '../widgets/scoreboard.dart';

enum _Source { shareCode, scorerToken, id }

class MatchDayScreen extends ConsumerStatefulWidget {
  const MatchDayScreen._(this.value, this._source, {required this.canScore});

  factory MatchDayScreen.spectator(String code) =>
      MatchDayScreen._(code, _Source.shareCode, canScore: false);
  factory MatchDayScreen.scorer(String token) =>
      MatchDayScreen._(token, _Source.scorerToken, canScore: true);
  factory MatchDayScreen.byId(String id) =>
      MatchDayScreen._(id, _Source.id, canScore: true);

  final String value;
  final _Source _source;
  final bool canScore;

  @override
  ConsumerState<MatchDayScreen> createState() => _MatchDayScreenState();
}

class _MatchDayScreenState extends ConsumerState<MatchDayScreen> {
  MatchDay? _day;
  final Map<String, TennisMatch> _matches = {};
  LiveConnection? _live;
  ConnectionStatus _status = ConnectionStatus.connecting;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = ref.read(apiClientProvider);
    try {
      final MatchDayBundle bundle;
      switch (widget._source) {
        case _Source.shareCode:
          bundle = await api.getMatchDayByShareCode(widget.value);
          break;
        case _Source.scorerToken:
          bundle = await api.getMatchDayByScorerToken(widget.value);
          break;
        case _Source.id:
          bundle = await api.getMatchDay(widget.value);
          break;
      }
      _day = bundle.matchDay;
      for (final m in bundle.matches) {
        _matches[m.id] = m;
      }
      _connectLive(bundle.matchDay.id);
      setState(() => _loading = false);
    } catch (e) {
      setState(() {
        _error = 'Could not load this match day.';
        _loading = false;
      });
    }
  }

  void _connectLive(String matchDayId) {
    final live = LiveConnection.matchDay(matchDayId);
    _live = live;
    live.status.listen((s) {
      if (mounted) setState(() => _status = s);
    });
    live.messages.listen((msg) {
      if (!mounted) return;
      final type = msg['type'];
      if (type == 'match_update' && msg['match'] != null) {
        final m = TennisMatch.fromJson(
            (msg['match'] as Map).cast<String, dynamic>());
        setState(() => _matches[m.id] = m);
      } else if (type == 'initial' && msg['matches'] is List) {
        setState(() {
          for (final raw in (msg['matches'] as List)) {
            final m = TennisMatch.fromJson((raw as Map).cast<String, dynamic>());
            _matches[m.id] = m;
          }
        });
      }
    });
    live.connect();
  }

  @override
  void dispose() {
    _live?.dispose();
    super.dispose();
  }

  List<TennisMatch> get _ordered {
    final list = _matches.values.toList()
      ..sort((a, b) {
        final byType = (a.isDoubles ? 1 : 0).compareTo(b.isDoubles ? 1 : 0);
        if (byType != 0) return byType;
        return (a.matchNumber ?? 0).compareTo(b.matchNumber ?? 0);
      });
    return list;
  }

  int get _teamAWins =>
      _matches.values.where((m) => m.scoreState.winner == 0).length;
  int get _teamBWins =>
      _matches.values.where((m) => m.scoreState.winner == 1).length;

  void _openMatch(TennisMatch m) {
    if (widget.canScore) {
      // Scorer token already stored (scoreday) or owner is authed.
      context.push('/match/${m.id}?score=1');
    } else {
      context.push('/watch/${m.shareCode}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final mode = ref.watch(themeControllerProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(_day?.name ?? 'Match Day',
            style: BC.display(const TextStyle(fontWeight: FontWeight.w700))),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Center(child: ConnectionDot(_status)),
          ),
          IconButton(
            icon: Icon(mode == ThemeMode.dark
                ? Icons.light_mode_outlined
                : Icons.dark_mode_outlined),
            onPressed: () => ref.read(themeControllerProvider.notifier).toggle(),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!))
              : _body(context),
    );
  }

  Widget _body(BuildContext context) {
    final ordered = _ordered;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _teamScorePill(context),
            const SizedBox(height: 16),
            for (final m in ordered) ...[
              _MatchCard(
                match: m,
                canScore: widget.canScore,
                onTap: () => _openMatch(m),
              ),
              const SizedBox(height: 12),
            ],
          ],
        ),
      ),
    );
  }

  Widget _teamScorePill(BuildContext context) {
    final sb = Theme.of(context).extension<ScoreboardColors>()!;
    final day = _day;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: BoxDecoration(
        color: sb.background,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _teamScore(day?.teamAName ?? 'Team A', _teamAWins, sb.teamA),
          Text('–', style: BC.score(TextStyle(fontSize: 22, color: sb.text))),
          _teamScore(day?.teamBName ?? 'Team B', _teamBWins, sb.teamB),
        ],
      ),
    );
  }

  Widget _teamScore(String name, int wins, Color color) => Column(
        children: [
          Text(name,
              style: BC.display(TextStyle(
                  fontSize: 18, fontWeight: FontWeight.w700, color: color))),
          Text('$wins',
              style: BC.score(const TextStyle(
                  fontSize: 30, fontWeight: FontWeight.w700))),
        ],
      );
}

class _MatchCard extends StatelessWidget {
  const _MatchCard(
      {required this.match, required this.canScore, required this.onTap});

  final TennisMatch match;
  final bool canScore;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    String status;
    Color statusColor;
    if (match.isFinished) {
      status = 'FINAL';
      statusColor = const Color(0xFF3FBF6B);
    } else if (match.isLive) {
      status = 'LIVE';
      statusColor = const Color(0xFFD44030);
    } else {
      status = 'UPCOMING';
      statusColor = Theme.of(context).disabledColor;
    }

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '${match.isDoubles ? 'Doubles' : 'Singles'} '
                '${match.matchNumber ?? ''}'.trim(),
                style: Theme.of(context).textTheme.labelLarge,
              ),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: statusColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(status,
                    style: BC.score(TextStyle(fontSize: 11, color: statusColor))),
              ),
              const Spacer(),
              if (canScore && !match.isFinished)
                Text('Enter score →',
                    style: Theme.of(context).textTheme.labelMedium),
            ],
          ),
          const SizedBox(height: 6),
          Scoreboard(match, compact: true),
        ],
      ),
    );
  }
}
