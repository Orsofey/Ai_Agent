// Темы как в приложении на ПК (static/themes.css): те же цвета, фон со свечением, стеклянные карточки.
import 'package:flutter/material.dart';

import 'ornaments.dart';

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
  'gzhel': Palette('gzhel', 'Гжель',
      bg: Color(0xFFF6F9FF), surface: Color(0xC2FFFFFF), surfaceStrong: Color(0xFFFFFFFF), text: Color(0xFF0F2257),
      muted: Color(0xFF566A9A), accent: Color(0xFF1A4FC4), accent2: Color(0xFFC29A45), onAccent: Color(0xFFFFFFFF),
      border: Color(0x331B40A0), chip: Color(0x0F1E50BE), bad: Color(0xFFC8324A),
      glows: [Color(0x333B72E6), Color(0x22C29A45), Color(0x2A1A4FC4)], dark: false),
  'slavic': Palette('slavic', 'Славянская',
      bg: Color(0xFF0C0605), surface: Color(0xC7160B08), surfaceStrong: Color(0xFF1C0E0A), text: Color(0xFFF8EAD0),
      muted: Color(0xFFC6A67A), accent: Color(0xFFE7B545), accent2: Color(0xFFD2342A), onAccent: Color(0xFF1A0B04),
      border: Color(0x57D6A43A), chip: Color(0x14D6A43A), bad: Color(0xFFFF5A4A),
      glows: [Color(0x55BE281E), Color(0x33E7B545), Color(0x22D2342A)]),
  'glass': Palette('glass', 'Стекло',
      bg: Color(0xFFF3EEE7), surface: Color(0x8CFFFFFF), surfaceStrong: Color(0xFFFBF9F6), text: Color(0xFF1C2033),
      muted: Color(0xFF686D82), accent: Color(0xFF6A5CFF), accent2: Color(0xFFE061D4), onAccent: Color(0xFFFFFFFF),
      border: Color(0xD9FFFFFF), chip: Color(0x80FFFFFF), bad: Color(0xFFE0445E),
      glows: [Color(0x8CFFC496), Color(0x73D6AAFF), Color(0x8096D6FF)], dark: false),
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
        if (palette.id == 'glass') ...glassShapes(),
        if (OrnamentStyle.of(palette.id) case final style?) ...[
          // Букет в правом нижнем углу и малый — в левом верхнем, как на ПК.
          Positioned(right: -12, bottom: 40, width: 260, height: 260,
              child: IgnorePointer(child: Opacity(opacity: .55, child: CustomPaint(painter: BouquetPainter(style))))),
          Positioned(left: -10, top: 60, width: 150, height: 150,
              child: IgnorePointer(child: Opacity(opacity: .3,
                  child: Transform.rotate(angle: 3.14159, child: CustomPaint(painter: BouquetPainter(style)))))),
          Positioned(left: 0, right: 0, top: 0, height: palette.id == 'gzhel' ? 12 : 33,
              child: IgnorePointer(child: CustomPaint(painter: BandPainter(palette.id)))),
        ],
        Positioned.fill(child: child),
      ]),
    );
  }

  /// Парящие стеклянные фигуры темы «Стекло» — как на ПК: по краям, с бликом и цветной тенью.
  static List<Widget> glassShapes() {
    const shapes = [
      // left, top, right, bottom, size, angle, colors, radius
      (-18.0, 70.0, null, null, 96.0, -0.3, [Color(0xFFFF6A3D), Color(0xFFFF9D4A), Color(0xD9FFD66E)], 0.5),
      (null, 40.0, -14.0, null, 84.0, 0.25, [Color(0xF2F6AAEE), Color(0xFFB46CF0), Color(0xFF7B3FD8)], 0.26),
      (null, null, -20.0, 170.0, 104.0, -0.2, [Color(0xF27EE8FF), Color(0xE6A096FF), Color(0xFF4A7DFF)], 0.24),
      (-16.0, null, null, 110.0, 72.0, 0.35, [Color(0xFFD9FF7A), Color(0xFF7FD65A), Color(0xFF1F9A4B)], 0.22),
      (130.0, 8.0, null, null, 44.0, 0.5, [Color(0x8CFFFFFF), Color(0x33FFFFFF), Color(0x1FFFFFFF)], 0.3),
    ];
    return [
      for (final (left, top, right, bottom, size, angle, colors, round) in shapes)
        Positioned(left: left, top: top, right: right, bottom: bottom, width: size, height: size,
            child: IgnorePointer(child: Transform.rotate(angle: angle, child: GlassShape(colors: colors, round: round)))),
    ];
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

class GlassShape extends StatelessWidget {
  const GlassShape({super.key, required this.colors, required this.round});

  final List<Color> colors;
  final double round;

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, box) {
        final radius = BorderRadius.circular(box.maxWidth * round);
        return DecoratedBox(
          decoration: BoxDecoration(
            borderRadius: radius,
            gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: colors),
            border: Border.all(color: const Color(0xCCFFFFFF), width: 1.5),
            boxShadow: [BoxShadow(color: colors.last.withValues(alpha: 0.35), blurRadius: 30, offset: const Offset(0, 18),
                spreadRadius: -10)],
          ),
          child: Align(alignment: const Alignment(-0.3, -0.55), child: FractionallySizedBox(widthFactor: 0.6, heightFactor: 0.3,
              child: DecoratedBox(decoration: BoxDecoration(borderRadius: radius,
                  gradient: const LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter,
                      colors: [Color(0xB3FFFFFF), Color(0x00FFFFFF)]))))),
        );
      });
}

/// Сфера ассистента — как на ПК: градиент акцентных цветов, пульсирует во время записи.
class Orb extends StatelessWidget {
  const Orb({super.key, required this.palette, required this.active, this.size = 150});

  final Palette palette;
  final bool active;
  final double size;

  @override
  Widget build(BuildContext context) {
    final style = OrnamentStyle.of(palette.id);
    if (style != null) {
      final porcelain = palette.id == 'gzhel';
      final rim1 = porcelain ? Colors.white : palette.bg;
      return AnimatedContainer(
        duration: const Duration(milliseconds: 400),
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(center: const Alignment(-0.3, -0.45), radius: 0.9,
              colors: porcelain
                  ? const [Colors.white, Color(0xFFF5F8FF), Color(0xFFDDE7FB), Color(0xFFAEC2EE)]
                  : const [Color(0xFF3A1A0E), Color(0xFF1A0906), Color(0xFF0C0605)]),
          border: Border.all(color: palette.accent2, width: 1.5),
          boxShadow: [
            BoxShadow(color: rim1, spreadRadius: 4),
            BoxShadow(color: porcelain ? palette.accent : palette.accent2, spreadRadius: 5.5),
            BoxShadow(color: (active ? palette.bad : palette.accent).withValues(alpha: active ? 0.6 : 0.35),
                blurRadius: active ? 60 : 34, spreadRadius: active ? 10 : 4),
          ],
        ),
        child: CustomPaint(painter: OrbPainter(style)),
      );
    }
    if (palette.id == 'glass') {
      // Радужная стеклянная сфера с бликом.
      return AnimatedContainer(
        duration: const Duration(milliseconds: 400),
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: const RadialGradient(colors: [Color(0xFFF4ECFF), Color(0xFFD9D0FF)]),
          border: Border.all(color: const Color(0xD9FFFFFF), width: 1.5),
          boxShadow: [BoxShadow(color: (active ? palette.bad : palette.accent).withValues(alpha: active ? 0.55 : 0.4),
              blurRadius: active ? 60 : 40, spreadRadius: active ? 8 : 0, offset: const Offset(0, 14))],
        ),
        child: ClipOval(child: Stack(fit: StackFit.expand, children: [
          for (final (x, y, color, r) in const [
            (-0.48, -0.32, Color(0xF2FFB06E), 0.62), (0.56, -0.4, Color(0xF26FCFFF), 0.66),
            (0.4, 0.56, Color(0xF2B98CFF), 0.7), (-0.48, 0.52, Color(0xE6FF78B6), 0.62),
            (0.04, 0.04, Color(0xB386F0B4), 0.5), (-0.36, -0.56, Color(0xF2FFFFFF), 0.34),
          ])
            DecoratedBox(decoration: BoxDecoration(gradient: RadialGradient(center: Alignment(x, y), radius: r,
                colors: [color, color.withValues(alpha: 0)]))),
        ])),
      );
    }
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
