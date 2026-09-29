// Разделы «Команды» и «Настройки» — те же, что в окне настроек на ПК.
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'main.dart' show Appearance;
import 'theme.dart';

/// Стеклянная карточка, как на ПК.
class GlassCard extends StatelessWidget {
  const GlassCard({super.key, required this.children, this.title});

  final List<Widget> children;
  final String? title;

  @override
  Widget build(BuildContext context) {
    final p = Appearance.instance.palette;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (title != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(title!, style: TextStyle(color: p.accent, fontWeight: FontWeight.w700, fontSize: 15)),
            ),
          ...children,
        ]),
      ),
    );
  }
}

// ---------------- Все команды ----------------
class CommandsPage extends StatefulWidget {
  const CommandsPage({super.key, required this.api});

  final AgentApi api;

  @override
  State<CommandsPage> createState() => _CommandsPageState();
}

class _CommandsPageState extends State<CommandsPage> {
  List<Map<String, dynamic>> _categories = [];
  String _query = '';
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final data = await widget.api.commands();
      if (mounted) setState(() => _categories = data);
    } on AgentError catch (error) {
      if (mounted) setState(() => _error = error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = Appearance.instance.palette;
    final q = _query.toLowerCase();
    final cards = <Widget>[];
    for (final category in _categories) {
      final items = (category['items'] as List).cast<Map>().where((i) =>
          q.isEmpty || '${category['title']} ${i['say']} ${i['does']}'.toLowerCase().contains(q)).toList();
      if (items.isEmpty) continue;
      cards.add(GlassCard(title: '${category['icon']} ${category['title']}', children: [
        for (final item in items)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: RichText(
              text: TextSpan(style: TextStyle(color: p.text, fontSize: 14), children: [
                TextSpan(text: '«${item['say']}»', style: const TextStyle(fontWeight: FontWeight.w600)),
                TextSpan(text: ' — ${item['does']}', style: TextStyle(color: p.muted)),
              ]),
            ),
          ),
      ]));
      cards.add(const SizedBox(height: 12));
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Все команды')),
      body: ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 20), children: [
        Text('Говорите после имени: «Андрей, открой Telegram».', style: TextStyle(color: p.muted)),
        const SizedBox(height: 10),
        TextField(
          decoration: const InputDecoration(prefixIcon: Icon(Icons.search_rounded), hintText: 'Поиск: вкладка, музыка, word…'),
          onChanged: (value) => setState(() => _query = value),
        ),
        const SizedBox(height: 12),
        if (_error != null) Text(_error!, style: TextStyle(color: p.bad)),
        if (_categories.isEmpty && _error == null) const Center(child: CircularProgressIndicator()),
        ...cards,
      ]),
    );
  }
}

// ---------------- Настройки ----------------
const _icons = {
  'person': Icons.person_outline_rounded, 'mic': Icons.mic_none_rounded, 'volume': Icons.volume_up_outlined,
  'sparkle': Icons.auto_awesome_outlined, 'desktop': Icons.desktop_windows_outlined,
  'palette': Icons.palette_outlined, 'phone': Icons.smartphone_rounded,
};

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.api, required this.onDisconnect});

  final AgentApi api;
  final VoidCallback onDisconnect;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  List<Map<String, dynamic>> _sections = [];
  Map<String, dynamic> _values = {};
  bool _premium = true;
  String? _error;
  String _voiceSource = 'pc';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    _voiceSource = prefs.getString('voice_source') ?? 'pc';
    try {
      final data = await widget.api.remoteSettings();
      if (!mounted) return;
      setState(() {
        _sections = (data['sections'] as List).cast<Map<String, dynamic>>();
        _values = Map<String, dynamic>.from(data['values'] as Map);
        _premium = data['premium'] != false;
        _error = null;
      });
    } on AgentError catch (error) {
      if (mounted) setState(() => _error = error.message);
    }
  }

  Future<void> _save(String key, dynamic value) async {
    final previous = _values[key];
    setState(() => _values[key] = value);
    try {
      final saved = await widget.api.saveSettings({key: value});
      if (!mounted) return;
      setState(() => _values = saved);
      if (key == 'theme') Appearance.instance.set(value.toString());
    } on AgentError catch (error) {
      if (!mounted) return;
      setState(() => _values[key] = previous);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  Future<void> _setVoiceSource(String value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('voice_source', value);
    setState(() => _voiceSource = value);
  }

  @override
  Widget build(BuildContext context) {
    final p = Appearance.instance.palette;
    return Scaffold(
      appBar: AppBar(title: const Text('Настройки'), actions: [
        IconButton(tooltip: 'Обновить', icon: const Icon(Icons.refresh_rounded), onPressed: _load),
      ]),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 24), children: [
          Text('Это настройки ассистента на вашем ПК — те же, что в окне «Настройки» на компьютере.',
              style: TextStyle(color: p.muted)),
          const SizedBox(height: 12),
          GlassCard(title: '📱 На этом телефоне', children: [
            _choice('Голос ответов', _voiceSource, const {'pc': 'Как на ПК (Джарвис, Пятница, дикторы)',
                'phone': 'Голос телефона'}, _setVoiceSource),
            const SizedBox(height: 6),
            OutlinedButton.icon(onPressed: widget.onDisconnect, icon: const Icon(Icons.link_off_rounded),
                label: const Text('Подключить другой ПК')),
          ]),
          const SizedBox(height: 12),
          if (_error != null) Text(_error!, style: TextStyle(color: p.bad)),
          if (_sections.isEmpty && _error == null) const Center(child: CircularProgressIndicator()),
          for (final section in _sections) ...[
            _section(section, p),
            const SizedBox(height: 12),
          ],
        ]),
      ),
    );
  }

  Widget _section(Map<String, dynamic> section, Palette p) {
    final locked = section['premium'] == true && !_premium;
    return Card(
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          leading: Icon(_icons[section['icon']] ?? Icons.settings_outlined, color: p.accent),
          title: Text(section['title'].toString(), style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: locked ? Text('Доступно по подписке', style: TextStyle(color: p.muted, fontSize: 12)) : null,
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          children: [for (final field in (section['fields'] as List).cast<Map<String, dynamic>>()) _field(field, p, locked)],
        ),
      ),
    );
  }

  Widget _field(Map<String, dynamic> field, Palette p, bool locked) {
    final key = field['key'] as String;
    final value = _values[key];
    final label = field['label'].toString();
    final hint = field['hint']?.toString();
    switch (field['type']) {
      case 'bool':
        return SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(label),
          subtitle: hint == null ? null : Text(hint, style: TextStyle(color: p.muted, fontSize: 12)),
          value: value == true,
          onChanged: locked ? null : (v) => _save(key, v),
        );
      case 'select':
        final options = {
          for (final o in (field['options'] as List).cast<Map>()) o['value'].toString(): o['label'].toString()
        };
        return _choice(label, value?.toString() ?? '', options, locked ? null : (v) => _save(key, v));
      case 'range':
        final min = (field['min'] as num).toDouble(), max = (field['max'] as num).toDouble();
        final current = ((value as num?)?.toDouble() ?? min).clamp(min, max);
        return Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('$label: ${current.round()}'),
            Slider(
              value: current,
              min: min,
              max: max,
              divisions: ((max - min) / ((field['step'] as num?) ?? 1)).round(),
              onChanged: locked ? null : (v) => setState(() => _values[key] = v.round()),
              onChangeEnd: locked ? null : (v) => _save(key, v.round()),
            ),
          ]),
        );
      default:
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: TextFormField(
            key: ValueKey('$key-$value'),
            initialValue: value?.toString() ?? '',
            enabled: !locked,
            decoration: InputDecoration(labelText: label, helperText: hint),
            onFieldSubmitted: (v) => _save(key, v.trim()),
          ),
        );
    }
  }

  Widget _choice(String label, String value, Map<String, String> options, ValueChanged<String>? onChanged) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: DropdownButtonFormField<String>(
        initialValue: options.containsKey(value) ? value : null,
        isExpanded: true,
        decoration: InputDecoration(labelText: label),
        items: [for (final e in options.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
        onChanged: onChanged == null ? null : (v) => v == null ? null : onChanged(v),
      ),
    );
  }
}
