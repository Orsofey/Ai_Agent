import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:webview_flutter/webview_flutter.dart';

void main() {
  runApp(const LocalAIAgentApp());
}

class LocalAIAgentApp extends StatelessWidget {
  const LocalAIAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Local AI Agent',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF4F73DF)),
        useMaterial3: true,
      ),
      home: const ConnectPage(),
    );
  }
}

/// Экран подключения: поиск ПК в сети или ручной ввод адреса.
class ConnectPage extends StatefulWidget {
  const ConnectPage({super.key});

  @override
  State<ConnectPage> createState() => _ConnectPageState();
}

class _ConnectPageState extends State<ConnectPage> {
  final TextEditingController _controller = TextEditingController();
  bool _searching = false;
  String _status = '';

  @override
  void initState() {
    super.initState();
    _loadSaved();
  }

  Future<void> _loadSaved() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('server_url');
    if (saved != null && saved.isNotEmpty) {
      _controller.text = saved;
      // Автоподключение к последнему адресу
      _connect(saved, silent: true);
    } else {
      _autoDiscover();
    }
  }

  /// Проверить, отвечает ли агент по адресу.
  Future<bool> _probe(String baseUrl) async {
    try {
      final resp = await http
          .get(Uri.parse('$baseUrl/health'))
          .timeout(const Duration(milliseconds: 700));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        return data['ok'] == true;
      }
    } catch (_) {}
    return false;
  }

  /// Перебор типичных адресов локальной сети.
  Future<void> _autoDiscover() async {
    setState(() {
      _searching = true;
      _status = 'Поиск агента в сети…';
    });

    final candidates = <String>[];
    for (var host = 1; host <= 254; host++) {
      candidates.add('http://192.168.0.$host:5000');
      candidates.add('http://192.168.1.$host:5000');
    }
    candidates.add('http://10.0.0.1:5000');

    // Проверяем пулами по 24, чтобы не ждать слишком долго
    for (var i = 0; i < candidates.length; i += 24) {
      final batch = candidates.sublist(i, (i + 24).clamp(0, candidates.length));
      final results = await Future.wait(
        batch.map((u) => _probe(u).then((ok) => ok ? u : null)),
      );
      final found = results.firstWhere((r) => r != null, orElse: () => null);
      if (found != null) {
        _controller.text = found;
        await _save(found);
        if (mounted) {
          setState(() {
            _searching = false;
            _status = 'Найден агент: $found';
          });
        }
        await _connect(found);
        return;
      }
      // Обновляем прогресс
      if (mounted) {
        setState(() {
          _status = 'Поиск… проверено ${(i + batch.length).clamp(0, candidates.length)}';
        });
      }
    }

    if (mounted) {
      setState(() {
        _searching = false;
        _status = 'Агент не найден. Введите адрес вручную (см. консоль на ПК).';
      });
    }
  }

  Future<void> _save(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_url', url);
  }

  Future<void> _connect(String url, {bool silent = false}) async {
    var base = url.trim();
    if (base.isEmpty) return;
    if (!base.startsWith('http')) base = 'http://$base';
    base = base.replaceAll(RegExp(r'/+$'), '');

    setState(() {
      _searching = true;
      _status = 'Подключение к $base…';
    });

    final ok = await _probe(base);
    if (!mounted) return;

    if (ok) {
      await _save(base);
      setState(() => _searching = false);
      Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => AgentWebView(baseUrl: base)),
      );
    } else {
      setState(() {
        _searching = false;
        if (!silent) _status = 'Не удалось подключиться к $base';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.smart_toy_outlined, size: 72, color: Color(0xFF4F73DF)),
              const SizedBox(height: 16),
              const Text(
                'Local AI Agent',
                style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              const Text(
                'Пульт управления агентом на вашем ПК',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.black54),
              ),
              const SizedBox(height: 32),
              TextField(
                controller: _controller,
                keyboardType: TextInputType.url,
                decoration: InputDecoration(
                  labelText: 'Адрес агента',
                  hintText: 'http://192.168.1.5:5000',
                  border: const OutlineInputBorder(),
                  prefixIcon: const Icon(Icons.wifi),
                ),
              ),
              const SizedBox(height: 16),
              if (_searching) const LinearProgressIndicator(),
              if (_status.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(_status, textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 13, color: Colors.black54)),
              ],
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _searching ? null : () => _connect(_controller.text),
                  icon: const Icon(Icons.link),
                  label: const Text('Подключиться'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _searching ? null : _autoDiscover,
                  icon: const Icon(Icons.search),
                  label: const Text('Найти автоматически'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// WebView с интерфейсом агента.
class AgentWebView extends StatefulWidget {
  final String baseUrl;
  const AgentWebView({super.key, required this.baseUrl});

  @override
  State<AgentWebView> createState() => _AgentWebViewState();
}

class _AgentWebViewState extends State<AgentWebView> {
  late final WebViewController _controller;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF171B25))
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (_) => setState(() => _loading = false),
        ),
      )
      ..loadRequest(Uri.parse(widget.baseUrl));

    // Разрешаем микрофон для голосового ввода
    _controller.setMediaPlaybackRequiresUserGesture(false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          WebViewWidget(controller: _controller),
          if (_loading)
            const Center(child: CircularProgressIndicator()),
        ],
      ),
    );
  }
}
