import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:local_ai_agent/theme.dart';

void main() {
  for (final id in ['gzhel', 'slavic']) {
    testWidgets('тема $id: фон с орнаментом и сфера рисуются', (tester) async {
      tester.view.physicalSize = const Size(400, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final palette = paletteOf(id);
      expect(palette.id, id);
      await tester.pumpWidget(MaterialApp(
        theme: themeFor(palette),
        home: Scene(palette: palette, child: Center(child: Orb(palette: palette, active: false))),
      ));
      expect(find.byType(CustomPaint), findsWidgets);
      expect(tester.takeException(), isNull);
      if (const bool.fromEnvironment('GOLDEN')) {
        await expectLater(find.byType(MaterialApp), matchesGoldenFile('goldens/$id.png'));
      }
    });
  }

  testWidgets('тема glass: стеклянные фигуры и радужная сфера', (tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final palette = paletteOf('glass');
    expect(palette.dark, isFalse);
    await tester.pumpWidget(MaterialApp(
      theme: themeFor(palette),
      home: Scene(palette: palette, child: Center(child: Orb(palette: palette, active: true))),
    ));
    expect(find.byType(GlassShape), findsNWidgets(5));
    expect(tester.takeException(), isNull);
    if (const bool.fromEnvironment('GOLDEN')) {
      await expectLater(find.byType(MaterialApp), matchesGoldenFile('goldens/glass.png'));
    }
  });
}
