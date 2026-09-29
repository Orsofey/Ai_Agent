// Орнаменты тем «Гжель» и «Славянская» — те же мазки, что в static/ornaments/*.svg на ПК.
import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Мазок-полумесяц: толстый посередине, сходит на нет к концам.
Path crescent(double r, double spanDeg, [double thick = 0.3]) {
  final a = spanDeg * math.pi / 180;
  final x = r * math.sin(a), y = -r * math.cos(a);
  final top = -r + r * thick;
  final c = (x * x + y * y - top * top) / (2 * (y - top));
  final big = (top - c).abs();
  return Path()
    ..moveTo(-x, y)
    ..arcToPoint(Offset(x, y), radius: Radius.circular(r))
    ..arcToPoint(Offset(-x, y), radius: Radius.circular(big), clockwise: top >= y)
    ..close();
}

class OrnamentStyle {
  const OrnamentStyle({required this.petal, required this.petal2, required this.core, required this.stem,
      required this.leaf, this.berries = false, this.curls = false});

  final List<Color> petal, petal2, leaf; // градиенты мазков
  final Color core, stem;
  final bool berries, curls;

  static const gzhel = OrnamentStyle(
    petal: [Color(0xFF0B2A86), Color(0xFF2459CC), Color(0x8C8FB2F0)],
    petal2: [Color(0xFF0B2A86), Color(0xFF2459CC), Color(0x8C8FB2F0)],
    leaf: [Color(0xFF0B2A86), Color(0xFF2A60D0), Color(0x809DBCF3)],
    core: Color(0xFF061D66), stem: Color(0xFF1D4BBD),
  );
  static const slavic = OrnamentStyle(
    petal: [Color(0xFFFFF0B0), Color(0xFFF0C55A), Color(0xFFC88A22), Color(0xFF7A4A0E)],
    petal2: [Color(0xFFFF8A6A), Color(0xFFE0321F), Color(0xFF7A0B07)],
    leaf: [Color(0xFFFFF0B0), Color(0xFFF0C55A), Color(0xFFC88A22)],
    core: Color(0xFFB3261E), stem: Color(0xFFD9A33A), berries: true, curls: true,
  );

  static OrnamentStyle? of(String id) => {'gzhel': gzhel, 'slavic': slavic}[id];
}

/// Роза из мазков: кольца лепестков с просветами и широкая «чаша» снизу.
void paintRose(Canvas canvas, Offset center, double scale, OrnamentStyle style, {bool cup = true}) {
  const rings = [(9.0, 2, 20.0, 62.0), (17.0, 3, 70.0, 44.0), (27.0, 4, 15.0, 36.0), (39.0, 5, 50.0, 30.0)];
  canvas.save();
  canvas.translate(center.dx, center.dy);
  canvas.scale(scale);
  void stroke(Path path, List<Color> colors, double angle) {
    canvas.save();
    canvas.rotate(angle * math.pi / 180);
    final bounds = path.getBounds();
    canvas.drawPath(path, Paint()..shader = LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: colors).createShader(bounds));
    canvas.restore();
  }

  for (var k = 0; k < rings.length; k++) {
    final (r, n, offset, span) = rings[k];
    final path = crescent(r, span);
    for (var i = 0; i < n; i++) {
      stroke(path, k.isOdd ? style.petal2 : style.petal, offset + i * 360 / n);
    }
  }
  if (cup) {
    stroke(crescent(47, 62, 0.37), style.petal, 180);
    stroke(crescent(35, 48, 0.37), style.petal2, 180);
  }
  canvas.drawCircle(Offset.zero, 5.5, Paint()..color = style.core);
  canvas.restore();
}

void _leaf(Canvas canvas, Offset at, double angle, double length, double width, OrnamentStyle style) {
  canvas.save();
  canvas.translate(at.dx, at.dy);
  canvas.rotate(angle * math.pi / 180);
  final path = Path()
    ..moveTo(0, 0)
    ..cubicTo(length * .25, -width, length * .7, -width * .9, length, 0)
    ..cubicTo(length * .7, width * .35, length * .25, width * .4, 0, 0)
    ..close();
  canvas.drawPath(path, Paint()..shader = LinearGradient(colors: style.leaf).createShader(path.getBounds()));
  canvas.restore();
}

void _berries(Canvas canvas, Offset at, double r) {
  for (final d in const [Offset(0, 0), Offset(1.7, .5), Offset(.6, 1.7), Offset(-1.1, 1.2)]) {
    final c = at + d * r;
    canvas.drawCircle(c, r, Paint()..shader = RadialGradient(center: const Alignment(-.3, -.4),
        colors: const [Color(0xFFFF8A6A), Color(0xFFE0321F), Color(0xFF7A0B07)])
        .createShader(Rect.fromCircle(center: c, radius: r)));
    canvas.drawCircle(c + Offset(-r * .35, -r * .38), r * .22, Paint()..color = const Color(0xD9FFE6B0));
  }
}

void _curl(Canvas canvas, Offset at, double size, double turn, Color color) {
  final path = Path();
  for (var i = 0; i < 46; i++) {
    final t = i / 45 * math.pi * 2.3;
    final rad = size * (1 - i / 52);
    final p = at + Offset(rad * math.cos(t * turn), rad * math.sin(t * turn));
    i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
  }
  canvas.drawPath(path, Paint()
    ..color = color
    ..style = PaintingStyle.stroke
    ..strokeWidth = 2
    ..strokeCap = StrokeCap.round);
}

/// Букет в углу экрана (координаты — как у SVG на ПК, 320×320).
class BouquetPainter extends CustomPainter {
  const BouquetPainter(this.style);

  final OrnamentStyle style;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 320);
    final stem = Paint()
      ..color = style.stem
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = 3;
    canvas.drawPath(Path()..moveTo(300, 300)..cubicTo(250, 250, 190, 215, 120, 190), stem);
    canvas.drawPath(Path()..moveTo(300, 300)..cubicTo(282, 225, 262, 160, 214, 96), stem);
    canvas.drawPath(Path()..moveTo(232, 244)..cubicTo(212, 200, 178, 170, 150, 150), stem..strokeWidth = 2);
    for (final (x, y, a, l, w) in const [
      (250.0, 252.0, 200.0, 64.0, 15.0), (246.0, 238.0, 245.0, 56.0, 13.0), (200.0, 222.0, 170.0, 58.0, 14.0),
      (268.0, 200.0, 250.0, 60.0, 14.0), (236.0, 150.0, 215.0, 52.0, 12.0), (240.0, 142.0, 285.0, 46.0, 11.0),
    ]) {
      _leaf(canvas, Offset(x, y), a, l, w, style);
    }
    if (style.curls) {
      _curl(canvas, const Offset(96, 176), 16, 1, style.stem);
      _curl(canvas, const Offset(214, 70), 14, -1, style.stem);
    } else {
      for (var i = 0; i < 4; i++) {
        canvas.drawCircle(Offset(106 - i * 8.0, 176 - i * 7.0), 3.4 - i * .7, Paint()..color = style.stem);
        canvas.drawCircle(Offset(214 - i * 1.0, 78 - i * 9.0), 3.4 - i * .7, Paint()..color = style.stem);
      }
    }
    paintRose(canvas, const Offset(120, 190), .95, style);
    paintRose(canvas, const Offset(214, 96), .75, style);
    paintRose(canvas, const Offset(150, 150), .5, style, cup: false);
    if (style.berries) {
      _berries(canvas, const Offset(222, 196), 8);
      _berries(canvas, const Offset(262, 120), 7);
    }
  }

  @override
  bool shouldRepaint(BouquetPainter old) => old.style != style;
}

/// Рисунок на сфере ассистента.
class OrbPainter extends CustomPainter {
  const OrbPainter(this.style);

  final OrnamentStyle style;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final scale = size.width / 140;
    if (style.berries) {
      canvas.save();
      canvas.translate(center.dx, center.dy);
      canvas.scale(scale);
      final plate = crescent(58, 20, 0.3);
      for (var a = 0; a < 360; a += 30) {
        canvas.save();
        canvas.rotate(a * math.pi / 180);
        canvas.drawPath(plate, Paint()..shader = LinearGradient(colors: style.leaf).createShader(plate.getBounds()));
        canvas.restore();
      }
      canvas.restore();
    } else {
      for (var a = 0; a < 360; a += 45) {
        final dir = Offset(math.sin(a * math.pi / 180), -math.cos(a * math.pi / 180));
        for (var i = 0; i < 3; i++) {
          canvas.drawCircle(center + dir * 52 * scale + Offset(-dir.dy, dir.dx) * (i - 1) * 9 * scale,
              (2.6 - i * .5) * scale, Paint()..color = style.stem);
        }
      }
    }
    paintRose(canvas, center, .82 * scale, style);
  }

  @override
  bool shouldRepaint(OrbPainter old) => old.style != style;
}

/// Кайма вдоль верха экрана: фестон гжельской тарелки или вышивка крестиком.
class BandPainter extends CustomPainter {
  const BandPainter(this.id);

  final String id;

  static const _motif = [
    '.......R.......', '......R.R......', '.....R.G.R.....', '....R.GGG.R....',
    '...R.G.R.G.R...', '..R.G.RRR.G.R..', '.R.G.RR.RR.G.R.', 'R.G.RR.G.RR.G.R',
  ];

  @override
  void paint(Canvas canvas, Size size) {
    if (id == 'gzhel') {
      final fill = Paint()..color = const Color(0xFF1D4BBD);
      final dot = Paint()..color = const Color(0xFF2459CC);
      for (double x = 0; x < size.width; x += 32) {
        canvas.drawPath(Path()
          ..moveTo(x, 0)
          ..lineTo(x + 32, 0)
          ..lineTo(x + 32, 2)
          ..quadraticBezierTo(x + 24, 9, x + 16, 2)
          ..quadraticBezierTo(x + 8, 9, x, 2)
          ..close(), fill);
        canvas.drawCircle(Offset(x + 8, 9), 1.2, dot);
        canvas.drawCircle(Offset(x + 24, 9), 1.2, dot);
      }
      return;
    }
    const cell = 1.7;
    final red = Paint()
      ..color = const Color(0xFFD0302A)
      ..strokeWidth = .9
      ..strokeCap = StrokeCap.round;
    final gold = Paint()
      ..color = const Color(0xFFE9B949)
      ..strokeWidth = .9
      ..strokeCap = StrokeCap.round;
    void stitch(double x, double y, Paint p) {
      canvas.drawLine(Offset(x + .3, y + .3), Offset(x + cell - .3, y + cell - .3), p);
      canvas.drawLine(Offset(x + cell - .3, y + .3), Offset(x + .3, y + cell - .3), p);
    }

    final rows = [..._motif, ..._motif.reversed.skip(1)];
    for (double left = 0; left < size.width; left += 20 * cell) {
      for (var i = 0; i < 20; i++) {
        stitch(left + i * cell, 0, i.isEven ? red : gold);
        stitch(left + i * cell, 18 * cell, i.isEven ? gold : red);
      }
      for (var r = 0; r < rows.length; r++) {
        for (var c = 0; c < rows[r].length; c++) {
          final ch = rows[r][c];
          if (ch != '.') stitch(left + c * cell, (r + 2) * cell, ch == 'R' ? red : gold);
        }
        if (r >= 6 && r <= 8) {
          final cross = const ['.G.', 'GGG', '.G.'][r - 6];
          for (var c = 0; c < 3; c++) {
            if (cross[c] == 'G') stitch(left + (16 + c) * cell, (r + 2) * cell, gold);
          }
        }
      }
    }
  }

  @override
  bool shouldRepaint(BandPainter old) => old.id != id;
}
