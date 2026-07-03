import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';
import 'router.dart';
import 'theme/broadcast_court.dart';
import 'theme/theme_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final container = ProviderContainer();
  // Load persisted tokens before the first frame so auth is ready.
  await container.read(authStoreProvider).load();
  container.read(isLoggedInProvider.notifier).state =
      container.read(authStoreProvider).bearerToken != null;

  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const TennisScoringApp(),
    ),
  );
}

class TennisScoringApp extends ConsumerWidget {
  const TennisScoringApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeControllerProvider);
    return MaterialApp.router(
      title: 'Tennis Scoring',
      debugShowCheckedModeBanner: false,
      theme: buildLightTheme(),
      darkTheme: buildDarkTheme(),
      themeMode: mode,
      routerConfig: router,
    );
  }
}
