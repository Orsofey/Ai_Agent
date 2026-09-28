// Подключение к агенту на ПК: разбор ссылки из QR-кода и вызовы локального API.
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

/// Адрес ПК и код подключения из ссылки вида http://192.168.1.5:8765/#token=…&device=…
class Pairing {
  Pairing(this.base, this.token);

  final Uri base;
  final String token;

  static Pairing? parse(String text) {
    final uri = Uri.tryParse(text.trim());
    if (uri == null || !(uri.scheme == 'http' || uri.scheme == 'https') || uri.host.isEmpty) {
      return null;
    }
    final params = Uri.splitQueryString(uri.fragment);
    final token = params['token'] ?? uri.queryParameters['token'] ?? '';
    if (!RegExp(r'^[\w-]{16,200}$').hasMatch(token)) return null;
    return Pairing(Uri(scheme: uri.scheme, host: uri.host, port: uri.port), token);
  }

  String get link => '${base.toString().replaceAll(RegExp(r'/$'), '')}/#token=$token';
}

class AgentError implements Exception {
  AgentError(this.message);
  final String message;
  @override
  String toString() => message;
}

class AgentApi {
  AgentApi(this.pairing, this.device, {http.Client? client}) : _client = client ?? http.Client();

  final Pairing pairing;
  final String device;
  final http.Client _client;

  static String newDeviceId() {
    final random = Random.secure();
    return 'android-${List.generate(10, (_) => random.nextInt(36).toRadixString(36)).join()}';
  }

  static String newCommandId() {
    final random = Random.secure();
    return List.generate(24, (_) => random.nextInt(36).toRadixString(36)).join();
  }

  Map<String, String> get _headers => {'X-Agent-Token': pairing.token, 'X-Device-ID': device};

  Uri _url(String path) => pairing.base.replace(path: path);

  Map<String, dynamic> _decode(http.Response response) {
    Map<String, dynamic> data;
    try {
      data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      throw AgentError('ПК ответил непонятно (код ${response.statusCode}). Проверьте адрес.');
    }
    if (response.statusCode == 401) {
      throw AgentError('Код подключения устарел. Отсканируйте QR-код заново: на ПК Настройки → «iPhone и Android».');
    }
    if (data['success'] == false) {
      throw AgentError((data['message'] ?? data['response'] ?? 'Ошибка на ПК').toString());
    }
    return data;
  }

  Future<T> _guard<T>(Future<T> Function() action) async {
    try {
      return await action();
    } on AgentError {
      rethrow;
    } catch (_) {
      throw AgentError('Не удаётся связаться с ПК. Телефон и компьютер должны быть в одной сети Wi‑Fi, а агент — запущен.');
    }
  }

  Future<bool> check() => _guard(() async {
        final response = await _client.get(_url('/api/connection'), headers: _headers).timeout(const Duration(seconds: 6));
        _decode(response);
        return true;
      });

  Future<String> send(String message) => _guard(() async {
        final response = await _client
            .post(_url('/api/chat'),
                headers: {..._headers, 'Content-Type': 'application/json'},
                body: jsonEncode({'message': message, 'id': newCommandId()}))
            .timeout(const Duration(seconds: 120));
        return (_decode(response)['response'] ?? '').toString();
      });

  Future<String> transcribe(List<int> wav) => _guard(() async {
        final request = http.MultipartRequest('POST', _url('/api/transcribe'))
          ..headers.addAll(_headers)
          ..fields['language'] = 'auto'
          ..files.add(http.MultipartFile.fromBytes('audio', wav, filename: 'voice.wav'));
        final response = await http.Response.fromStream(await _client.send(request).timeout(const Duration(seconds: 60)));
        return (_decode(response)['text'] ?? '').toString().trim();
      });

  Future<List<Map<String, String>>> history() => _guard(() async {
        final response = await _client.get(_url('/api/history'), headers: _headers).timeout(const Duration(seconds: 10));
        final items = (_decode(response)['history'] as List?) ?? const [];
        return [
          for (final item in items.whereType<Map>())
            {'role': '${item['role']}', 'text': '${item['text']}'}
        ];
      });

  Future<void> cancel() => _guard(() async {
        await _client.post(_url('/api/cancel'), headers: _headers).timeout(const Duration(seconds: 6));
      });
}
