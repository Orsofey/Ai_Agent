/* Shared client core: pairing token, API, themes, live events, cross-window sync. */
(() => {
  'use strict';
  const Agent = window.Agent = {};
  const store = {
    get(key, fallback = null) { try { return localStorage.getItem(key) ?? fallback; } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } },
  };
  Agent.store = store;

  const fragment = new URLSearchParams(location.hash.slice(1));
  const iOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = window.navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;
  Agent.iOS = iOS;
  if (fragment.has('device') && /^[\w-]{1,80}$/.test(fragment.get('device'))) store.set('agent_device', fragment.get('device'));
  if (fragment.has('token')) {
    store.set('agent_token', fragment.get('token'));
    // На iPhone ссылка с кодом остаётся в адресе, чтобы «На экран Домой» открывал уже подключённое приложение.
    if (!(iOS && !standalone)) history.replaceState(null, '', location.pathname);
    else document.querySelectorAll('link[rel=manifest]').forEach(link => link.remove());
  }
  Agent.token = store.get('agent_token', '');
  Agent.device = store.get('agent_device') || 'desktop';
  store.set('agent_device', Agent.device);
  Agent.settings = {};
  Agent.secrets = {};

  Agent.setToken = token => { Agent.token = token; store.set('agent_token', token); };

  Agent.api = async (path, options = {}) => {
    const headers = { 'X-Agent-Token': Agent.token, 'X-Device-ID': Agent.device, ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const response = await fetch('/api/' + path, { ...options, headers });
    let data = {};
    try { data = await response.json(); } catch (e) { /* not json */ }
    if (!response.ok || data.success === false) {
      const error = new Error(data.message || data.error || ('Ошибка HTTP ' + response.status));
      error.status = response.status;
      if (response.status === 401) document.dispatchEvent(new CustomEvent('agent-unpaired'));
      throw error;
    }
    return data;
  };

  Agent.post = (path, body = {}) => Agent.api(path, { method: 'POST', body: JSON.stringify(body) });

  // ---- темы ----
  Agent.THEMES = [
    { id: 'aurora', name: 'Аврора', note: 'Северное сияние над ночным небом' },
    { id: 'cyberpunk', name: 'Киберпанк', note: 'Неон, синтвейв-солнце и бегущая сетка' },
    { id: 'sakura', name: 'Сакура', note: 'Весенний сад и падающие лепестки' },
    { id: 'ocean', name: 'Бездна', note: 'Светящийся океан, пузыри и каустика' },
    { id: 'luxe', name: 'Люкс', note: 'Ар-деко: чёрный мрамор и золото' },
    { id: 'dark', name: 'Тёмная', note: 'Классическая спокойная тема' },
    { id: 'light', name: 'Светлая', note: 'Классическая светлая тема' },
  ];

  Agent.applyTheme = (theme, animations = true) => {
    const root = document.documentElement;
    const changed = root.dataset.theme !== theme;
    root.dataset.theme = theme;
    root.dataset.animations = animations ? 'on' : 'off';
    store.set('agent_theme', theme);
    store.set('agent_animations', animations ? 'on' : 'off');
    if (changed || !document.querySelector('.scene .particle')) {
      document.querySelectorAll('body > .scene').forEach(scene => window.AgentMotion && AgentMotion.decorate(scene, theme));
    }
  };

  // ---- настройки ----
  Agent.loadSettings = async () => {
    const data = await Agent.api('settings');
    Agent.settings = data.settings;
    Agent.secrets = data.secrets || {};
    Agent.applyTheme(Agent.settings.theme, Agent.settings.animations);
    return Agent.settings;
  };

  const channel = 'BroadcastChannel' in window ? new BroadcastChannel('local-ai-agent') : null;
  Agent.saveSettings = async partial => {
    const data = await Agent.post('settings', partial);
    Agent.settings = data.settings;
    Agent.secrets = data.secrets || Agent.secrets;
    Agent.applyTheme(Agent.settings.theme, Agent.settings.animations);
    if (channel) channel.postMessage({ type: 'settings', settings: Agent.settings });
    return Agent.settings;
  };
  Agent.onSettings = handler => {
    if (channel) channel.addEventListener('message', e => e.data && e.data.type === 'settings' && handler(e.data.settings));
    window.addEventListener('storage', e => { if (e.key === 'agent_theme' && e.newValue) Agent.applyTheme(e.newValue, store.get('agent_animations') !== 'off'); });
  };

  // ---- живые события (SSE) ----
  Agent.connectEvents = handler => {
    let source = null, retry = 1000;
    const open = () => {
      if (!Agent.token) return setTimeout(open, 2000);
      source = new EventSource('/api/events?token=' + encodeURIComponent(Agent.token));
      source.onmessage = e => { retry = 1000; try { handler(JSON.parse(e.data)); } catch (err) { console.error(err); } };
      source.onerror = () => { source.close(); setTimeout(open, retry); retry = Math.min(retry * 2, 15000); };
    };
    open();
    return () => source && source.close();
  };

  // ---- мелочи ----
  Agent.toast = (text, ms = 2600) => {
    let el = document.querySelector('.toast');
    if (!el) { el = document.createElement('div'); el.className = 'toast'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
    el.textContent = text;
    el.classList.add('show');
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.remove('show'), ms);
  };
  Agent.uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + '_' + Math.random().toString(36).slice(2));

  Agent.openSettings = async (section = '') => {
    try {
      const result = await Agent.post('ui/open-settings');
      if (result.opened) return;
    } catch (e) { /* браузер — откроем вкладкой */ }
    window.open('/settings' + (section ? '?section=' + section : '') + '#token=' + encodeURIComponent(Agent.token),
      'agent-settings', 'width=1020,height=780');
  };

  // Старые версии кешировали скрипты сервис-воркером.
  if ('serviceWorker' in navigator) navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => r.unregister())).catch(() => {});
})();
