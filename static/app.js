/* Main window: live voice orb, streaming dialog, quick commands. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const panel = $('voice-panel');
  const STATES = {
    off: ['Прослушивание выключено', 'Включите «Слушать», чтобы обращаться по имени.'],
    idle: ['Скажите «{name}»', 'и команду — я выполню её в любом открытом приложении.'],
    hearing: ['Слышу вас…', 'Говорите, я запишу фразу целиком.'],
    listening: ['Слушаю команду', 'Говорите — имя можно не называть.'],
    transcribing: ['Распознаю…', 'Секунду.'],
    thinking: ['Выполняю…', ''],
    speaking: ['Отвечаю', 'Скажите «{name}», чтобы перебить.'],
    error: ['Микрофон недоступен', ''],
  };
  let voiceState = 'off', nativeVoice = false, busy = false, voiceBubble = null, localRequest = false, speaking = false;
  let controller = null;

  // ---------- сообщения ----------
  function scrollDown() { const m = $('messages'); m.scrollTop = m.scrollHeight; }
  function emptyState() {
    const m = $('messages');
    if (m.children.length) return;
    const name = Agent.settings.wake_word || 'Андрей';
    m.innerHTML = '';
    const box = document.createElement('div');
    box.className = 'empty-chat';
    const title = document.createElement('b');
    title.textContent = 'Привет! Я ' + name + '.';
    box.append(title, document.createTextNode('Спросите что угодно: курс валют, погоду, питание, финансы. ' +
      'Или дайте команду: «' + name + ', напиши текст привет, Милана» — в Word, Telegram или любом другом окне.'));
    m.appendChild(box);
  }
  function bubble(text, role, meta) {
    const empty = $('messages').querySelector('.empty-chat');
    if (empty) empty.remove();
    const el = document.createElement('div');
    el.className = 'msg ' + role;
    el.textContent = text;
    if (meta) { const s = document.createElement('span'); s.className = 'meta'; s.textContent = meta; el.appendChild(s); }
    $('messages').appendChild(el);
    scrollDown();
    return el;
  }
  function setBubbleText(el, text) {
    const meta = el.querySelector('.meta');
    el.textContent = text;
    if (meta) el.appendChild(meta);
  }

  async function loadHistory() {
    const data = await Agent.api('history');
    $('messages').replaceChildren();
    data.history.forEach(m => bubble(m.text, m.role));
    emptyState();
  }

  // ---------- отправка с потоковым ответом ----------
  async function send(text) {
    text = String(text == null ? $('chat-input').value : text).trim();
    if (!text || busy) return;
    busy = localRequest = true;
    $('send').disabled = true;
    controller = new AbortController();
    showPause();
    $('chat-input').value = '';
    autosize();
    bubble(text, 'user');
    const answer = bubble('', 'agent');
    answer.classList.add('streaming');
    let full = '', spoken = false;
    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Agent-Token': Agent.token, 'X-Device-ID': Agent.device },
        body: JSON.stringify({ message: text, id: Agent.uid() }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        if (response.status === 401) $('pair').hidden = false;
        throw new Error(data.message || 'Ошибка ' + response.status);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf('\n\n')) >= 0) {
          const line = buffer.slice(0, index).trim();
          buffer = buffer.slice(index + 2);
          if (!line.startsWith('data:')) continue;
          const item = JSON.parse(line.slice(5));
          if (item.type === 'delta') { full += item.text; setBubbleText(answer, full); scrollDown(); }
          else if (item.type === 'done') { full = item.response; spoken = item.spoken; setBubbleText(answer, full); }
          else if (item.type === 'error') throw new Error(item.message);
        }
      }
      if (!spoken) AgentVoice.speak(full);
    } catch (e) {
      setBubbleText(answer, e.name === 'AbortError' ? (full ? full + ' …' : 'Остановлено.') : e.message);
    } finally {
      answer.classList.remove('streaming');
      busy = localRequest = false;
      controller = null;
      $('send').disabled = false;
      showPause();
      scrollDown();
    }
  }
  window.sendMessage = send;

  // ---------- пауза ----------
  function showPause() {
    const active = busy || speaking || voiceState === 'thinking';
    $('stop-speaking').hidden = !active;
    $('pause').hidden = !active;
    $('send').hidden = active;
  }
  function pause() {
    Agent.post('cancel').catch(() => {});
    AgentVoice.stop();
    if (controller) controller.abort();
    if (voiceBubble) { setBubbleText(voiceBubble, voiceBubble.textContent ? voiceBubble.textContent + ' …' : 'Остановлено.'); voiceBubble.classList.remove('streaming'); voiceBubble = null; }
    speaking = false;
    paintVoice(voiceState === 'thinking' ? 'idle' : voiceState);
  }

  // ---------- голосовая сфера ----------
  function paintVoice(state, extra = {}) {
    voiceState = state;
    panel.dataset.state = speaking && state === 'idle' ? 'speaking' : state;
    const name = Agent.settings.wake_word || 'Андрей';
    const [title, hint] = STATES[panel.dataset.state] || STATES.idle;
    $('voice-title').textContent = title.replace('{name}', name);
    $('voice-hint').textContent = (extra.message || hint).replace('{name}', name);
    $('listen-toggle').textContent = 'Слушать: ' + (Agent.settings.voice_enabled ? 'вкл' : 'выкл');
    showPause();
  }

  function onEvent(e) {
    switch (e.type) {
      case 'state':
        if (e.state === 'thinking' && e.command) $('heard').innerHTML = '';
        paintVoice(e.state, e);
        break;
      case 'level':
        document.documentElement.style.setProperty('--level', e.value);
        break;
      case 'transcript': {
        const heard = $('heard');
        heard.textContent = '';
        const em = document.createElement('em'); em.textContent = '«' + e.text + '»';
        heard.append(em, document.createTextNode(e.elapsed != null ? '  ' + Math.round(e.elapsed * 1000) + ' мс' : ''));
        break;
      }
      case 'speaking':
        speaking = e.speaking;
        paintVoice(voiceState);
        break;
      case 'message':
        if (e.source === 'voice') {
          if (e.role === 'user') { bubble(e.text, 'user', '🎙 голосом'); voiceBubble = bubble('', 'agent'); voiceBubble.classList.add('streaming'); }
          else if (voiceBubble) { setBubbleText(voiceBubble, e.text); voiceBubble.classList.remove('streaming'); voiceBubble = null; }
          else bubble(e.text, 'agent');
        } else if (!localRequest && e.owner && e.owner.startsWith('device:') && e.owner !== 'device:desktop') {
          bubble(e.text, e.role, '📱 с телефона');
        }
        break;
      case 'delta':
        if (voiceBubble && !localRequest) { setBubbleText(voiceBubble, voiceBubble.textContent + e.text); scrollDown(); }
        break;
      case 'download': {
        const names = { vad: 'детектор речи', parakeet: 'распознавание речи', gigaam: 'распознавание речи', piper: 'голоса',
          'llama:cpu': 'движок нейросети', 'llama:vulkan': 'движок нейросети', 'llm:qwen3-4b': 'нейросеть', 'llm:qwen2.5-7b': 'нейросеть', 'llm:qwen3-1.7b': 'нейросеть' };
        const pill = $('download-pill');
        if (e.item === 'all') { pill.hidden = true; pollStatus(); break; }
        pill.hidden = false;
        const what = names[e.item] || e.item;
        if (e.stage === 'progress') $('download-status').textContent = `Установка: ${what} ${e.detail.percent}%`;
        else if (e.stage === 'start') $('download-status').textContent = `Установка: ${what}…`;
        else if (e.stage === 'error') Agent.toast(`Не удалось скачать ${what}: ${e.detail}`, 8000);
        break;
      }
      case 'voice_error':
        Agent.toast(e.message);
        break;
      case 'settings':
        Agent.settings = e.settings;
        Agent.applyTheme(e.settings.theme, e.settings.animations);
        reflect();
        break;
    }
  }

  function reflect() {
    const s = Agent.settings;
    $('agent-name').textContent = s.wake_word || 'Андрей';
    $('hotkey-label').textContent = (s.hotkey || 'ctrl+alt+space').split('+').map(k => k.length > 1 ? k[0].toUpperCase() + k.slice(1) : k.toUpperCase()).join('+');
    paintVoice(voiceState);
  }

  async function pollStatus() {
    try {
      const data = await Agent.api('voice/status');
      nativeVoice = data.native;
      const sp = data.speech;
      $('engine').textContent = sp.ready ? sp.engine + ' · готов' : (sp.loading ? sp.engine + ' · загрузка…' : (sp.error ? 'Нет модели речи' : sp.engine));
      $('engine-pill').className = 'pill ' + (sp.ready ? 'ok' : sp.loading ? 'warn' : 'bad');
      $('engine-pill').title = sp.error || ('Распознавание: ' + sp.engine + (sp.last_elapsed ? ', последнее за ' + Math.round(sp.last_elapsed * 1000) + ' мс' : ''));
      if (nativeVoice) paintVoice(data.voice.state, { message: data.voice.error });
      else paintVoice(Agent.settings.voice_enabled ? 'idle' : 'off');
      const ai = await Agent.api('ai/status');
      const local = ai.local || {};
      let text = 'ИИ: внешний сервер', kind = 'ok';
      if (ai.provider === 'off') { text = 'ИИ выключен'; kind = ''; }
      else if (ai.provider === 'local') {
        if (local.ready) text = 'ИИ на этом ПК · готов';
        else if (local.starting) { text = 'ИИ загружается…'; kind = 'warn'; }
        else if (!local.model_installed || !local.runtime_installed) { text = 'ИИ не установлен'; kind = 'warn'; }
        else { text = 'ИИ на этом ПК'; kind = 'warn'; }
      }
      $('ai-status').textContent = text;
      $('ai-pill').className = 'pill ' + kind;
      $('ai-pill').title = local.error || 'Ответы на вопросы: бесплатно, без ключей';
    } catch (e) { $('engine').textContent = e.message; $('engine-pill').className = 'pill bad'; }
  }

  async function listenOnce() {
    AgentVoice.stop();
    if (nativeVoice) {
      try { await Agent.post('voice/listen'); } catch (e) { Agent.toast(e.message); }
      return;
    }
    try {
      await BrowserRecorder.start(text => { if (text) send(text); else Agent.toast('Речь не распознана'); },
        st => { $('mic').classList.toggle('recording', st === 'recording'); paintVoice(st === 'recording' ? 'listening' : st === 'transcribing' ? 'transcribing' : 'idle'); });
    } catch (e) { Agent.toast(e.message); }
  }

  // ---------- интерфейс ----------
  function autosize() { const t = $('chat-input'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 160) + 'px'; }
  $('chat-input').addEventListener('input', autosize);
  $('chat-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  $('send').onclick = () => send();
  $('mic').onclick = listenOnce;
  $('orb').onclick = listenOnce;
  $('open-settings').onclick = () => Agent.openSettings();
  $('stop-speaking').onclick = pause;
  $('pause').onclick = pause;
  $('listen-toggle').onclick = async () => {
    try { await Agent.saveSettings({ voice_enabled: !Agent.settings.voice_enabled }); reflect(); pollStatus(); }
    catch (e) { Agent.toast(e.message); }
  };
  $('clear').onclick = async () => {
    if (!confirm('Очистить историю диалога?')) return;
    await Agent.post('history/clear');
    await loadHistory();
  };
  document.querySelectorAll('[data-command]').forEach(b => b.onclick = () => send(b.dataset.command));
  $('pair-btn').onclick = () => { Agent.setToken($('token').value.trim()); init(); };
  document.addEventListener('agent-unpaired', () => { $('pair').hidden = false; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') pause(); });

  Agent.onSettings(settings => { Agent.settings = settings; Agent.applyTheme(settings.theme, settings.animations); reflect(); pollStatus(); });

  let eventsStarted = false;
  async function init() {
    try {
      await Agent.loadSettings();
      $('pair').hidden = true;
      reflect();
      await loadHistory();
      await pollStatus();
      if (!eventsStarted) { eventsStarted = true; Agent.connectEvents(onEvent); setInterval(pollStatus, 5000); }
      const ai = await Agent.api('ai/status').catch(() => ({}));
      if (ai.provider === 'local' && ai.local && (!ai.local.model_installed || !ai.local.runtime_installed) && !Agent.store.get('agent_llm_hint')) {
        Agent.store.set('agent_llm_hint', '1');
        Agent.toast('Чтобы я отвечал на любые вопросы, скачайте бесплатную нейросеть: Настройки → ИИ.', 6000);
      }
    } catch (e) {
      if (e.status === 401) $('pair').hidden = false; else Agent.toast(e.message);
    }
  }
  Agent.applyTheme(document.documentElement.dataset.theme, document.documentElement.dataset.animations !== 'off');
  init();
})();
