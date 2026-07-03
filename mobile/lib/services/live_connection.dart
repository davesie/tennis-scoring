import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/api_config.dart';

enum ConnectionStatus { connecting, connected, reconnecting, disconnected }

/// Wraps a single backend WebSocket (match or match-day feed) with
/// exponential-backoff reconnect. Cross-platform: `web_socket_channel` uses the
/// browser WebSocket on web and dart:io sockets on mobile.
///
/// Mirrors the site's JS client: max 10 attempts, delay capped at 30s.
class LiveConnection {
  LiveConnection.match(String matchId) : _path = '/ws/$matchId';
  LiveConnection.matchDay(String matchDayId)
      : _path = '/ws/matchday/$matchDayId';

  final String _path;

  static const _maxAttempts = 10;

  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  int _attempts = 0;
  bool _disposed = false;
  Timer? _retryTimer;

  final _messages = StreamController<Map<String, dynamic>>.broadcast();
  final _status = StreamController<ConnectionStatus>.broadcast();

  /// Decoded server messages: {type: initial|score_update|match_update, ...}.
  Stream<Map<String, dynamic>> get messages => _messages.stream;
  Stream<ConnectionStatus> get status => _status.stream;

  void connect() {
    if (_disposed) return;
    _emit(_attempts == 0
        ? ConnectionStatus.connecting
        : ConnectionStatus.reconnecting);
    try {
      final channel = WebSocketChannel.connect(ApiConfig.ws(_path));
      _channel = channel;
      _sub = channel.stream.listen(
        _onData,
        onError: (_) => _scheduleReconnect(),
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
      // A successful first frame confirms the connection (see _onData).
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _onData(dynamic raw) {
    _attempts = 0; // healthy connection resets backoff
    _emit(ConnectionStatus.connected);
    try {
      final decoded = jsonDecode(raw as String);
      if (decoded is Map<String, dynamic>) {
        _messages.add(decoded);
      }
    } catch (_) {
      // ignore malformed frames
    }
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    _sub?.cancel();
    _sub = null;
    _channel = null;

    if (_attempts >= _maxAttempts) {
      _emit(ConnectionStatus.disconnected);
      return;
    }
    _attempts++;
    _emit(ConnectionStatus.reconnecting);
    final int delayMs = (1000 * (1 << _attempts)).clamp(1000, 30000).toInt();
    _retryTimer?.cancel();
    _retryTimer = Timer(Duration(milliseconds: delayMs), connect);
  }

  void _emit(ConnectionStatus s) {
    if (!_status.isClosed) _status.add(s);
  }

  Future<void> dispose() async {
    _disposed = true;
    _retryTimer?.cancel();
    await _sub?.cancel();
    await _channel?.sink.close();
    await _messages.close();
    await _status.close();
  }
}
