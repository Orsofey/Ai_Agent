// Темы как в приложении на ПК (static/themes.css): те же цвета, фон со свечением, стеклянные карточки.
import 'package:flutter/material.dart';

class Palette {
  const Palette(this.id, this.title, {required this.bg, required this.surface, required this.surfaceStrong,
      required this.text, required this.muted, required this.accent, required this.accent2, required this.onAccent,
      required this.border, required this.chip, required this.bad, required this.glows, this.dark = true});

  final String id;
  final String title;
  final Color bg, surface, surfaceStrong, text, muted, accent, accent2, onAccent, border, chip, bad;
  final List<Color> glows; // цветные пятна фона («северное сияние», неон…)
  final bool dark;
}

const palettes = <String, Palette>{
  'aurora': Palette('aurora', 'Аврора',
      bg: Color(0xFF040817), surface: Color(0x850E1630), surfaceStrong: Color(0xFF111A38), text: Color(0xFFEAF2FF),
      muted: Color(0xFF97A8CC), accent: Color(0xFF5EF2C2), accent2: Color(0xFF7AA2FF), onAccent: Color(0xFF03141A),
      border: Color(0x2696C8FF), chip: Color(0x0FFFFFFF), bad: Color(0xFFFF6B8B),
      glows: [Color(0x665EF2C2), Color(0x557AA2FF), Color(0x44B388FF)]),
  'cyberpunk': Palette('cyberpunk', 'Киберпанк',
      bg: Color(0xFF07020F), surface: Color(0xCC10041E), surfaceStrong: Color(0xFF1A0630), text: Color(0xFFF7F0FF),
      muted: Color(0xFFB194D0), accent: Color(0xFF00F0FF), accent2: Color(0xFFFF2BD6), onAccent: Color(0xFF07020F),
      border: Color(0x61FF2BD6), chip: Color(0x14FF2BD6), bad: Color(0xFFFF3860),
      glows: [Color(0x66FF2BD6), Color(0x5500F0FF), Color(0x44FFB400)]),
  'sakura': Palette('sakura', 'Сакура',
      bg: Color(0xFFFFF6F8), surface: Color(0xB8FFFFFF), surfaceStrong: Color(0xFFFFFFFF), text: Color(0xFF3F2330),
      muted: Color(0xFF8F6B7A), accent: Color(0xFFE0457B), accent2: Color(0xFF7CC6A4), onAccent: Color(0xFFFFFFFF),
      border: Color(0x38D67896), chip: Color(0x12E5487D), bad: Color(0xFFD63A4A),
      glows: [Color(0x55FFB7CD), Color(0x447CC6A4), Color(0x33FFD6A5)], dark: false),
  'ocean': Palette('ocean', 'Бездна',
      bg: Color(0xFF011018), surface: Color(0x80032634), surfaceStrong: Color(0xFF04303F), text: Color(0xFFDCF9FF),
      muted: Color(0xFF82B8C5), accent: Color(0xFF38F3FF), accent2: Color(0xFF2EE6A6), onAccent: Color(0xFF012028),
      border: Color(0x2B5AE6FF), chip: Color(0x1238F3FF), bad: Color(0xFFFF6F91),
      glows: [Color(0x5538F3FF), Color(0x442EE6A6), Color(0x333A7BFF)]),
  'luxe': Palette('luxe', 'Люкс',
      bg: Color(0xFF0B0906), surface: Color(0xDB16120C), surfaceStrong: Color(0xFF1A150D), text: Color(0xFFF6ECD6),
      muted: Color(0xFFB9A67E), accent: Color(0xFFE0BD6E), accent2: Color(0xFFF5DC9B), onAccent: Color(0xFF1A1206),
      border: Color(0x57D4AF5F), chip: Color(0x14D4AF5F), bad: Color(0xFFE0705C),
      glows: [Color(0x44E0BD6E), Color(0x33F5DC9B), Color(0x22FFFFFF)]),
  'dark': Palette('dark', 'Тёмная',
      bg: Color(0xFF0F141C), surface: Color(0xFF161D28), surfaceStrong: Color(0xFF1B2330), text: Color(0xFFE9EEF6),
      muted: Color(0xFF98A4B6), accent: Color(0xFF5AA8FF), accent2: Color(0xFF7EE0C3), onAccent: Color(0xFF06121F),
      border: Color(0xFF283344), chip: Color(0xFF1D2634), bad: Color(0xFFF87171), glows: []),
  'light': Palette('light', 'Светлая',
      bg: Color(0xFFF3F5F9), surface: Color(0xFFFFFFFF), surfaceStrong: Color(0xFFFFFFFF), text: Color(0xFF16202F),
      muted: Color(0xFF5D6B80), accent: Color(0xFF2563EB), accent2: Color(0xFF0D9488), onAccent: Color(0xFFFFFFFF),
      border: Color(0xFFDDE3EC), chip: Color(0xFFEEF2F8), bad: Color(0xFFDC2626), glows: [], dark: false),
};

Palette paletteOf(String? id) => palettes[id] ?? palettes['aurora']!;

ThemeData themeFor(Palette p) {
  final scheme = ColorScheme(
    brightness: p.dark ? Brightness.dark : Brightness.light,
    primary: p.accent, onPrimary: p.onAccent, secondary: p.accent2, onSecondary: p.onAccent,
    error: p.bad, onError: Colors.white, surface: p.surfaceStrong, onSurface: p.text,
    surfaceContainerHighest: p.chip, outline: p.border,
  );
  final radius = BorderRadius.circular(14);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: Colors.transparent,
    appBarTheme: AppBarTheme(backgroundColor: Colors.transparent, foregroundColor: p.text, elevation: 0,
        scrolledUnderElevation: 0, centerTitle: false),
    cardTheme: CardThemeData(color: p.surface, elevation: 0, margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18), side: BorderSide(color: p.border))),
    inputDecorationTheme: InputDecorationTheme(
      filled: true, fillColor: p.chip, hintStyle: TextStyle(color: p.muted), labelStyle: TextStyle(color: p.muted),
      border: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: p.border)),
      enabledBorder: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: p.border)),
      focusedBorder: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: p.accent, width: 1.5)),
    ),
    filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(backgroundColor: p.accent,
        foregroundColor: p.onAccent, shape: RoundedRectangleBorder(borderRadius: radius),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14))),
    outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(foregroundColor: p.text,
        side: BorderSide(color: p.border), shape: RoundedRectangleBorder(borderRadius: radius),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14))),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.onAccent : p.muted),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? p.accent : p.chip),
    ),
    sliderTheme: SliderThemeData(activeTrackColor: p.accent, thumbColor: p.accent, inactiveTrackColor: p.chip),
    navigationBarTheme: NavigationBarThemeData(backgroundColor: p.surfaceStrong.withValues(alpha: 0.92),
        indicatorColor: p.accent.withValues(alpha: 0.22),
        labelTextStyle: WidgetStatePropertyAll(TextStyle(color: p.text, fontSize: 12))),
    dividerColor: p.border,
    textTheme: Typography.material2021().black.apply(bodyColor: p.text, displayColor: p.text),
  );
}

/// Фон темы: базовый цвет и мягкие цветные свечения, как «сцена» на ПК.
class Scene extends StatelessWidget {
  const Scene({super.key, required this.palette, required this.child});

  final Palette palette;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final glows = palette.glows;
    return DecoratedBox(
      decoration: BoxDecoration(color: palette.bg),
      child: Stack(children: [
        if (glows.isNotEmpty) ...[
          _glow(glows[0], const Alignment(-1.1, -1.0), 1.4),
          if (glows.length > 1) _glow(glows[1], const Alignment(1.2, -0.2), 1.2),
          if (glows.length > 2) _glow(glows[2], const Alignment(-0.4, 1.3), 1.3),
        ],
        Positioned.fill(child: child),
      ]),
    );
  }

  Widget _glow(Color color, Alignment at, double radius) => Positioned.fill(
        child: IgnorePointer(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: RadialGradient(center: at, radius: radius, colors: [color, color.withValues(alpha: 0)]),
            ),
          ),
        ),
      );
}

/// Сфера ассистента — как на ПК: градиент акцентных цветов, пульсирует во время записи.
class Orb extends StatelessWidget {
  const Orb({super.key, required this.palette, required this.active, this.size = 150});

  final Palette palette;
  final bool active;
  final double size;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 400),
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(center: const Alignment(-0.35, -0.4), radius: 0.95,
            colors: [Colors.white.withValues(alpha: 0.85), palette.accent, palette.accent2]),
        boxShadow: [
          BoxShadow(color: (active ? palette.bad : palette.accent).withValues(alpha: active ? 0.7 : 0.45),
              blurRadius: active ? 60 : 38, spreadRadius: active ? 10 : 2),
        ],
      ),
    );
  }
}
