package com.localaiagent.local_ai_agent

import android.media.MediaPlayer
import android.speech.tts.TextToSpeech
import java.io.File
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.Locale

// Озвучка ответов «Андрея» системным синтезатором речи Android (канал andrey/tts, см. lib/speaker.dart).
class MainActivity : FlutterActivity() {
    private var tts: TextToSpeech? = null
    private var ready = false
    private var pending: String? = null
    private var player: MediaPlayer? = null

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
                "play" -> {
                    // Голос ассистента с ПК (Джарвис, Пятница, дикторы) — готовый WAV.
                    val audio = call.argument<ByteArray>("audio")
                    if (audio == null) {
                        result.error("no_audio", "Нет звука", null)
                    } else {
                        tts?.stop()
                        val file = File(cacheDir, "answer.wav")
                        file.writeBytes(audio)
                        player?.release()
                        player = MediaPlayer().apply {
                            setDataSource(file.absolutePath)
                            setOnCompletionListener { it.release(); if (player === it) player = null }
                            prepare()
                            start()
                        }
                        result.success(true)
                    }
                }
                "stop" -> {
                    pending = null
                    tts?.stop()
                    player?.release()
                    player = null
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
        player?.release()
        player = null
        tts?.shutdown()
        tts = null
        super.onDestroy()
    }
}
