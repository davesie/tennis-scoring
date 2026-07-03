import 'package:flutter/foundation.dart' show kIsWeb;

/// Resolves the backend base URL for REST and WebSocket in one place.
///
/// - **Web:** same origin as the served page (via [Uri.base]), so the build
///   automatically targets whatever host serves it and no CORS is needed.
/// - **Mobile:** an absolute base URL supplied at build time with
///   `--dart-define=API_BASE_URL=https://your-host`. Falls back to a sensible
///   dev default.
class ApiConfig {
  ApiConfig._();

  static const String _defineBaseUrl =
      String.fromEnvironment('API_BASE_URL', defaultValue: '');

  /// Absolute HTTP(S) base, e.g. `https://tennis.example.com`.
  static String get httpBase {
    if (kIsWeb) {
      final origin = Uri.base;
      return '${origin.scheme}://${origin.authority}';
    }
    if (_defineBaseUrl.isNotEmpty) return _defineBaseUrl;
    // Dev default: Android emulator maps host loopback to 10.0.2.2.
    return 'http://10.0.2.2:8000';
  }

  /// WebSocket base, derived from [httpBase] (http->ws, https->wss).
  static String get wsBase {
    final u = Uri.parse(httpBase);
    final scheme = u.scheme == 'https' ? 'wss' : 'ws';
    return '$scheme://${u.authority}';
  }

  static Uri http(String path) => Uri.parse('$httpBase$path');
  static Uri ws(String path) => Uri.parse('$wsBase$path');
}
