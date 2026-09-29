// Темы как в приложении на ПК (static/themes.css): те же цвета, фон со свечением, стеклянные карточки.
import 'package:flutter/material.dart';

import 'ornaments.dart';

class Palette {
  const Palette(this.id, this.title, {required this.bg, required this.surface, required this.surfaceStrong,
      required this.text, required this.muted, required this.accent, required this.accent2, required this.onAccent,
      required this.border, required this.chip, required this.bad, required this.glows, this.dark = true,
      this.font, this.displayFont});

  final String id;
  final String title;
  final Color bg, surface, surfaceStrong, text, muted, accent, accent2, onAccent, border, chip, bad;
  final List<Color> glows; // цветные пятна фона («северное сияние», неон…)
  final bool dark;
  final String? font, displayFont; // фирменная тема: JetBrains Mono и Tektur

  bool get isBrand => id == 'brand';
}

const palettes = <String, Palette>{
  // Фирменная тема по умолчанию (дизайн-код AI Agent): Ink, Graphite, один акцент Voice Blue, курсор лаймом.
  'brand': Palette('brand', 'AI Agent',
      bg: Color(0xFF0E0F12), surface: Color(0xFF1A1C21), surfaceStrong: Color(0xFF1A1C21), text: Color(0xFFF2F0EA),
      muted: Color(0xFF9398A5), accent: Color(0xFF4C7DFF), accent2: Color(0xFFC8F53C), onAccent: Color(0xFF0E0F12),
      border: Color(0xFF2E323A), chip: Color(0xFF24272E), bad: Color(0xFFFF5F57), glows: [],
      font: 'JetBrainsMono', displayFont: 'Tektur'),
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
  'dark': Palette('dark', 'Тёмная',
      bg: Color(0xFF0F141C), surface: Color(0xFF161D28), surfaceStrong: Color(0xFF1B2330), text: Color(0xFFE9EEF6),
      muted: Color(0xFF98A4B6), accent: Color(0xFF5AA8FF), accent2: Color(0xFF7EE0C3), onAccent: Color(0xFF06121F),
      border: Color(0xFF283344), chip: Color(0xFF1D2634), bad: Color(0xFFF87171), glows: []),
  'light': Palette('light', 'Светлая',
      bg: Color(0xFFF3F5F9), surface: Color(0xFFFFFFFF), surfaceStrong: Color(0xFFFFFFFF), text: Color(0xFF16202F),
      muted: Color(0xFF5D6B80), accent: Color(0xFF2563EB), accent2: Color(0xFF0D9488), onAccent: Color(0xFFFFFFFF),
      border: Color(0xFFDDE3EC), chip: Color(0xFFEEF2F8), bad: Color(0xFFDC2626), glows: [], dark: false),
};

Palette paletteOf(String? id) => palettes[id] ?? palettes['brand']!;

/// Лаймовый курсор ▮ — знак бренда.
const brandLime = Color(0xFFC8F53C);

ThemeData themeFor(Palette p) {
  final scheme = ColorScheme(
    brightness: p.dark ? Brightness.dark : Brightness.light,
    primary: p.accent, onPrimary: p.onAccent, secondary: p.accent2, onSecondary: p.onAccent,
    error: p.bad, onError: Colors.white, surface: p.surfaceStrong, onSurface: p.text,
    surfaceContainerHighest: p.chip, outline: p.border,
  );
  final radius = BorderRadius.circular(14);
  final base = Typography.material2021().black.apply(bodyColor: p.text, displayColor: p.text, fontFamily: p.font);
  final text = p.displayFont == null
      ? base
      : base.copyWith(
          headlineSmall: base.headlineSmall?.copyWith(fontFamily: p.displayFont, fontWeight: FontWeight.w500),
          titleLarge: base.titleLarge?.copyWith(fontFamily: p.displayFont, fontWeight: FontWeight.w500),
          titleMedium: base.titleMedium?.copyWith(fontFamily: p.displayFont, fontWeight: FontWeight.w500),
        );
  return ThemeData(
    useMaterial3: true,
    fontFamily: p.font,
    colorScheme: scheme,
    scaffoldBackgroundColor: Colors.transparent,
    appBarTheme: AppBarTheme(backgroundColor: Colors.transparent, foregroundColor: p.text, elevation: 0,
        scrolledUnderElevation: 0, centerTitle: false),
    cardTheme: CardThemeData(color: p.surface, elevation: 0, margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(p.isBrand ? 22 : 18),
            side: BorderSide(color: p.border, width: p.isBrand ? 2 : 1))),
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
    textTheme: text,
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
        if (palette.isBrand) const Positioned.fill(child: IgnorePointer(child: CustomPaint(painter: DotGridPainter()))),
        if (glows.isNotEmpty) ...[
          _glow(glows[0], const Alignment(-1.1, -1.0), 1.4),
          if (glows.length > 1) _glow(glows[1], const Alignment(1.2, -0.2), 1.2),
          if (glows.length > 2) _glow(glows[2], const Alignment(-0.4, 1.3), 1.3),
        ],
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
    if (palette.isBrand) {
      // Фирменная иконка: волна из 5 столбиков в синем скруглённом квадрате, вокруг — «уголки кадра».
      return SizedBox(
        width: size * 1.35,
        height: size * 1.35,
        child: CustomPaint(
          painter: CornersPainter(active ? brandLime : palette.accent),
          child: Center(
            child: AnimatedScale(
              duration: const Duration(milliseconds: 300),
              scale: active ? 1.05 : 1,
              child: SizedBox(width: size, height: size, child: const CustomPaint(painter: WaveIconPainter())),
            ),
          ),
        ),
      );
    }
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

/// Точечная сетка — фон тёмных экранов бренда.
class DotGridPainter extends CustomPainter {
  const DotGridPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final dot = Paint()..color = const Color(0x12FFFFFF);
    for (double y = 18; y < size.height; y += 36) {
      for (double x = 18; x < size.width; x += 36) {
        canvas.drawCircle(Offset(x, y), 1.6, dot);
      }
    }
  }

  @override
  bool shouldRepaint(DotGridPainter old) => false;
}

/// Иконка проекта (как static/icon.svg): квадрат 24×24, радиус 5.5, пять столбиков Ink.
class WaveIconPainter extends CustomPainter {
  const WaveIconPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    canvas.drawRRect(RRect.fromRectAndRadius(const Rect.fromLTWH(0, 0, 24, 24), const Radius.circular(5.5)),
        Paint()..color = const Color(0xFF4C7DFF));
    final ink = Paint()..color = const Color(0xFF0E0F12);
    for (final (x, y, h) in const [(4.6, 9.0, 6.0), (7.8, 6.5, 11.0), (11.0, 4.0, 16.0), (14.2, 6.5, 11.0), (17.4, 9.0, 6.0)]) {
      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(x, y, 2, h), const Radius.circular(1)), ink);
    }
  }

  @override
  bool shouldRepaint(WaveIconPainter old) => false;
}

/// «Уголки кадра»: четыре угловые скобки цветом акцента.
class CornersPainter extends CustomPainter {
  const CornersPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final l = size.width * .16, t = 4.0;
    final paint = Paint()..color = color;
    for (final (x, y, dx, dy) in [(0.0, 0.0, 1.0, 1.0), (size.width, 0.0, -1.0, 1.0), (0.0, size.height, 1.0, -1.0),
        (size.width, size.height, -1.0, -1.0)]) {
      canvas.drawRect(Rect.fromPoints(Offset(x, y), Offset(x + dx * l, y + dy * t)), paint);
      canvas.drawRect(Rect.fromPoints(Offset(x, y), Offset(x + dx * t, y + dy * l)), paint);
    }
  }

  @override
  bool shouldRepaint(CornersPainter old) => old.color != color;
}
