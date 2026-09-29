// Озвучка ответов системным синтезатором Android (TextToSpeech) — без сторонних плагинов.
// Нативная часть — android/MainActivity.kt (копируется скриптом сборки).
import 'package:flutter/services.dart';

class Speaker {
  static const _channel = MethodChannel('andrey/tts');

  Future<void> speak(String text) async {
    try {
      await _channel.invokeMethod('speak', {'text': text});
    } on MissingPluginException {
      // Тесты и платформы без нативной части — молча без звука.
    } on PlatformException {
      // Синтезатор речи на телефоне не установлен.
    }
  }

  /// Воспроизвести готовый звук (WAV с голосом ассистента ПК).
  Future<void> play(List<int> wav) async {
    await _channel.invokeMethod('play', {'audio': Uint8List.fromList(wav)});
  }

  Future<void> stop() async {
    try {
      await _channel.invokeMethod('stop');
    } on MissingPluginException {
      // нет нативной части
    } on PlatformException {
      // нет синтезатора
    }
  }
}
