import 'package:flutter/material.dart';

import '../models/match.dart';
import '../theme/broadcast_court.dart';
import '../utils/format.dart';

/// TV-style scoreboard rendered from server-computed `score_cells` and
/// `point_display` — the app never computes tennis scoring itself.
class Scoreboard extends StatelessWidget {
  const Scoreboard(this.match, {super.key, this.compact = false});

  final TennisMatch match;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final sb = Theme.of(context).extension<ScoreboardColors>()!;
    return Container(
      decoration: BoxDecoration(
        color: sb.background,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.12),
            blurRadius: 16,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      padding: EdgeInsets.all(compact ? 10 : 16),
      child: Column(
        children: [
          _row(context, sb, teamIndex: 0),
          Divider(height: compact ? 8 : 12, color: sb.text.withValues(alpha: 0.08)),
          _row(context, sb, teamIndex: 1),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, ScoreboardColors sb, {required int teamIndex}) {
    final isA = teamIndex == 0;
    final label = isA ? match.teamALabel : match.teamBLabel;
    final serving = match.scoreState.serving == teamIndex &&
        match.scoreState.initialServerSet &&
        !match.isFinished;
    final isWinner = match.scoreState.winner == teamIndex;
    final teamColor = isA ? sb.teamA : sb.teamB;
    final points = isA ? match.pointDisplay['a'] : match.pointDisplay['b'];

    final parsed = parseLK(label);

    final cells = <Widget>[];
    for (final cell in match.scoreCells) {
      final main = isA ? cell.a : cell.b;
      final sup = isA ? cell.aSup : cell.bSup;
      cells.add(_setCell(sb, cell.show ? main : '', sup, compact));
    }

    return Row(
      children: [
        // Serve dot
        SizedBox(
          width: 14,
          child: serving
              ? Icon(Icons.circle, size: 9, color: sb.serveDot)
              : const SizedBox.shrink(),
        ),
        // Name (+ LK badge)
        Expanded(
          child: Row(
            children: [
              Flexible(
                child: Text(
                  parsed.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: BC.display(TextStyle(
                    fontSize: compact ? 15 : 18,
                    fontWeight: FontWeight.w700,
                    color: isWinner ? sb.accent : sb.text,
                  )),
                ),
              ),
              if (parsed.lk != null) ...[
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                  decoration: BoxDecoration(
                    color: teamColor.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text('LK ${parsed.lk}',
                      style: BC.score(TextStyle(fontSize: 10, color: teamColor))),
                ),
              ],
              if (isWinner) ...[
                const SizedBox(width: 6),
                Icon(Icons.check_circle, size: 14, color: sb.accent),
              ],
            ],
          ),
        ),
        ...cells,
        // Current points cell
        _pointsCell(sb, points ?? '', compact),
      ],
    );
  }

  Widget _setCell(ScoreboardColors sb, String main, String? sup, bool compact) {
    return SizedBox(
      width: compact ? 24 : 34,
      child: Center(
        child: RichText(
          text: TextSpan(
            text: main,
            style: BC.score(TextStyle(
              fontSize: compact ? 16 : 20,
              fontWeight: FontWeight.w600,
              color: sb.text,
            )),
            children: [
              if (sup != null)
                TextSpan(
                  text: sup,
                  style: BC.score(TextStyle(
                    fontSize: compact ? 9 : 11,
                    color: sb.text.withValues(alpha: 0.6),
                  )),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _pointsCell(ScoreboardColors sb, String points, bool compact) {
    return Container(
      width: compact ? 40 : 56,
      alignment: Alignment.center,
      padding: const EdgeInsets.symmetric(vertical: 2),
      decoration: BoxDecoration(
        color: sb.accent.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        points,
        style: BC.score(TextStyle(
          fontSize: compact ? 18 : 24,
          fontWeight: FontWeight.w700,
          color: sb.text,
        )),
      ),
    );
  }
}
