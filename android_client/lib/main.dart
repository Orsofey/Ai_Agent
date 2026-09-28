// «Андрей» для Android: голосовой и текстовый пульт ИИ-агента, который работает на вашем ПК.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'speaker.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AgentApp());
}

const accent = Color(0xFF7C5CFF);

class AgentApp extends StatelessWidget {
  const AgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Андрей',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: accent, brightness: Brightness.dark),
        scaffoldBackgroundColor: const Color(0xFF0B1020),
        useMaterial3: true,
      ),
      home: const StartPage(),
    );
  }
}

/// Загружает сохранённое подключение и открывает чат или экран подключения.
class StartPage extends StatefulWidget {
  const StartPage({super.key});

  @override
  State<StartPage> createState() => _StartPageState();
}

class _StartPageState extends State<StartPage> {
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    var device = prefs.getString('device') ?? '';
    if (device.isEmpty) {
      device = AgentApi.newDeviceId();
      await prefs.setString('device', device);
    }
    final pairing = Pairing.parse(prefs.getString('link') ?? '');
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => pairing == null ? ConnectPage(device: device) : ChatPage(api: AgentApi(pairing, device))));
  }

  @override
  Widget build(BuildContext context) => const Scaffold(body: Center(child: CircularProgressIndicator()));
}

class ConnectPage extends StatefulWidget {
  const ConnectPage({super.key, required this.device, this.error});

  final String device;
  final String? error;

  @override
  State<ConnectPage> createState() => _ConnectPageState();
}

class _ConnectPageState extends State<ConnectPage> {
  final _link = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _error = widget.error;
  }

  Future<void> _connect(String text) async {
    final pairing = Pairing.parse(text);
    if (pairing == null) {
      setState(() => _error = 'Это не ссылка подключения. Откройте на ПК Настройки → «iPhone и Android» и отсканируйте QR-код.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = AgentApi(pairing, widget.device);
    try {
      await api.check();
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('link', pairing.link);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ChatPage(api: api)));
    } on AgentError catch (error) {
      setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _scan() async {
    final value = await Navigator.of(context).push<String>(MaterialPageRoute(builder: (_) => const ScanPage()));
    if (value != null) {
      _link.text = value;
      await _connect(value);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Подключение к ПК')),
      body: ListView(padding: const EdgeInsets.all(20), children: [
        const Icon(Icons.computer_rounded, size: 72, color: accent),
        const SizedBox(height: 16),
        const Text(
          'Запустите «Андрея» на компьютере и откройте Настройки → «iPhone и Android». '
          'Телефон и ПК должны быть в одной сети Wi‑Fi.',
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 24),
        FilledButton.icon(
          onPressed: _busy ? null : _scan,
          icon: const Icon(Icons.qr_code_scanner_rounded),
          label: const Text('Сканировать QR-код'),
        ),
        const SizedBox(height: 24),
        TextField(
          controller: _link,
          decoration: const InputDecoration(labelText: 'или вставьте ссылку подключения', border: OutlineInputBorder()),
          keyboardType: TextInputType.url,
          onSubmitted: _connect,
        ),
        const SizedBox(height: 12),
        OutlinedButton(onPressed: _busy ? null : () => _connect(_link.text), child: const Text('Подключиться')),
        if (_busy) const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
      ]),
    );
  }
}

class ScanPage extends StatefulWidget {
  const ScanPage({super.key});

  @override
  State<ScanPage> createState() => _ScanPageState();
}

class _ScanPageState extends State<ScanPage> {
  bool _done = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Наведите камеру на QR-код')),
      body: MobileScanner(onDetect: (capture) {
        final value = capture.barcodes.map((code) => code.rawValue).whereType<String>().firstOrNull;
        if (value == null || _done || Pairing.parse(value) == null) return;
        _done = true;
        Navigator.of(context).pop(value);
      }),
    );
  }
}

class Message {
  Message(this.mine, this.text);
  final bool mine;
  final String text;
}

class ChatPage extends StatefulWidget {
  const ChatPage({super.key, required this.api});

  final AgentApi api;

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _recorder = AudioRecorder();
  final _tts = Speaker();
  final List<Message> _messages = [];
  bool _recording = false;
  bool _busy = false;
  bool _speak = true;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (mounted) setState(() => _speak = prefs.getBool('speak') ?? true);
    });
    _loadHistory();
  }

  @override
  void dispose() {
    _recorder.dispose();
    _tts.stop();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _loadHistory() async {
    try {
      final items = await widget.api.history();
      if (!mounted) return;
      setState(() {
        _messages
          ..clear()
          ..addAll(items.skip(items.length > 50 ? items.length - 50 : 0).map((m) => Message(m['role'] == 'user', m['text']!)));
      });
      _toBottom();
    } on AgentError catch (error) {
      _add(false, error.message);
    }
  }

  void _add(bool mine, String text) {
    if (!mounted || text.isEmpty) return;
    setState(() => _messages.add(Message(mine, text)));
    _toBottom();
  }

  void _toBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      }
    });
  }

  Future<void> _send(String text) async {
    text = text.trim();
    if (text.isEmpty || _busy) return;
    _input.clear();
    _add(true, text);
    setState(() => _busy = true);
    try {
      final answer = await widget.api.send(text);
      _add(false, answer);
      if (_speak && answer.isNotEmpty) await _tts.speak(answer);
    } on AgentError catch (error) {
      _add(false, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _toggleRecording() async {
    if (_recording) {
      final path = await _recorder.stop();
      setState(() => _recording = false);
      if (path == null) return;
      final file = File(path);
      setState(() => _busy = true);
      try {
        final text = await widget.api.transcribe(await file.readAsBytes());
        if (!mounted) return;
        setState(() => _busy = false);
        if (text.isEmpty) {
          _add(false, 'Не расслышал. Попробуйте ещё раз.');
        } else {
          await _send(text);
        }
      } on AgentError catch (error) {
        _add(false, error.message);
      } finally {
        if (mounted) setState(() => _busy = false);
        if (await file.exists()) await file.delete();
      }
      return;
    }
    if (!await _recorder.hasPermission()) {
      _add(false, 'Разрешите доступ к микрофону в настройках Android, чтобы говорить с агентом.');
      return;
    }
    await _tts.stop();
    final folder = await getTemporaryDirectory();
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: '${folder.path}/voice.wav',
    );
    setState(() => _recording = true);
  }

  Future<void> _disconnect() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('link');
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ConnectPage(device: widget.api.device)));
  }

  Future<void> _toggleSpeak() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() => _speak = !_speak);
    await prefs.setBool('speak', _speak);
    if (!_speak) await _tts.stop();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Андрей'),
          Text(widget.api.route, style: Theme.of(context).textTheme.bodySmall),
        ]),
        actions: [
          IconButton(
            tooltip: _speak ? 'Не озвучивать ответы' : 'Озвучивать ответы',
            icon: Icon(_speak ? Icons.volume_up_rounded : Icons.volume_off_rounded),
            onPressed: _toggleSpeak,
          ),
          IconButton(
            tooltip: 'Пауза: остановить команду на ПК',
            icon: const Icon(Icons.pause_circle_outline_rounded),
            onPressed: () async {
              await _tts.stop();
              try {
                await widget.api.cancel();
              } on AgentError catch (error) {
                _add(false, error.message);
              }
            },
          ),
          PopupMenuButton<String>(
            onSelected: (value) => value == 'disconnect' ? _disconnect() : _loadHistory(),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'refresh', child: Text('Обновить историю')),
              PopupMenuItem(value: 'disconnect', child: Text('Подключить другой ПК')),
            ],
          ),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: _messages.isEmpty
              ? const Center(
                  child: Padding(
                  padding: EdgeInsets.all(32),
                  child: Text('Нажмите на микрофон и скажите, например:\n«Открой Telegram» или «Какая погода?»',
                      textAlign: TextAlign.center),
                ))
              : ListView.builder(
                  controller: _scroll,
                  padding: const EdgeInsets.all(12),
                  itemCount: _messages.length,
                  itemBuilder: (_, index) {
                    final message = _messages[index];
                    return Align(
                      alignment: message.mine ? Alignment.centerRight : Alignment.centerLeft,
                      child: Container(
                        margin: const EdgeInsets.symmetric(vertical: 4),
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
                        decoration: BoxDecoration(
                          color: message.mine ? accent : scheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: SelectableText(message.text),
                      ),
                    );
                  },
                ),
        ),
        if (_busy) const LinearProgressIndicator(),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  enabled: !_recording,
                  textInputAction: TextInputAction.send,
                  onSubmitted: _send,
                  decoration: const InputDecoration(hintText: 'Команда для ПК…', border: OutlineInputBorder()),
                ),
              ),
              const SizedBox(width: 8),
              FloatingActionButton(
                onPressed: _busy && !_recording ? null : _toggleRecording,
                backgroundColor: _recording ? scheme.error : accent,
                tooltip: _recording ? 'Остановить запись' : 'Сказать команду',
                child: Icon(_recording ? Icons.stop_rounded : Icons.mic_rounded),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}
