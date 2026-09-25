/* Settings window: autosave, theme gallery, models, AI keys, hotkey capture. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fields = [...document.querySelectorAll('[data-setting]')];
  let pending = {}, timer = null;

  // ---------- навигация ----------
  function show(page) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + page));
    Agent.store.set('agent_settings_page', page);
    if (page === 'recognition') refreshModels();
    if (page === 'voice') loadMicrophones();
    if (page === 'ai') refreshAI();
    if (page === 'licenses') loadLicenses();
  }
  document.querySelectorAll('.nav-item').forEach(b => b.onclick = () => show(b.dataset.page));

  // ---------- поля ----------
  function valueOf(el) {
    if (el.type === 'checkbox') return el.checked;
    if (el.type === 'range' || el.type === 'number') return Number(el.value);
    return el.value.trim();
  }
  function paintOutput(el) {
    const out = document.querySelector(`output[data-for="${el.dataset.setting}"]`);
    if (out) out.textContent = el.value + ' ' + (el.dataset.unit || '');
  }
  function fill(settings) {
    fields.forEach(el => {
      const key = el.dataset.setting;
      if (!(key in settings) || el === document.activeElement) return;
      if (el.type === 'checkbox') el.checked = !!settings[key];
      else {
        if (el.tagName === 'SELECT' && ![...el.options].some(o => o.value === String(settings[key])))
          el.add(new Option(settings[key] || 'Системный по умолчанию', settings[key]));
        el.value = settings[key];
      }
      paintOutput(el);
    });
    document.querySelectorAll('.name-ref').forEach(n => n.textContent = settings.wake_word || 'Андрей');
    document.querySelectorAll('[data-provider]').forEach(b => b.hidden = b.dataset.provider !== settings.llm_provider);
    $('hotkey').value = prettyHotkey(settings.hotkey);
    document.querySelectorAll('.theme-card').forEach(c => c.classList.toggle('selected', c.dataset.value === settings.theme));
    paintSecrets();
  }

  function state(text, kind) {
    const pill = $('save-state');
    pill.className = 'pill ' + (kind || '');
    pill.lastElementChild.textContent = text;
  }

  function queue(partial, immediate) {
    Object.assign(pending, partial);
    state('Сохранение…', 'warn');
    clearTimeout(timer);
    timer = setTimeout(flush, immediate ? 0 : 350);
  }
  async function flush() {
    const body = pending; pending = {};
    try {
      const settings = await Agent.saveSettings(body);
      fill(settings);
      state('Сохранено', 'ok');
    } catch (e) {
      state(e.message, 'bad');
      Agent.toast(e.message, 4000);
      fill(Agent.settings);
    }
  }

  fields.forEach(el => {
    if (el.id === 'hotkey') return;
    const key = el.dataset.setting;
    const handler = () => { paintOutput(el); queue({ [key]: valueOf(el) }, el.type === 'checkbox'); };
    if (el.type === 'range') { el.addEventListener('input', () => paintOutput(el)); el.addEventListener('change', handler); }
    else if (el.tagName === 'INPUT' && el.type !== 'checkbox') { el.addEventListener('change', handler); el.addEventListener('keydown', e => e.key === 'Enter' && el.blur()); }
    else el.addEventListener('change', handler);
  });
  document.querySelector('[data-setting="llm_gpu"]').addEventListener('change', () => setTimeout(refreshAI, 700));
  $('provider').addEventListener('change', e => document.querySelectorAll('[data-provider]').forEach(b => b.hidden = b.dataset.provider !== e.target.value));

  // ---------- горячая клавиша ----------
  function prettyHotkey(spec) {
    return String(spec || 'ctrl+alt+space').split('+').map(k => ({ ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', win: 'Win', space: 'Пробел' }[k] || k.toUpperCase())).join(' + ');
  }
  const KEYMAP = { ' ': 'space', Spacebar: 'space', Enter: 'enter', Escape: 'esc', Tab: 'tab', Insert: 'insert', Delete: 'delete', Home: 'home', End: 'end', PageUp: 'pageup', PageDown: 'pagedown' };
  let capturing = false;
  $('hotkey').onclick = () => { capturing = true; $('hotkey').classList.add('capturing'); $('hotkey').value = 'Нажмите сочетание…'; };
  $('hotkey').onblur = () => { capturing = false; $('hotkey').classList.remove('capturing'); $('hotkey').value = prettyHotkey(Agent.settings.hotkey); };
  $('hotkey').onkeydown = e => {
    if (!capturing) return;
    e.preventDefault();
    if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return;
    const mods = [e.ctrlKey && 'ctrl', e.altKey && 'alt', e.shiftKey && 'shift', e.metaKey && 'win'].filter(Boolean);
    let key = KEYMAP[e.key] || (/^F\d{1,2}$/.test(e.key) ? e.key.toLowerCase() : (e.code.startsWith('Key') ? e.code.slice(3).toLowerCase() : e.code.startsWith('Digit') ? e.code.slice(5) : ''));
    if (!key || !mods.length) { Agent.toast('Нужен модификатор (Ctrl, Alt, Shift или Win) и клавиша.'); return; }
    const spec = [...mods, key].join('+');
    capturing = false;
    $('hotkey').classList.remove('capturing');
    $('hotkey').value = prettyHotkey(spec);
    queue({ hotkey: spec }, true);
    $('hotkey').blur();
  };

  // ---------- темы ----------
  function buildThemes() {
    const box = $('themes');
    Agent.THEMES.forEach(theme => {
      const card = document.createElement('button');
      card.className = 'theme-card';
      card.dataset.value = theme.id;
      card.dataset.theme = theme.id;
      card.setAttribute('aria-label', 'Тема ' + theme.name);
      card.innerHTML = '<div class="scene" data-compact="1"></div><span class="check">✓</span>' +
        '<div class="theme-preview"><div class="mini-orb"></div><div class="mini-chat"><i></i><i class="u"></i><i class="s"></i></div></div>' +
        '<div class="theme-info"><b></b><small></small></div>';
      card.querySelector('b').textContent = theme.name;
      card.querySelector('small').textContent = theme.note;
      card.onclick = () => { document.querySelectorAll('.theme-card').forEach(c => c.classList.toggle('selected', c === card)); queue({ theme: theme.id }, true); };
      box.appendChild(card);
      if (window.AgentMotion) AgentMotion.decorate(card.querySelector('.scene'), theme.id);
    });
  }

  // ---------- ИИ ----------
  function paintSecrets() {
    const s = Agent.secrets || {};
    $('openai-state').textContent = s.openai_api_key ? '✓ Ключ сохранён на этом ПК.' : 'Не нужен для локальных серверов.';
  }
  document.querySelectorAll('[data-preset]').forEach(b => b.onclick = () => {
    const [url, model] = b.dataset.preset.split('|');
    queue({ openai_base_url: url, openai_model: model }, true);
    if (!/127\.0\.0\.1|localhost/.test(url)) Agent.toast('Получите бесплатный ключ на сайте сервиса и вставьте его ниже.', 5000);
  });

  async function refreshAI() {
    try {
      const [ai, models] = await Promise.all([Agent.api('ai/status'), Agent.api('models/status')]);
      const local = ai.local || {};
      $('llm-state').textContent = ai.provider !== 'local' ? 'Используется внешний сервер.' :
        local.ready ? '✓ Работает на этом ПК' + (local.runtime === 'vulkan' ? ' · видеокарта' : ' · процессор') :
        local.starting ? 'Загружается в память…' :
        !local.runtime_installed || !local.model_installed ? 'Не установлена — нажмите «Скачать» ниже' : (local.error || 'Запустится при первом вопросе');
      const list = $('llm-models');
      list.replaceChildren();
      const rows = [['llama:cpu', { title: 'Движок llama.cpp (процессор)', size_mb: 30, installed: models.llama.cpu.installed }]];
      if (Agent.settings.llm_gpu) rows.push(['llama:vulkan', { title: 'Движок llama.cpp (видеокарта, Vulkan)', size_mb: 50, installed: models.llama.vulkan.installed }]);
      ['qwen3-4b', 'qwen2.5-7b', 'qwen3-1.7b'].filter(k => models.llm[k]).forEach(key => rows.push(['llm:' + key, models.llm[key]]));
      $('download-ai').hidden = models.llama.cpu.installed && models.llm[Agent.settings.local_model] && models.llm[Agent.settings.local_model].installed;
      rows.forEach(([key, info]) => list.appendChild(modelRow(key, info)));
    } catch (e) { $('llm-state').textContent = e.message; }
  }

  function modelRow(key, info) {
    const row = document.createElement('div');
    row.className = 'model';
    row.innerHTML = '<div><b></b><small></small></div><div class="control"></div>';
    row.querySelector('b').textContent = labels[key] || info.title;
    row.querySelector('small').textContent = [info.size_mb ? `≈ ${info.size_mb >= 1000 ? (info.size_mb / 1000).toFixed(1).replace('.', ',') + ' ГБ' : info.size_mb + ' МБ'}` : '', info.ram_gb ? `ОЗУ от ${info.ram_gb} ГБ` : ''].filter(Boolean).join(' · ');
    const control = row.querySelector('.control');
    const badge = document.createElement('span');
    badge.className = 'badge ' + (info.installed ? 'ok' : '');
    badge.id = 'badge-' + key;
    badge.textContent = info.installed ? 'Установлена' : 'Не установлена';
    control.appendChild(badge);
    if (!info.installed) {
      const button = document.createElement('button');
      button.className = 'btn';
      button.textContent = 'Скачать';
      button.onclick = () => download([key]);
      control.appendChild(button);
    }
    return row;
  }

  document.querySelectorAll('[data-secret]').forEach(button => button.onclick = async () => {
    const input = $(button.dataset.input);
    try {
      const data = await Agent.post('secrets', { name: button.dataset.secret, value: input.value.trim() });
      Agent.secrets = data.secrets;
      input.value = '';
      paintSecrets();
      Agent.toast('Ключ сохранён');
    } catch (e) { Agent.toast(e.message); }
  });
  $('test-ai').onclick = async () => {
    const out = $('ai-test-result');
    out.textContent = 'Проверяю…';
    $('test-ai').disabled = true;
    try { const r = await Agent.post('ai/test'); out.textContent = `✓ ${r.response} (${r.elapsed} с)`; }
    catch (e) { out.textContent = '✗ ' + e.message; }
    finally { $('test-ai').disabled = false; }
  };

  // ---------- микрофоны и голоса ----------
  async function loadMicrophones() {
    try {
      const data = await Agent.api('audio/devices');
      const select = $('mic-select');
      const current = Agent.settings.native_microphone || '';
      select.replaceChildren(new Option('Системный по умолчанию', ''));
      data.devices.forEach(d => select.add(new Option(d.label + (d.default ? ' (по умолчанию)' : ''), d.id)));
      if (current && ![...select.options].some(o => o.value === current)) select.add(new Option(current + ' (не найден)', current));
      select.value = current;
    } catch (e) { /* нет звуковой подсистемы */ }
  }
  $('refresh-mics').onclick = loadMicrophones;

  async function loadVoices() {
    try {
      const data = await Agent.api('ai/voices');
      const mark = (select, lang) => [...select.options].forEach(o => {
        const v = data.voices.find(x => x.id === o.value);
        if (v && !v.installed) o.textContent = o.textContent.replace(/ \(не установлен\)$/, '') + ' (не установлен)';
      });
      mark($('voice-ru'), 'ru'); mark($('voice-en'), 'en');
    } catch (e) { /* */ }
  }
  $('test-voice').onclick = async () => {
    try {
      const r = await Agent.post('tts/speak', { text: `Привет! Я ${Agent.settings.wake_word || 'Андрей'}. Так звучит мой голос.` });
      if (!r.native) Agent.toast('Озвучка на этом устройстве недоступна.');
    } catch (e) { Agent.toast(e.message); }
  };

  // ---------- модели ----------
  const labels = { vad: 'Детектор речи Silero VAD', piper: 'Голоса Piper (Ирина, Денис, Amy)' };
  async function refreshModels() {
    try {
      const [models, speech] = await Promise.all([Agent.api('models/status'), Agent.api('speech/status')]);
      $('engine-now').textContent = speech.ready ? `Сейчас работает: ${speech.engine}${speech.gpu ? ' · видеокарта' : ' · процессор'}${speech.last_elapsed ? ' · последняя фраза за ' + Math.round(speech.last_elapsed * 1000) + ' мс' : ''}`
        : speech.loading ? `Загружается: ${speech.engine}…` : (speech.error || 'Модель не загружена');
      const list = $('models');
      list.replaceChildren();
      const rows = [['vad', models.vad], ...Object.entries(models.stt)];
      rows.push(['piper', { title: labels.piper, installed: Object.values(models.piper).some(v => v.installed) }]);
      rows.forEach(([key, info]) => list.appendChild(modelRow(key, info)));
      $('download-all').disabled = models.downloading;
    } catch (e) { $('engine-now').textContent = e.message; }
  }
  async function download(items) {
    try {
      const r = await Agent.post('models/download', { items });
      if (!r.started) Agent.toast('Загрузка уже идёт.');
      $('download-all').disabled = true;
    } catch (e) { Agent.toast(e.message); }
  }
  $('download-ai').onclick = () => download(['llama:' + (Agent.settings.llm_gpu ? 'vulkan' : 'cpu'), 'llm:' + (Agent.settings.local_model || 'qwen3-4b')]);
  $('download-all').onclick = () => download(['vad', 'parakeet', 'gigaam', 'piper']);
  $('reload-model').onclick = async () => { await Agent.post('speech/load').catch(e => Agent.toast(e.message)); setTimeout(refreshModels, 800); };

  // ---------- лицензии ----------
  let licensesLoaded = false;
  async function loadLicenses() {
    if (licensesLoaded) return;
    const box = $('licenses');
    try {
      const data = await Agent.api('licenses');
      box.replaceChildren();
      const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
      data.sections.forEach(section => {
        const group = el('div', 'card group');
        group.append(el('h3', null, section.title), el('p', 'hint', section.note));
        section.items.forEach(item => {
          const row = el('div', 'row');
          const label = el('div', 'label');
          label.append(el('b', null, item.name), el('small', null, item.author));
          if (item.attribution) label.append(el('small', null, item.attribution));
          const control = el('div', 'control');
          const link = el('a', 'badge', item.license);
          link.href = item.url; link.target = '_blank'; link.rel = 'noopener';
          control.append(link);
          row.append(label, control);
          group.append(row);
        });
        box.append(group);
      });
      const voices = el('div', 'card group');
      voices.append(el('h3', null, 'Карточки голосов Piper'), el('p', 'hint', 'Лицензия и авторы датасета каждого голоса — из его карточки (MODEL_CARD), скачанной вместе с голосом.'));
      data.voices.forEach(v => {
        const row = el('div', 'row stack');
        const label = el('div', 'label');
        label.append(el('b', null, v.title));
        label.append(el('small', null, !v.installed ? 'Голос не установлен.' : v.card ? '' : 'Карточка не найдена — скачайте голос заново в разделе «Распознавание».'));
        row.append(label);
        if (v.card) { const pre = el('pre', 'hint', v.card); pre.style.whiteSpace = 'pre-wrap'; pre.style.margin = '0'; row.append(pre); }
        voices.append(row);
      });
      box.append(voices);
      licensesLoaded = true;
    } catch (e) { box.textContent = e.message; }
  }

  // ---------- телефон и профиль ----------
  async function loadConnection() {
    try {
      const c = await Agent.api('connection');
      $('pc-address').textContent = `http://${c.ip}:${c.port}`;
      $('connection-token').value = c.token;
      $('storage').textContent = 'Данные хранятся на ПК: ' + c.storage;
      $('profile').textContent = c.user ? 'Профиль: ' + c.user : 'Гостевой профиль этого устройства';
    } catch (e) { /* */ }
  }
  $('show-token').onclick = () => { const t = $('connection-token'); t.type = t.type === 'password' ? 'text' : 'password'; $('show-token').textContent = t.type === 'password' ? 'Показать' : 'Скрыть'; };
  for (const action of ['register', 'login', 'logout']) $(action).onclick = async () => {
    try {
      await Agent.post(action, { name: $('username').value, password: $('password').value });
      $('password').value = '';
      $('account-status').textContent = action === 'register' ? 'Аккаунт создан. Теперь войдите.' : 'Готово';
      if (action !== 'register') { await Agent.loadSettings(); fill(Agent.settings); loadConnection(); }
    } catch (e) { $('account-status').textContent = e.message; }
  };
  $('export').onclick = async () => {
    try {
      const data = await Agent.api('export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a'); a.href = url; a.download = 'LocalAIAgent-data.json'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) { Agent.toast(e.message); }
  };
  $('clear-history').onclick = async () => { if (confirm('Удалить историю диалога?')) { await Agent.post('history/clear'); Agent.toast('История очищена'); } };

  // ---------- живые события ----------
  function onEvent(e) {
    if (e.type === 'download') {
      const badge = $('badge-' + e.item);
      if (badge) {
        badge.className = 'badge ' + (e.stage === 'done' ? 'ok' : e.stage === 'error' ? 'bad' : 'busy');
        badge.textContent = e.stage === 'start' ? 'Скачивается…' : e.stage === 'progress' ? `Скачивается ${e.detail.percent}% · ${e.detail.done_mb} из ${e.detail.total_mb} МБ`
          : e.stage === 'done' ? 'Установлена' : e.stage === 'error' ? 'Ошибка' : badge.textContent;
        const row = badge.closest('.model');
        let note = row && row.querySelector('.model-error');
        if (e.stage === 'error' && row) {
          if (!note) { note = document.createElement('small'); note.className = 'model-error'; note.style.color = 'var(--bad)'; row.firstElementChild.appendChild(note); }
          note.textContent = 'Ошибка: ' + (e.detail || 'неизвестная') + '. Подробности: logs/agent.log';
          Agent.toast('Не удалось скачать: ' + (e.detail || ''), 7000);
        } else if (note && e.stage === 'start') note.remove();
      }
      if (e.item === 'all' && e.stage === 'finished') { Agent.toast('Загрузка завершена'); refreshModels(); refreshAI(); }
    } else if (e.type === 'settings') {
      Agent.settings = e.settings; fill(e.settings);
      if (document.getElementById('page-ai').classList.contains('active')) refreshAI();
    }
  }

  Agent.onSettings(settings => { Agent.settings = settings; fill(settings); });
  document.addEventListener('agent-unpaired', () => state('Нет кода подключения — откройте настройки из главного окна', 'bad'));

  (async () => {
    buildThemes();
    try {
      await Agent.loadSettings();
      fill(Agent.settings);
      loadVoices();
      loadConnection();
      Agent.connectEvents(onEvent);
      const wanted = new URLSearchParams(location.search).get('section') || Agent.store.get('agent_settings_page') || 'general';
      show(document.getElementById('page-' + wanted) ? wanted : 'general');
    } catch (e) { state(e.message, 'bad'); }
  })();
})();
