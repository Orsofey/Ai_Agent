// «Андрей» для Android: голосовой и текстовый пульт ИИ-агента на ПК — в том же оформлении, что и на компьютере.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'pages.dart';
import 'speaker.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AgentApp());
}

/// Тема приложения — та же, что выбрана на ПК (Настройки → Оформление); запоминается на телефоне.
class Appearance extends ChangeNotifier {
  Appearance._();
  static final instance = Appearance._();

  Palette palette = paletteOf('aurora');

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    palette = paletteOf(prefs.getString('theme'));
    notifyListeners();
  }

  Future<void> set(String? id) async {
    if (id == null || id == palette.id || !palettes.containsKey(id)) return;
    palette = paletteOf(id);
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('theme', id);
  }
}

class AgentApp extends StatefulWidget {
  const AgentApp({super.key});

  @override
  State<AgentApp> createState() => _AgentAppState();
}

class _AgentAppState extends State<AgentApp> {
  @override
  void initState() {
    super.initState();
    Appearance.instance.load();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: Appearance.instance,
      builder: (context, _) {
        final palette = Appearance.instance.palette;
        return MaterialApp(
          title: 'Андрей',
          debugShowCheckedModeBanner: false,
          theme: themeFor(palette),
          builder: (context, child) => Scene(palette: palette, child: child ?? const SizedBox()),
          home: const StartPage(),
        );
      },
    );
  }
}

/// Загружает сохранённое подключение и открывает главный экран или экран подключения.
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
        builder: (_) => pairing == null ? ConnectPage(device: device) : HomePage(api: AgentApi(pairing, device))));
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
      setState(() => _error = 'Это не ссылка подключения. Откройте на ПК Настройки → «Телефон» и отсканируйте QR-код.');
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
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => HomePage(api: api)));
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
    final p = Appearance.instance.palette;
    return Scaffold(
      appBar: AppBar(title: const Text('Подключение к ПК')),
      body: ListView(padding: const EdgeInsets.all(20), children: [
        Center(child: Orb(palette: p, active: _busy, size: 110)),
        const SizedBox(height: 22),
        GlassCard(children: [
          Text('Запустите «Андрея» на компьютере и откройте Настройки → «Телефон». Дома подключение идёт по Wi‑Fi, '
              'а с включённым «Доступом через интернет» — из любой сети.',
              textAlign: TextAlign.center, style: TextStyle(color: p.muted)),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: _busy ? null : _scan,
            icon: const Icon(Icons.qr_code_scanner_rounded),
            label: const Text('Сканировать QR-код'),
          ),
          const SizedBox(height: 18),
          TextField(
            controller: _link,
            decoration: const InputDecoration(labelText: 'или вставьте ссылку подключения'),
            keyboardType: TextInputType.url,
            onSubmitted: _connect,
          ),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: _busy ? null : () => _connect(_link.text), child: const Text('Подключиться')),
          if (_busy) const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
          if (_error != null)
            Padding(padding: const EdgeInsets.only(top: 16), child: Text(_error!, style: TextStyle(color: p.bad))),
        ]),
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

/// Главный экран: «Диалог», «Команды», «Настройки» — как разделы окна на ПК.
class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.api});

  final AgentApi api;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _tab = 0;

  @override
  void initState() {
    super.initState();
    // Тема ПК — сразу при запуске, чтобы телефон выглядел так же.
    widget.api.remoteSettings().then((data) {
      final values = data['values'];
      if (values is Map) Appearance.instance.set(values['theme']?.toString());
    }).catchError((_) {});
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      ChatPage(api: widget.api),
      CommandsPage(api: widget.api),
      SettingsPage(api: widget.api, onDisconnect: _disconnect),
    ];
    return Scaffold(
      body: IndexedStack(index: _tab, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.graphic_eq_rounded), label: 'Диалог'),
          NavigationDestination(icon: Icon(Icons.terminal_rounded), label: 'Команды'),
          NavigationDestination(icon: Icon(Icons.tune_rounded), label: 'Настройки'),
        ],
      ),
    );
  }

  Future<void> _disconnect() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('link');
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ConnectPage(device: widget.api.device)));
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
  final _speaker = Speaker();
  final List<Message> _messages = [];
  bool _recording = false;
  bool _busy = false;
  bool _speak = true;
  bool _pcVoice = true;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (mounted) {
        setState(() {
          _speak = prefs.getBool('speak') ?? true;
          _pcVoice = (prefs.getString('voice_source') ?? 'pc') == 'pc';
        });
      }
    });
    _loadHistory();
  }

  @override
  void dispose() {
    _recorder.dispose();
    _speaker.stop();
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

  /// Ответ — голосом ассистента с ПК (Джарвис, Пятница, дикторы); если не вышло — голосом телефона.
  Future<void> _say(String text) async {
    final prefs = await SharedPreferences.getInstance();
    _pcVoice = (prefs.getString('voice_source') ?? 'pc') == 'pc';
    if (_pcVoice) {
      try {
        await _speaker.play(await widget.api.voice(text));
        return;
      } catch (_) {
        // голоса на ПК не установлены или связь медленная — читаем голосом телефона
      }
    }
    await _speaker.speak(text);
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
      if (_speak && answer.isNotEmpty) await _say(answer);
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
    await _speaker.stop();
    final folder = await getTemporaryDirectory();
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: '${folder.path}/voice.wav',
    );
    setState(() => _recording = true);
  }

  Future<void> _toggleSpeak() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() => _speak = !_speak);
    await prefs.setBool('speak', _speak);
    if (!_speak) await _speaker.stop();
  }

  @override
  Widget build(BuildContext context) {
    final p = Appearance.instance.palette;
    final status = _recording ? 'Слушаю… нажмите ещё раз, чтобы отправить' : _busy ? 'Думаю…' : 'Нажмите на сферу и говорите';
    return Scaffold(
      appBar: AppBar(
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Андрей', style: TextStyle(fontWeight: FontWeight.w700, color: p.accent)),
          Text(widget.api.route, style: TextStyle(fontSize: 12, color: p.muted)),
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
              await _speaker.stop();
              try {
                await widget.api.cancel();
              } on AgentError catch (error) {
                _add(false, error.message);
              }
            },
          ),
          IconButton(tooltip: 'Обновить', icon: const Icon(Icons.refresh_rounded), onPressed: _loadHistory),
        ],
      ),
      body: Column(children: [
        GestureDetector(
          onTap: _busy && !_recording ? null : _toggleRecording,
          child: Padding(
            padding: const EdgeInsets.only(top: 6, bottom: 10),
            child: Orb(palette: p, active: _recording, size: _messages.isEmpty ? 170 : 96),
          ),
        ),
        Text(status, style: TextStyle(color: p.muted)),
        const SizedBox(height: 8),
        Expanded(
          child: _messages.isEmpty
              ? Center(
                  child: Padding(
                  padding: const EdgeInsets.all(32),
                  child: Text('Скажите, например:\n«Открой Telegram» или «Какая погода?»',
                      textAlign: TextAlign.center, style: TextStyle(color: p.muted)),
                ))
              : ListView.builder(
                  controller: _scroll,
                  padding: const EdgeInsets.all(12),
                  itemCount: _messages.length,
                  itemBuilder: (_, index) => Bubble(message: _messages[index], palette: p),
                ),
        ),
        if (_busy) LinearProgressIndicator(color: p.accent, backgroundColor: p.chip),
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
                  decoration: const InputDecoration(hintText: 'Спросите или дайте команду…'),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                onPressed: _busy ? null : () => _send(_input.text),
                icon: const Icon(Icons.send_rounded),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}

class Bubble extends StatelessWidget {
  const Bubble({super.key, required this.message, required this.palette});

  final Message message;
  final Palette palette;

  @override
  Widget build(BuildContext context) {
    final mine = message.mine;
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
        decoration: BoxDecoration(
          gradient: mine ? LinearGradient(colors: [palette.accent, palette.accent2]) : null,
          color: mine ? null : palette.surface,
          border: mine ? null : Border.all(color: palette.border),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(18), topRight: const Radius.circular(18),
            bottomLeft: Radius.circular(mine ? 18 : 4), bottomRight: Radius.circular(mine ? 4 : 18)),
        ),
        child: SelectableText(message.text, style: TextStyle(color: mine ? palette.onAccent : palette.text)),
      ),
    );
  }
}
