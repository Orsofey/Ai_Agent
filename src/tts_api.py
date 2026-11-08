"""Shared neural/recorded speech endpoints for desktop preview, web and Android.

Registered on the existing app, so its authentication and error handlers still apply.
"""
import base64
import re
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file


def register_tts_routes(app, tts, store, owner):
    routes = Blueprint('tts_audio', __name__)

    @routes.post('/api/ai/synthesize_local')
    def synthesize_local():
        data = request.get_json(silent=True) or {}
        text = str(data.get('text', '')).strip()
        if not 1 <= len(text) <= 2000:
            return jsonify(success=False, error='Text 1-2000 chars')
        settings = store.settings(owner())
        allowed = {item['id'] for item in tts.available_voices()} | \
            {item['id'] for item in tts.assistant_voices() if item['id'].startswith('custom:')}
        voice = str(data.get('voice', settings.get('tts_voice', 'irina')))
        if voice not in allowed:
            voice = 'irina'
        try:
            path = tts.synthesize(text, voice, settings.get('tts_rate', 100) / 100.0,
                                  preset=settings.get('voice_preset', 'classic'))
        except Exception:
            app.logger.exception('Voice preview failed')
            return jsonify(success=False, error='Не удалось создать озвучку'), 503
        if not path:
            return jsonify(success=False, error='Fallback to system')
        return jsonify(success=True, audio_url='/tts_audio/' + Path(path).name)

    @routes.get('/tts_audio/<filename>')
    def serve_tts_audio(filename):
        if not re.fullmatch(r'[0-9a-f]{20}\.wav', filename):
            return 'Not found', 404
        path = Path(tts.cache) / filename
        if not path.is_file():
            return 'Not found', 404
        return send_file(str(path), mimetype='audio/wav')

    @routes.post('/api/tts/phone')
    def tts_phone():
        text = str((request.get_json(silent=True) or {}).get('text', '')).strip()
        if not 1 <= len(text) <= 2000:
            return jsonify(success=False, message='Нужен текст до 2000 символов'), 400
        settings = store.settings('device:desktop')
        path = tts.synthesize(text, settings.get('tts_voice', 'irina'), settings.get('tts_rate', 110) / 100.0,
                              preset=settings.get('voice_preset', 'classic'))
        if not path:
            return jsonify(success=False, message='Голоса на ПК ещё не установлены'), 503
        return jsonify(success=True, mime='audio/wav', audio=base64.b64encode(Path(path).read_bytes()).decode())

    app.register_blueprint(routes)
