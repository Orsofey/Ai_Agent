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
    if (page === 'account') loadAccount();
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
    setTimeout(() => document.getElementById('voice-cards') && paintVoiceCards(), 0);
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
      card.onclick = () => { if (!account.premium) { Agent.toast('Темы доступны по подписке', 3000); show('account'); return; } document.querySelectorAll('.theme-card').forEach(c => c.classList.toggle('selected', c === card)); queue({ theme: theme.id }, true); };
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
      if (ai.timing && ai.timing.first_token != null) {
        $('llm-state').textContent += ` · последний ответ начался через ${ai.timing.first_token.toFixed(1)} с`;
      }
      const mem = local.memory || {};
      if (mem.mode) {
        const now = mem.llm_mb ? ` Сейчас: ассистент ${mem.agent_mb} МБ + нейросеть ${mem.llm_mb} МБ.` : mem.agent_mb ? ` Сейчас ассистент занимает ${mem.agent_mb} МБ.` : '';
        $('memory-info').textContent = `${mem.mode_title}. Нейросеть ≈ ${(mem.estimate_mb / 1024).toFixed(1)} ГБ, в компьютере ${mem.total_ram_gb} ГБ.${now}`;
      }
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

  // ---------- голос ассистента: карточки Джарвис / Пятница / свои ----------
  function paintVoiceCards() {
    const current = $('voice-preset').value;
    document.querySelectorAll('.voice-card').forEach(c => {
      c.classList.toggle('selected', c.dataset.voice === current);
      c.setAttribute('aria-checked', c.dataset.voice === current);
    });
  }
  async function loadVoices() {
    try {
      const data = await Agent.api('ai/voices');
      const select = $('voice-preset'), box = $('voice-cards');
      const saved = Agent.settings.voice_preset;
      select.replaceChildren(...data.assistant.map(v => new Option(v.title, v.id)));
      if (saved && ![...select.options].some(o => o.value === saved)) select.add(new Option(saved, saved));
      select.value = saved || 'jarvis';
      box.replaceChildren(...data.assistant.map(v => {
        const card = document.createElement('button');
        card.type = 'button'; card.className = 'voice-card'; card.dataset.voice = v.id; card.setAttribute('role', 'radio');
        const initial = v.id === 'jarvis' ? 'J' : v.id === 'friday' ? 'F' : '★';
        card.innerHTML = '<span class="voice-avatar"></span><span class="voice-meta"><b></b><small></small></span><span class="voice-wave"><i></i><i></i><i></i><i></i></span>';
        card.querySelector('.voice-avatar').textContent = initial;
        card.querySelector('b').textContent = v.title;
        card.querySelector('small').textContent = v.note;
        card.onclick = () => {
          select.value = v.id;
          select.dispatchEvent(new Event('change'));
          paintVoiceCards();
        };
        return card;
      }));
      paintVoiceCards();
    } catch (e) { /* */ }
  }
  $('voice-folder').onclick = async () => {
    try {
      const r = await Agent.post('voices/open-folder');
      $('voice-folder-hint').textContent = r.opened ? 'Папка открыта. Положите туда .onnx и .onnx.json и нажмите «Проверить голос».' : 'Папка голосов: ' + r.path;
      setTimeout(loadVoices, 1500);
    } catch (e) { Agent.toast(e.message); }
  };
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
      $('siri-url').textContent = `http://${c.ip}:${c.port}/api/siri`;
      fetch('/api/connection/qr', { headers: { 'X-Agent-Token': Agent.token, 'X-Device-ID': Agent.device } })
        .then(r => r.ok ? r.blob() : null).then(b => { if (b) $('pair-qr').src = URL.createObjectURL(b); });
      $('connection-token').value = c.token;
      $('storage').textContent = 'Данные хранятся на ПК: ' + c.storage;
    } catch (e) { /* */ }
  }
  $('show-token').onclick = () => { const t = $('connection-token'); t.type = t.type === 'password' ? 'text' : 'password'; $('show-token').textContent = t.type === 'password' ? 'Показать' : 'Скрыть'; };
  $('export').onclick = async () => {
    try {
      const data = await Agent.api('export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a'); a.href = url; a.download = 'LocalAIAgent-data.json'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) { Agent.toast(e.message); }
  };
  $('clear-history').onclick = async () => { if (confirm('Удалить историю диалога?')) { await Agent.post('history/clear'); Agent.toast('История очищена'); } };

  // ---------- аккаунт и подписка ----------
  let account = { premium: true }, paymentTimer = null, authMode = 'login';
  const authBox = $('auth-box');
  function message(text, kind) {
    const box = $('account-message');
    box.textContent = text || '';
    box.className = 'auth-message ' + (kind || '');
  }
  function setMode(mode) {
    authMode = mode;
    authBox.dataset.mode = mode;
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.toggle('active', t.dataset.mode === mode));
    $('account-submit').firstElementChild.textContent = mode === 'login' ? 'Войти' : 'Создать аккаунт';
    $('account-password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
    message('');
  }
  document.querySelectorAll('.auth-tab').forEach(t => t.onclick = () => setMode(t.dataset.mode));
  document.querySelectorAll('[data-eye]').forEach(b => b.onclick = () => {
    const input = $(b.dataset.eye);
    input.type = input.type === 'password' ? 'text' : 'password';
    b.classList.toggle('on', input.type === 'text');
  });
  function paintAccount(a) {
    account = a;
    document.body.classList.toggle('locked', !a.premium);
    const date = a.expires ? new Date(a.expires).toLocaleDateString('ru-RU') : '';
    authBox.hidden = a.logged_in;
    $('profile-box').hidden = !a.logged_in;
    $('promo-box').hidden = !a.logged_in || a.plan === 'lifetime';
    $('plans-box').hidden = a.plan === 'lifetime';
    $('plans-hint').hidden = a.plan === 'lifetime';
    if (a.logged_in) {
      $('account-title').textContent = a.email;
      $('account-avatar').textContent = (a.email || '?')[0].toUpperCase();
      $('account-plan').textContent = a.owner ? 'Владелец — все функции открыты'
        : a.plan === 'lifetime' ? 'Подписка навсегда — спасибо!'
        : a.plan === 'monthly' ? `Подписка активна до ${date}` : 'Бесплатный тариф: команды и ответы без ограничений';
      const badge = $('account-badge');
      badge.textContent = a.owner ? 'Владелец' : a.plan === 'lifetime' ? 'Навсегда' : a.plan === 'monthly' ? 'Premium' : 'Бесплатно';
      badge.className = 'plan-badge ' + (a.premium ? 'premium' : '');
      $('account-check').hidden = a.plan === 'lifetime';
    }
    const box = $('server-box');
    box.classList.toggle('connected', !!a.configured);
    box.hidden = a.logged_in && a.configured;
    $('server-state').textContent = a.configured ? 'Подключён: ' + a.server_url : 'Сервер ещё не подключён — вставьте адрес проекта Amvera.';
    if (a.configured && document.activeElement !== $('server-url')) $('server-url').value = a.server_url || '';
    $('server-save').textContent = a.configured ? 'Изменить' : 'Подключить';
  }
  async function loadAccount() {
    try { paintAccount((await Agent.api('account')).account); } catch (e) { /* */ }
  }
  async function accountAction(path, body, button) {
    if (button) button.classList.add('loading'), button.disabled = true;
    try {
      const data = await Agent.post(path, body);
      paintAccount(data.account);
      await Agent.loadSettings(); fill(Agent.settings);
      return data.account;
    } catch (e) { message(e.message, 'bad'); Agent.toast(e.message, 4000); return null; }
    finally { if (button) button.classList.remove('loading'), button.disabled = false; }
  }
  $('auth-form').addEventListener('submit', async e => {
    e.preventDefault();
    const email = $('account-email').value.trim(), password = $('account-password').value;
    document.querySelectorAll('.field-icon').forEach(f => f.classList.remove('invalid'));
    const invalid = id => { $(id).closest('.field-icon').classList.add('invalid'); $(id).focus(); };
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) { message('Введите email, например name@mail.ru', 'bad'); return invalid('account-email'); }
    if (password.length < 8) { message('Пароль — не короче 8 символов', 'bad'); return invalid('account-password'); }
    if (authMode === 'register' && password !== $('account-password2').value) { message('Пароли не совпадают', 'bad'); return invalid('account-password2'); }
    message('');
    const a = await accountAction(authMode === 'login' ? 'account/login' : 'account/register', { email, password }, $('account-submit'));
    if (a) {
      $('account-password').value = $('account-password2').value = '';
      Agent.toast(a.owner ? 'С возвращением! Все функции открыты.' : authMode === 'login' ? 'Вы вошли в аккаунт' : 'Аккаунт создан', 4000);
    }
  });
  $('account-logout').onclick = () => accountAction('account/logout').then(() => setMode('login'));
  $('account-check').onclick = () => accountAction('account/check', {}, $('account-check'));
  $('promo-apply').onclick = async () => {
    const code = $('promo-code').value.trim();
    if (!code) { $('promo-code').focus(); return; }
    const a = await accountAction('account/promo', { code }, $('promo-apply'));
    if (a && a.premium) { $('promo-code').value = ''; Agent.toast('Промокод активирован: подписка навсегда!', 6000); }
  };
  $('server-save').onclick = async () => {
    const url = $('server-url').value.trim();
    if (!url) { $('server-url').focus(); return; }
    const a = await accountAction('account/server', { url }, $('server-save'));
    if (a) { message('Сервер подключён. Теперь войдите или зарегистрируйтесь.', 'ok'); Agent.toast('Сервер аккаунтов подключён', 3000); }
  };
  $('server-url').addEventListener('keydown', e => { if (e.key === 'Enter') $('server-save').click(); });
  $('promo-code').addEventListener('keydown', e => { if (e.key === 'Enter') $('promo-apply').click(); });

  async function buy(plan) {
    if (!account.logged_in) { show('account'); setMode('register'); message('Сначала войдите или зарегистрируйтесь — подписка привязывается к аккаунту.', 'bad'); $('account-email').focus(); return; }
    try {
      const data = await Agent.post('account/checkout', { plan });
      if (!data.opened) window.open(data.url, '_blank');
      Agent.toast('Откроется страница оплаты ЮKassa. После оплаты подписка включится автоматически.', 6000);
      show('account');
      clearInterval(paymentTimer);
      let tries = 0;
      paymentTimer = setInterval(async () => {
        const a = ++tries > 120 ? null : await Agent.post('account/check').then(d => d.account).catch(() => null);
        if (a) paintAccount(a);
        if (tries > 120 || (a && a.premium && !a.pending_payment)) {
          clearInterval(paymentTimer);
          if (a && a.premium) { Agent.toast('Оплата получена. Спасибо! Все разделы открыты.', 6000); await Agent.loadSettings(); fill(Agent.settings); }
        }
      }, 5000);
    } catch (e) { Agent.toast(e.message, 5000); }
  }
  document.querySelectorAll('[data-buy]').forEach(b => b.onclick = () => buy(b.dataset.buy));

  // ---------- расширение для браузера ----------
  async function refreshExtension() {
    try {
      const st = await Agent.api('ext/status');
      $('ext-pill').className = 'pill ' + (st.connected ? 'ok' : '');
      $('ext-status').textContent = st.connected ? 'Подключено: ' + (st.browser || 'браузер') : 'Не подключено';
      $('ext-steps').hidden = !!st.connected;
    } catch (e) { /* */ }
  }
  $('ext-folder').onclick = async () => {
    try {
      const r = await Agent.post('ext/open-folder');
      if (!r.opened) Agent.toast('Папка расширения: ' + r.path, 8000);
    } catch (e) { Agent.toast(e.message); }
  };
  refreshExtension();
  setInterval(refreshExtension, 5000);

  async function refreshIntegrations() {
    try {
      const st = await Agent.api('integrations');
      $('int-status').textContent = st.items.length ? 'Подключено: ' + st.items.length : 'Пока нет';
      $('int-pill').className = 'pill ' + (st.items.length ? 'ok' : '');
      $('int-list').replaceChildren(...st.items.map(i => {
        const li = document.createElement('li');
        li.innerHTML = '<b></b> — <span></span>';
        li.querySelector('b').textContent = i.name;
        li.querySelector('span').textContent = `${i.commands} команд${i.context ? ', данные для вопросов' : ''} (${i.file})`;
        return li;
      }), ...st.errors.map(e => { const li = document.createElement('li'); li.textContent = 'Ошибка: ' + e; li.style.color = 'var(--bad)'; return li; }));
    } catch (e) { /* */ }
  }
  $('int-folder').onclick = async () => {
    try {
      const r = await Agent.post('integrations/open-folder');
      if (!r.opened) Agent.toast('Папка интеграций: ' + r.path, 8000);
      setTimeout(refreshIntegrations, 2000);
    } catch (e) { Agent.toast(e.message); }
  };
  refreshIntegrations();

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
    } else if (e.type === 'account') {
      paintAccount(e.account);
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
      await loadAccount();
      Agent.connectEvents(onEvent);
      const wanted = new URLSearchParams(location.search).get('section') || Agent.store.get('agent_settings_page') || 'general';
      show(document.getElementById('page-' + wanted) ? wanted : 'general');
    } catch (e) { state(e.message, 'bad'); }
  })();
})();
