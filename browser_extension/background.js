/* «Андрей» в браузере пользователя: получает команды от ассистента на этом ПК и выполняет их.
   Ассистент слушает на http://127.0.0.1:5000 (порт можно сменить в окне расширения).
   Связь — долгий опрос /api/ext/next; ответ — /api/ext/result. Код подключения — из настроек ассистента. */
'use strict';

const state = { running: false, again: false, online: false, error: '' };

async function config() {
  const { port = 5000, token = '' } = await chrome.storage.local.get(['port', 'token']);
  return { base: `http://127.0.0.1:${port}`, token };
}

function browserName() {
  const brands = (navigator.userAgentData && navigator.userAgentData.brands) || [];
  const known = brands.map(b => b.brand).find(b => /yandex|edge|opera|brave|vivaldi|chrom/i.test(b) && !/not.a.brand|chromium/i.test(b));
  if (known) return known;
  if (/YaBrowser/.test(navigator.userAgent)) return 'Yandex Browser';
  if (/Edg\//.test(navigator.userAgent)) return 'Microsoft Edge';
  if (/OPR\//.test(navigator.userAgent)) return 'Opera';
  return 'Google Chrome';
}

async function setBadge(online) {
  state.online = online;
  await chrome.action.setBadgeText({ text: online ? '' : '!' });
  await chrome.action.setBadgeBackgroundColor({ color: '#ff6b8b' });
}

async function loop() {
  if (state.running) { state.again = true; return; } // перезапустим, когда текущий цикл завершится
  state.running = true;
  state.again = false;
  try {
    for (;;) {
      await chrome.runtime.getPlatformInfo(); // вызов API продлевает жизнь фонового воркера
      const { base, token } = await config();
      if (!token) { state.error = 'Введите код подключения'; await setBadge(false); break; }
      let data;
      try {
        const response = await fetch(`${base}/api/ext/next?wait=20&browser=${encodeURIComponent(browserName())}`,
          { headers: { 'X-Agent-Token': token } });
        if (response.status === 401) { state.error = 'Неверный код подключения'; await setBadge(false); break; }
        data = await response.json();
        state.error = ''; await setBadge(true);
      } catch (e) {
        state.error = 'Ассистент не запущен'; await setBadge(false);
        await new Promise(r => setTimeout(r, 5000));
        continue;
      }
      if (data && data.command) handle(data.command, base, token); // не ждём: следующая команда может прийти сразу
    }
  } finally {
    state.running = false;
    if (state.again) { state.again = false; setTimeout(loop, 0); } // например, код сохранили во время выхода
  }
}

async function handle(command, base, token) {
  let body;
  try {
    const result = await (ACTIONS[command.action] || (() => { throw new Error('Неизвестная команда'); }))(command.args || {});
    body = { id: command.id, ok: true, result };
  } catch (e) {
    body = { id: command.id, ok: false, error: String(e && e.message || e) };
  }
  await fetch(`${base}/api/ext/result`, { method: 'POST', headers: { 'X-Agent-Token': token, 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }).catch(() => {});
}

// ---------- вкладки ----------
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab;
}

async function focus(tab) {
  await chrome.tabs.update(tab.id, { active: true });
  const win = await chrome.windows.get(tab.windowId);
  await chrome.windows.update(tab.windowId, win.state === 'minimized' ? { focused: true, state: 'normal' } : { focused: true });
  return tab;
}

function sameSite(tabUrl, url) {
  try {
    const a = new URL(tabUrl), b = new URL(url);
    const host = h => h.replace(/^www\./, '');
    if (host(a.hostname) !== host(b.hostname)) return false;
    const path = b.pathname.replace(/\/$/, '');
    return !path || a.pathname.startsWith(path);
  } catch (e) { return false; }
}

function waitLoaded(tabId, timeout = 15000) {
  return new Promise(resolve => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listener); clearTimeout(timer); resolve(); };
    const listener = (id, info) => { if (id === tabId && info.status === 'complete') done(); };
    const timer = setTimeout(done, timeout);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function run(tabId, func, args = []) {
  const [result] = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func, args });
  return result ? result.result : undefined;
}

async function mediaTab() {
  const audible = await chrome.tabs.query({ audible: true });
  if (audible.length) return audible[0];
  const tab = await activeTab();
  if (tab && /^https?:/.test(tab.url || '')) return tab;
  const players = await chrome.tabs.query({ url: ['*://*.youtube.com/*', '*://music.yandex.ru/*', '*://open.spotify.com/*', '*://vk.com/*', '*://rutube.ru/*', '*://zvuk.com/*', '*://soundcloud.com/*'] });
  return players[0];
}

// ---------- скрипты на страницах (те же, что в браузере агента) ----------
function mediaScript(action) {
  let ok = 0;
  for (const m of document.querySelectorAll('video, audio')) {
    try { if (action === 'pause') { m.pause(); } else { m.play(); } ok++; } catch (e) { /* */ }
  }
  if (!ok) {
    const words = action === 'pause' ? ['pause', 'пауза', 'приостанов'] : ['play', 'воспроизв', 'играть'];
    for (const b of document.querySelectorAll('button, [role=button]')) {
      const label = ((b.getAttribute('aria-label') || '') + ' ' + (b.getAttribute('title') || '')).toLowerCase();
      if (words.some(w => label.includes(w)) && b.offsetParent !== null) { b.click(); ok++; break; }
    }
  }
  return ok > 0;
}

function pickScript(skip) {
  const seen = new Set(), links = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    const m = href.match(/youtube\.com\/(?:watch\?v=|shorts\/)([\w-]{11})/) || href.match(/rutube\.ru\/video\/(\w+)/);
    if (!m || m[1] === skip || seen.has(m[1])) continue;
    const box = a.getBoundingClientRect();
    if (!box.width || !box.height || a.closest('#masthead, ytd-masthead, [hidden]')) continue;
    seen.add(m[1]);
    links.push(href);
  }
  return links;
}

function playFirstScript() {
  const bar = 'header, nav, footer, [class*="PlayerBar"], [class*="player-bar"], [class*="PlayerControls"], [data-testid="now-playing-bar"], ytmusic-player-bar, [class*="audio_page_player"]';
  const words = ['воспроизв', 'play', 'слушать', 'играть'];
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < innerHeight; };
  const main = document.querySelector('main, [role=main], #content, #main') || document;
  for (const b of [...main.querySelectorAll('button, [role=button], a[aria-label]'), ...document.querySelectorAll('button, [role=button]')]) {
    const label = ((b.getAttribute('aria-label') || '') + ' ' + (b.getAttribute('title') || '') + ' ' + (b.dataset.testid || '')).toLowerCase();
    if (!words.some(w => label.includes(w)) || label.includes('pause') || label.includes('пауз')) continue;
    if (b.closest(bar) || !visible(b)) continue;
    b.click();
    return 'button';
  }
  const link = [...document.querySelectorAll('a[href*="/track/"], a[href*="/watch?v="], a[href*="/song/"]')].find(visible);
  if (link) { link.click(); return 'link'; }
  return '';
}

// ---------- команды ----------
const ACTIONS = {
  async open({ url }) {
    const tabs = await chrome.tabs.query({});
    const existing = tabs.find(t => sameSite(t.url || '', url));
    if (existing) { await focus(existing); return { focused: true }; }
    const tab = await activeTab();
    if (tab && /^(chrome|edge|browser|about):\/\/(newtab|new-tab-page)|^about:blank/.test(tab.url || tab.pendingUrl || '')) {
      await chrome.tabs.update(tab.id, { url });
      await focus(tab);
    } else {
      const created = await chrome.tabs.create({ url, active: true });
      await focus(created);
    }
    return { focused: false };
  },
  async navigate({ url }) {
    const tab = await activeTab();
    const target = tab && /^https?:/.test(tab.url || '') ? await chrome.tabs.update(tab.id, { url })
      : await chrome.tabs.create({ url, active: true });
    await focus(target);
    await waitLoaded(target.id);
    return true;
  },
  async tab({ index }) {
    const win = await chrome.windows.getLastFocused();
    const tabs = await chrome.tabs.query({ windowId: win.id });
    const active = tabs.find(t => t.active) || tabs[0];
    const target = index === 'last' ? tabs[tabs.length - 1]
      : index === 'next' ? tabs[(active.index + 1) % tabs.length]
      : index === 'prev' ? tabs[(active.index - 1 + tabs.length) % tabs.length]
      : tabs[index - 1];
    if (!target) return null;
    await focus(target);
    return { index: target.index + 1 };
  },
  async minimize({ url }) {
    const tabs = (await chrome.tabs.query({})).filter(t => sameSite(t.url || '', url));
    const windows = [...new Set(tabs.map(t => t.windowId))];
    for (const id of windows) await chrome.windows.update(id, { state: 'minimized' });
    return windows.length;
  },
  async block({ domains }) { await blockedReady; blocked = domains || []; await chrome.storage.local.set({ blocked }); await sweep(); return blocked.length; },
  async url() { const tab = await activeTab(); return tab ? tab.url : ''; },
  async tabs() { return (await chrome.tabs.query({})).map(t => ({ title: t.title, url: t.url })); },
  async close_tab() { const tab = await activeTab(); if (tab) await chrome.tabs.remove(tab.id); return true; },
  async close_site({ url }) {
    const tabs = (await chrome.tabs.query({})).filter(t => sameSite(t.url || '', url));
    if (tabs.length) await chrome.tabs.remove(tabs.map(t => t.id));
    return tabs.length;
  },
  async media({ action }) {
    const tab = await mediaTab();
    return tab ? !!(await run(tab.id, mediaScript, [action])) : false;
  },
  async youtube({ action, arg }) {
    const tab = await activeTab();
    if (!tab) return false;
    if (action === 'pick') {
      const current = (tab.url || '').match(/[?&]v=([\w-]{11})/);
      let links = [];
      for (let i = 0; i < 20 && !links.length; i++) {
        links = await run(tab.id, pickScript, [current ? current[1] : '']) || [];
        if (!links.length) await new Promise(r => setTimeout(r, 500));
      }
      const index = arg > 0 ? arg - 1 : links.length + arg;
      if (!links[index]) return false;
      await chrome.tabs.update(tab.id, { url: links[index] });
      await waitLoaded(tab.id);
      await new Promise(r => setTimeout(r, 1200));
      await run(tab.id, mediaScript, ['play']);
      return true;
    }
    if (action === 'back') { await chrome.tabs.goBack(tab.id); return true; }
    if (action === 'next') return run(tab.id, () => { const b = document.querySelector('.ytp-next-button'); if (b) b.click(); return !!b; });
    if (action === 'fullscreen') return run(tab.id, () => { const b = document.querySelector('.ytp-fullscreen-button'); if (b) b.click(); return !!b; });
    if (action === 'seek') return run(tab.id, s => { const v = document.querySelector('video'); if (v) v.currentTime = Math.max(0, v.currentTime + s); return !!v; }, [arg]);
    return false;
  },
  async music({ url }) {
    const tabs = await chrome.tabs.query({});
    const host = new URL(url).hostname;
    let tab = tabs.find(t => (t.url || '').includes(host));
    if (tab) { tab = await chrome.tabs.update(tab.id, { url }); } else { tab = await chrome.tabs.create({ url, active: true }); }
    await focus(tab);
    await waitLoaded(tab.id);
    for (let i = 0; i < 12; i++) {
      await new Promise(r => setTimeout(r, 500));
      const clicked = await run(tab.id, playFirstScript);
      if (clicked === 'link') { await new Promise(r => setTimeout(r, 1500)); await run(tab.id, mediaScript, ['play']); return true; }
      if (clicked) return true;
    }
    return false;
  },
};

// ---------- блокировка сайтов (сценарии «Работа», «Учёба» и «заблокируй ютуб на час») ----------
let blocked = [];
// Список переживает перезапуск фонового воркера; команда «block» ждёт загрузки, чтобы её не затёрло старое значение.
const blockedReady = chrome.storage.local.get('blocked').then(v => { blocked = v.blocked || []; sweep(); });

function isBlocked(url) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '');
    return blocked.some(d => host === d || host.endsWith('.' + d));
  } catch (e) { return false; }
}

async function stop(tab) {
  const page = chrome.runtime.getURL('blocked.html') + '#' + encodeURIComponent(new URL(tab.url).hostname);
  await chrome.tabs.update(tab.id, { url: page }).catch(() => {});
}

async function sweep() {
  if (!blocked.length) return;
  for (const tab of await chrome.tabs.query({})) if (isBlocked(tab.url || '')) await stop(tab);
}

chrome.tabs.onUpdated.addListener((id, info, tab) => {
  if (info.url && isBlocked(info.url)) stop({ id, url: info.url });
});

// ---------- запуск ----------
chrome.runtime.onStartup.addListener(loop);
chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create('keepalive', { periodInMinutes: 0.5 }); loop(); });
chrome.alarms.onAlarm.addListener(() => loop());
chrome.storage.onChanged.addListener(() => loop());
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message === 'status') { reply({ online: state.online, error: state.error }); return false; }
  return false;
});
loop();
