import 'package:flutter/material.dart';

import '../services/live_connection.dart';

/// Small coloured dot reflecting the WebSocket status
/// (green connected, amber reconnecting, red disconnected).
class ConnectionDot extends StatelessWidget {
  const ConnectionDot(this.status, {super.key});

  final ConnectionStatus status;

  @override
  Widget build(BuildContext context) {
    late final Color color;
    late final String label;
    switch (status) {
      case ConnectionStatus.connected:
        color = const Color(0xFF3FBF6B);
        label = 'Live';
        break;
      case ConnectionStatus.connecting:
      case ConnectionStatus.reconnecting:
        color = const Color(0xFFE0A800);
        label = 'Reconnecting';
        break;
      case ConnectionStatus.disconnected:
        color = const Color(0xFFD44030);
        label = 'Offline';
        break;
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 9,
          height: 9,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Text(label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(color: color)),
      ],
    );
  }
}
