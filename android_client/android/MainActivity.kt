package com.localaiagent.local_ai_agent

import android.speech.tts.TextToSpeech
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.Locale

// Озвучка ответов «Андрея» системным синтезатором речи Android (канал andrey/tts, см. lib/speaker.dart).
class MainActivity : FlutterActivity() {
    private var tts: TextToSpeech? = null
    private var ready = false
    private var pending: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        tts = TextToSpeech(this) { status ->
            ready = status == TextToSpeech.SUCCESS
            if (ready) {
                tts?.language = Locale("ru", "RU")
                pending?.let { speak(it) }
                pending = null
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "andrey/tts").setMethodCallHandler { call, result ->
            when (call.method) {
                "speak" -> {
                    val text = call.argument<String>("text") ?: ""
                    if (ready) speak(text) else pending = text
                    result.success(true)
                }
                "stop" -> {
                    pending = null
                    tts?.stop()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun speak(text: String) {
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "andrey")
    }

    override fun onDestroy() {
        tts?.shutdown()
        tts = null
        super.onDestroy()
    }
}
