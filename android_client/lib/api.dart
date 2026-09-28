// Подключение к агенту на ПК: разбор ссылки из QR-кода, выбор пути (домашняя сеть или интернет) и вызовы API.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;

/// Данные из ссылки вида http://192.168.1.5:5000/#token=…&hosts=10.0.0.5&relay=https%3A%2F%2F…&rid=…
class Pairing {
  Pairing(this.bases, this.token, {this.relay, this.rid});

  /// Адреса ПК в локальных сетях — пробуем все (у ПК бывает несколько сетевых адаптеров).
  final List<Uri> bases;
  final String token;

  /// Мост через интернет (сервер аккаунтов «Андрея») — работает из любой сети.
  final Uri? relay;
  final String? rid;

  Uri get base => bases.first;
  bool get hasRelay => relay != null && rid != null;

  static Pairing? parse(String text) {
    final uri = Uri.tryParse(text.trim());
    if (uri == null || !(uri.scheme == 'http' || uri.scheme == 'https') || uri.host.isEmpty) {
      return null;
    }
    final params = Uri.splitQueryString(uri.fragment);
    final token = params['token'] ?? uri.queryParameters['token'] ?? '';
    if (!RegExp(r'^[\w-]{16,200}$').hasMatch(token)) return null;
    final bases = <Uri>[Uri(scheme: uri.scheme, host: uri.host, port: uri.port)];
    for (final host in (params['hosts'] ?? '').split(',')) {
      if (RegExp(r'^[\w.:-]{3,60}$').hasMatch(host.trim())) {
        bases.add(Uri(scheme: uri.scheme, host: host.trim(), port: uri.port));
      }
    }
    Uri? relay;
    final relayText = params['relay'];
    if (relayText != null && relayText.isNotEmpty) {
      final parsed = Uri.tryParse(relayText);
      if (parsed != null && parsed.scheme == 'https' && parsed.host.isNotEmpty) relay = parsed;
    }
    final rid = params['rid'];
    return Pairing(bases, token,
        relay: relay, rid: rid != null && RegExp(r'^[\w-]{16,64}$').hasMatch(rid) ? rid : null);
  }

  String get link {
    final extra = bases.skip(1).map((b) => b.host).join(',');
    var value = '${base.toString().replaceAll(RegExp(r'/$'), '')}/#token=$token';
    if (extra.isNotEmpty) value += '&hosts=$extra';
    if (hasRelay) value += '&relay=${Uri.encodeComponent(relay.toString())}&rid=$rid';
    return value;
  }

  /// Ключ моста — HMAC от кода подключения (сам код на сервер не уходит). Совпадает с relay_client.py.
  String get relayKey => Hmac(sha256, utf8.encode(token)).convert(utf8.encode('andrey-relay')).toString();
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

  Uri? _direct;          // рабочий адрес в локальной сети
  bool _viaRelay = false; // или мост через интернет

  /// Как подключены сейчас: «Wi‑Fi (192.168.1.5)» или «через интернет».
  String get route => _viaRelay ? 'через интернет' : (_direct != null ? 'Wi‑Fi (${_direct!.host})' : 'не подключено');

  static String newDeviceId() {
    final random = Random.secure();
    return 'android-${List.generate(10, (_) => random.nextInt(36).toRadixString(36)).join()}';
  }

  static String newCommandId() {
    final random = Random.secure();
    return List.generate(24, (_) => random.nextInt(36).toRadixString(36)).join();
  }

  Map<String, String> get _headers => {'X-Agent-Token': pairing.token, 'X-Device-ID': device};

  // ---------------- выбор пути ----------------
  /// Найти рабочий путь: сначала все адреса в локальной сети (параллельно), затем мост через интернет.
  Future<void> connect() async {
    final reasons = <String>[];
    final completer = Completer<Uri?>();
    var pending = pairing.bases.length;
    for (final base in pairing.bases) {
      _client
          .get(base.replace(path: '/api/connection'), headers: _headers)
          .timeout(const Duration(seconds: 4))
          .then((response) {
        if (response.statusCode == 401) {
          if (!completer.isCompleted) completer.completeError(AgentError(_expired));
        } else if (response.statusCode == 200 && !completer.isCompleted) {
          completer.complete(base);
        }
      }).catchError((Object error) {
        reasons.add(_reason(error));
      }).whenComplete(() {
        pending -= 1;
        if (pending == 0 && !completer.isCompleted) completer.complete(null);
      });
    }
    final found = await completer.future;
    if (found != null) {
      _direct = found;
      _viaRelay = false;
      return;
    }
    if (pairing.hasRelay) {
      await _relay('GET', '/api/connection', timeout: const Duration(seconds: 20));
      _viaRelay = true;
      _direct = null;
      return;
    }
    final hosts = pairing.bases.map((b) => b.host).join(', ');
    final refused = reasons.contains('refused');
    throw AgentError(refused
        ? 'Компьютер ($hosts) отвечает, но «Андрей» на нём не запущен. Запустите ассистента на ПК.'
        : 'Не удаётся связаться с ПК ($hosts). Чаще всего подключение блокирует брандмауэр Windows: на ПК откройте '
            'Настройки → «Телефон» → «Разрешить подключение телефона». Или включите там «Доступ через интернет» '
            'и отсканируйте QR-код заново — тогда одна сеть Wi‑Fi не нужна.');
  }

  static String _reason(Object error) {
    if (error is SocketException && (error.osError?.errorCode == 111 || error.message.contains('refused'))) {
      return 'refused';
    }
    return error is TimeoutException ? 'timeout' : 'network';
  }

  static const _expired =
      'Код подключения устарел. Отсканируйте QR-код заново: на ПК Настройки → «Телефон».';

  // ---------------- запросы ----------------
  Future<Map<String, dynamic>> _call(String method, String path,
      {Map<String, dynamic>? json, List<int>? audio, Duration timeout = const Duration(seconds: 30)}) async {
    if (_direct == null && !_viaRelay) await connect();
    try {
      return _viaRelay
          ? await _relay(method, path, json: json, audio: audio, timeout: timeout)
          : await _local(method, path, json: json, audio: audio, timeout: timeout);
    } on AgentError {
      rethrow;
    } catch (_) {
      // Сеть сменилась (ушли из дома, другой Wi‑Fi) — ищем путь заново и повторяем.
      // Команды с одинаковым id ПК не выполняет дважды.
      _direct = null;
      _viaRelay = false;
      await connect();
      return _viaRelay
          ? await _relay(method, path, json: json, audio: audio, timeout: timeout)
          : await _local(method, path, json: json, audio: audio, timeout: timeout);
    }
  }

  Future<Map<String, dynamic>> _local(String method, String path,
      {Map<String, dynamic>? json, List<int>? audio, required Duration timeout}) async {
    final url = _direct!.replace(path: path);
    http.Response response;
    if (audio != null) {
      final request = http.MultipartRequest('POST', url)
        ..headers.addAll(_headers)
        ..fields['language'] = 'auto'
        ..files.add(http.MultipartFile.fromBytes('audio', audio, filename: 'voice.wav'));
      response = await http.Response.fromStream(await _client.send(request).timeout(timeout));
    } else if (method == 'GET') {
      response = await _client.get(url, headers: _headers).timeout(timeout);
    } else {
      response = await _client
          .post(url, headers: {..._headers, 'Content-Type': 'application/json'}, body: jsonEncode(json ?? {}))
          .timeout(timeout);
    }
    return _decode(response.statusCode, _json(response.bodyBytes, response.statusCode));
  }

  Future<Map<String, dynamic>> _relay(String method, String path,
      {Map<String, dynamic>? json, List<int>? audio, required Duration timeout}) async {
    final response = await _client
        .post(pairing.relay!.replace(path: '/relay/phone'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'rid': pairing.rid,
              'key': pairing.relayKey,
              'method': method,
              'path': path,
              'json': json,
              'audio': audio == null ? null : base64Encode(audio),
              'language': 'auto',
              'device': device,
            }))
        .timeout(timeout + const Duration(seconds: 10));
    final data = _json(response.bodyBytes, response.statusCode);
    if (response.statusCode != 200 || data['success'] == false) {
      throw AgentError((data['message'] ?? 'Мост через интернет недоступен (код ${response.statusCode}).').toString());
    }
    final body = data['body'];
    return _decode((data['status'] as num?)?.toInt() ?? 500, body is Map<String, dynamic> ? body : {});
  }

  static Map<String, dynamic> _json(List<int> bytes, int status) {
    try {
      return jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
    } catch (_) {
      throw AgentError('ПК ответил непонятно (код $status). Проверьте адрес.');
    }
  }

  static Map<String, dynamic> _decode(int status, Map<String, dynamic> data) {
    if (status == 401) throw AgentError(_expired);
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
      throw AgentError('Связь с ПК потеряна. Проверьте, что компьютер включён и «Андрей» запущен.');
    }
  }

  // ---------------- API ----------------
  Future<bool> check() => _guard(() async {
        await connect();
        return true;
      });

  Future<String> send(String message) => _guard(() async {
        final data = await _call('POST', '/api/chat',
            json: {'message': message, 'id': newCommandId()}, timeout: const Duration(seconds: 120));
        return (data['response'] ?? '').toString();
      });

  Future<String> transcribe(List<int> wav) => _guard(() async {
        final data = await _call('POST', '/api/transcribe', audio: wav, timeout: const Duration(seconds: 60));
        return (data['text'] ?? '').toString().trim();
      });

  Future<List<Map<String, String>>> history() => _guard(() async {
        final data = await _call('GET', '/api/history', timeout: const Duration(seconds: 15));
        final items = (data['history'] as List?) ?? const [];
        return [
          for (final item in items.whereType<Map>())
            {'role': '${item['role']}', 'text': '${item['text']}'}
        ];
      });

  Future<void> cancel() => _guard(() async {
        await _call('POST', '/api/cancel', timeout: const Duration(seconds: 10));
      });
}
