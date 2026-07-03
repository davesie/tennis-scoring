import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// "Broadcast Court" design system, ported from static/css/style.css.
/// Colours, fonts and the scoreboard layer for light and dark.
class BC {
  BC._();

  // Brand palette (light)
  static const bgLight = Color(0xFFF7F5EE);
  static const textLight = Color(0xFF1A1917);
  static const teamALight = Color(0xFF1B4FA8);
  static const teamBLight = Color(0xFFD44030);
  static const mutedLight = Color(0xFF7A7672);
  static const borderLight = Color(0xFFDDD9D0);

  // Brand palette (dark)
  static const bgDark = Color(0xFF131210);
  static const textDark = Color(0xFFF0EDE8);
  static const teamADark = Color(0xFF3D72D9);
  static const teamBDark = Color(0xFFE05545);
  static const mutedDark = Color(0xFF8A8782);
  static const borderDark = Color(0xFF2E2C28);

  // Shared accent: tennis-ball lime
  static const accent = Color(0xFFC6EF3E);

  // Match scoreboard layer (light)
  static const scoreboardBgLight = Color(0xFFFFFFFF);
  static const scoreboardTextLight = Color(0xFF1A1A1A);
  static const scoreboardAccentLight = Color(0xFFD4A017); // gold serve dot

  // Match scoreboard layer (dark)
  static const scoreboardBgDark = Color(0xFF16161A);
  static const scoreboardTextDark = Color(0xFFF0EDE8);
  static const scoreboardAccentDark = accent;

  // Fonts
  static TextStyle display([TextStyle? base]) =>
      GoogleFonts.barlowCondensed(textStyle: base);
  static TextStyle score([TextStyle? base]) =>
      GoogleFonts.chakraPetch(textStyle: base);
  static TextStyle body([TextStyle? base]) =>
      GoogleFonts.dmSans(textStyle: base);
}

/// Extra scoreboard colours attached to the theme so widgets can read them.
@immutable
class ScoreboardColors extends ThemeExtension<ScoreboardColors> {
  final Color background;
  final Color text;
  final Color serveDot;
  final Color teamA;
  final Color teamB;
  final Color accent;

  const ScoreboardColors({
    required this.background,
    required this.text,
    required this.serveDot,
    required this.teamA,
    required this.teamB,
    required this.accent,
  });

  @override
  ScoreboardColors copyWith({
    Color? background,
    Color? text,
    Color? serveDot,
    Color? teamA,
    Color? teamB,
    Color? accent,
  }) =>
      ScoreboardColors(
        background: background ?? this.background,
        text: text ?? this.text,
        serveDot: serveDot ?? this.serveDot,
        teamA: teamA ?? this.teamA,
        teamB: teamB ?? this.teamB,
        accent: accent ?? this.accent,
      );

  @override
  ScoreboardColors lerp(ScoreboardColors? other, double t) {
    if (other == null) return this;
    return ScoreboardColors(
      background: Color.lerp(background, other.background, t)!,
      text: Color.lerp(text, other.text, t)!,
      serveDot: Color.lerp(serveDot, other.serveDot, t)!,
      teamA: Color.lerp(teamA, other.teamA, t)!,
      teamB: Color.lerp(teamB, other.teamB, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
    );
  }
}

ThemeData buildLightTheme() {
  final scheme = const ColorScheme.light(
    primary: BC.teamALight,
    secondary: BC.teamBLight,
    surface: BC.bgLight,
  ).copyWith(surfaceTint: Colors.transparent);
  final base = ThemeData(useMaterial3: true, colorScheme: scheme);
  return base.copyWith(
    scaffoldBackgroundColor: BC.bgLight,
    textTheme: GoogleFonts.dmSansTextTheme(base.textTheme)
        .apply(bodyColor: BC.textLight, displayColor: BC.textLight),
    dividerColor: BC.borderLight,
    extensions: const [
      ScoreboardColors(
        background: BC.scoreboardBgLight,
        text: BC.scoreboardTextLight,
        serveDot: BC.scoreboardAccentLight,
        teamA: BC.teamALight,
        teamB: BC.teamBLight,
        accent: BC.accent,
      ),
    ],
  );
}

ThemeData buildDarkTheme() {
  final scheme = const ColorScheme.dark(
    primary: BC.teamADark,
    secondary: BC.teamBDark,
    surface: BC.bgDark,
  ).copyWith(surfaceTint: Colors.transparent);
  final base = ThemeData(useMaterial3: true, colorScheme: scheme);
  return base.copyWith(
    scaffoldBackgroundColor: BC.bgDark,
    textTheme: GoogleFonts.dmSansTextTheme(base.textTheme)
        .apply(bodyColor: BC.textDark, displayColor: BC.textDark),
    dividerColor: BC.borderDark,
    extensions: const [
      ScoreboardColors(
        background: BC.scoreboardBgDark,
        text: BC.scoreboardTextDark,
        serveDot: BC.scoreboardAccentDark,
        teamA: BC.teamADark,
        teamB: BC.teamBDark,
        accent: BC.accent,
      ),
    ],
  );
}
