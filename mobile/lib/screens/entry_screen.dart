import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers.dart';
import '../theme/broadcast_court.dart';
import '../theme/theme_controller.dart';

/// Landing screen: open a scorer/watcher link, or sign in with an account.
class EntryScreen extends ConsumerStatefulWidget {
  const EntryScreen({super.key});

  @override
  ConsumerState<EntryScreen> createState() => _EntryScreenState();
}

class _EntryScreenState extends ConsumerState<EntryScreen> {
  final _link = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _link.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  /// Extract a routable path from a pasted link or raw path.
  /// Recognises /scoreday, /watchday, /matchday, /watch, /match.
  String? _routeFor(String input) {
    var s = input.trim();
    if (s.isEmpty) return null;
    Uri? uri = Uri.tryParse(s);
    final segments = (uri?.pathSegments ?? s.split('/'))
        .where((e) => e.isNotEmpty)
        .toList();
    const known = {'scoreday', 'watchday', 'matchday', 'watch', 'match'};
    for (var i = 0; i < segments.length - 1; i++) {
      if (known.contains(segments[i])) {
        return '/${segments[i]}/${segments[i + 1]}';
      }
    }
    return null;
  }

  void _openLink() {
    final route = _routeFor(_link.text);
    if (route == null) {
      setState(() => _error =
          'Paste a scorer, watcher or match link (e.g. .../scoreday/XXXX).');
      return;
    }
    context.go(route);
  }

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .login(_email.text.trim(), _password.text);
      ref.read(isLoggedInProvider.notifier).state = true;
      if (mounted) {
        setState(() => _error = 'Signed in. Open a match day link to score.');
      }
    } on DioException catch (e) {
      setState(() => _error =
          e.response?.data?['detail']?.toString() ?? 'Login failed.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final mode = ref.watch(themeControllerProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text('Tennis Scoring',
            style: BC.display(const TextStyle(
                fontWeight: FontWeight.w800, fontSize: 22))),
        actions: [
          IconButton(
            tooltip: 'Toggle theme',
            icon: Icon(mode == ThemeMode.dark
                ? Icons.light_mode_outlined
                : Icons.dark_mode_outlined),
            onPressed: () => ref.read(themeControllerProvider.notifier).toggle(),
          ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: ListView(
            padding: const EdgeInsets.all(24),
            shrinkWrap: true,
            children: [
              if (_error != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: BC.accent.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(_error!),
                ),
                const SizedBox(height: 16),
              ],
              Text('Open a match',
                  style: BC.display(const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.w700))),
              const SizedBox(height: 8),
              TextField(
                controller: _link,
                decoration: const InputDecoration(
                  labelText: 'Scorer / watcher / match link',
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.link),
                ),
                onSubmitted: (_) => _openLink(),
              ),
              const SizedBox(height: 10),
              FilledButton.icon(
                onPressed: _openLink,
                icon: const Icon(Icons.open_in_new),
                label: const Text('Open'),
              ),
              const SizedBox(height: 32),
              Text('Sign in',
                  style: BC.display(const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.w700))),
              const SizedBox(height: 4),
              Text('For match-day owners. Watchers and scorers can just use a link.',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 12),
              TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  labelText: 'Email',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _password,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Password',
                  border: OutlineInputBorder(),
                ),
                onSubmitted: (_) => _login(),
              ),
              const SizedBox(height: 10),
              FilledButton(
                onPressed: _busy ? null : _login,
                child: _busy
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('Sign in'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
