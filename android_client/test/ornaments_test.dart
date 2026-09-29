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
}
