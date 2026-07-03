import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persists the account bearer token and the active scorer token.
///
/// Uses [FlutterSecureStorage] which is keychain/keystore-backed on mobile and
/// falls back to a browser-backed store on web — acceptable for session
/// tokens. The rest of the app talks to this abstraction, never the platform.
class AuthStore {
  AuthStore(this._storage);

  final FlutterSecureStorage _storage;

  static const _kBearer = 'bearer_token';
  static const _kScorer = 'scorer_token';

  String? _bearerToken;
  String? _scorerToken;

  String? get bearerToken => _bearerToken;
  String? get scorerToken => _scorerToken;

  Future<void> load() async {
    _bearerToken = await _storage.read(key: _kBearer);
    _scorerToken = await _storage.read(key: _kScorer);
  }

  Future<void> setBearerToken(String? token) async {
    _bearerToken = token;
    if (token == null) {
      await _storage.delete(key: _kBearer);
    } else {
      await _storage.write(key: _kBearer, value: token);
    }
  }

  Future<void> setScorerToken(String? token) async {
    _scorerToken = token;
    if (token == null) {
      await _storage.delete(key: _kScorer);
    } else {
      await _storage.write(key: _kScorer, value: token);
    }
  }

  Future<void> clear() async {
    _bearerToken = null;
    _scorerToken = null;
    await _storage.delete(key: _kBearer);
    await _storage.delete(key: _kScorer);
  }
}
