// Helpers ported from static/js/common.js so mobile/web match the site.

class PlayerName {
  final String name;
  final String? lk; // Leistungsklasse, e.g. "23"
  const PlayerName(this.name, this.lk);
}

final RegExp _lkPattern = RegExp(r'^(.*?)\s*\(LK\s+([^)]+)\)$');

/// "John Doe (LK 2)" -> PlayerName("John Doe", "2").
PlayerName parseLK(String? fullName) {
  if (fullName == null || fullName.isEmpty) {
    return PlayerName(fullName ?? '', null);
  }
  final m = _lkPattern.firstMatch(fullName);
  if (m != null) {
    return PlayerName(m.group(1)!.trim(), m.group(2));
  }
  return PlayerName(fullName, null);
}

String stripLK(String? fullName) => parseLK(fullName).name;

/// 323 -> "5m 23s"; 4500 -> "1h 15m".
String formatElapsed(int totalSeconds) {
  if (totalSeconds < 0) totalSeconds = 0;
  final h = totalSeconds ~/ 3600;
  final m = (totalSeconds % 3600) ~/ 60;
  final s = totalSeconds % 60;
  if (h > 0) return '${h}h ${m.toString().padLeft(2, '0')}m';
  return '${m}m ${s.toString().padLeft(2, '0')}s';
}
