import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:local_ai_agent/theme.dart';

void main() {
  setUpAll(() async {
    // Фирменные шрифты из assets — как в приложении.
    for (final (family, files) in const [
      ('Tektur', ['assets/fonts/Tektur-Medium.ttf']),
      ('JetBrainsMono', ['assets/fonts/JetBrainsMono-Regular.ttf', 'assets/fonts/JetBrainsMono-Bold.ttf']),
    ]) {
      final loader = FontLoader(family);
      for (final file in files) {
        loader.addFont(rootBundle.load(file));
      }
      await loader.load();
    }
  });

  test('фирменная тема — по умолчанию', () {
    expect(paletteOf(null).id, 'brand');
    expect(paletteOf('unknown').isBrand, isTrue);
  });

  for (final id in ['brand', 'gzhel', 'slavic']) {
    testWidgets('тема $id: фон с орнаментом и сфера рисуются', (tester) async {
      tester.view.physicalSize = const Size(400, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final palette = paletteOf(id);
      expect(palette.id, id);
      await tester.pumpWidget(MaterialApp(
        theme: themeFor(palette),
        home: Scene(palette: palette, child: Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
          Orb(palette: palette, active: false),
          const SizedBox(height: 24),
          Text('Скажи «Андрей»', style: themeFor(palette).textTheme.titleLarge),
          const Text('голос вместо клавиатуры'),
        ]))),
      ));
      expect(find.byType(CustomPaint), findsWidgets);
      expect(tester.takeException(), isNull);
      if (const bool.fromEnvironment('GOLDEN')) {
        await expectLater(find.byType(MaterialApp), matchesGoldenFile('goldens/$id.png'));
      }
    });
  }
}
