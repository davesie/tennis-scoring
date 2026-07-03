import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'services/api_client.dart';
import 'services/auth_store.dart';

/// Secure storage instance (keychain/keystore on mobile, browser on web).
final secureStorageProvider = Provider<FlutterSecureStorage>(
  (ref) => const FlutterSecureStorage(),
);

/// Token store. `load()` is awaited once at startup (see bootstrap).
final authStoreProvider = Provider<AuthStore>(
  (ref) => AuthStore(ref.watch(secureStorageProvider)),
);

/// REST client, authed via the AuthStore.
final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(ref.watch(authStoreProvider)),
);

/// Whether an account bearer token is present (drives entry-screen UI).
final isLoggedInProvider = StateProvider<bool>((ref) {
  return ref.watch(authStoreProvider).bearerToken != null;
});
