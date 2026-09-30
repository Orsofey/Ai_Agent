/* Settings 6.0: файлы и поиск, игры, умный дом, каталог голосов, модель зрения. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const hint = (id, text) => { if ($(id)) $(id).textContent = text; };
  const onPage = (page, fn) => document.querySelectorAll(`.nav-item[data-page="${page}"]`)
    .forEach(b => b.addEventListener('click', fn));
  const safe = fn => async (...args) => { try { await fn(...args); } catch (e) { Agent.toast(e.message, 5000); } };

  // ---------- файлы ----------
  async function loadIndex() {
    const { status } = await Agent.api('files/status');
    hint('fi-state', status.scanning ? `Идёт индексация… файлов: ${status.files}` :
      `Файлов: ${status.files}, с текстом: ${status.texts}` + (status.last_scan ? `, обновлён в ${status.last_scan}` : ', строится после запуска'));
  }
  onPage('files', safe(loadIndex));
  if ($('fi-reindex')) $('fi-reindex').onclick = safe(async () => { await Agent.post('files/reindex'); Agent.toast('Обновляю индекс…'); setTimeout(safe(loadIndex), 1500); });

  // ---------- игры ----------
  let games = { profiles: {} };
  function paintGames() {
    $('gm-active').checked = !!games.active;
    hint('gm-state', games.active ? `Включён, профиль «${games.profile}»` : 'Выключен');
    const select = $('gm-profile');
    const current = select.value;
    select.replaceChildren(...Object.keys(games.profiles).map(name => Object.assign(document.createElement('option'), { value: name, textContent: name })));
    select.value = current && games.profiles[current] != null ? current :
      (games.profile || (games.profiles['Общий'] != null ? 'Общий' : Object.keys(games.profiles)[0]));
    $('gm-text').value = games.profiles[select.value] || '';
  }
  async function loadGames() { games = await Agent.api('games'); paintGames(); }
  onPage('games', safe(loadGames));
  if ($('gm-profile')) {
    $('gm-profile').onchange = () => { $('gm-text').value = games.profiles[$('gm-profile').value] || ''; };
    $('gm-text').oninput = () => { games.profiles[$('gm-profile').value] = $('gm-text').value; };
    $('gm-new').onclick = () => {
      const name = (prompt('Название игры') || '').trim();
      if (!name) return;
      games.profiles[name] = 'прыжок = space\n';
      paintGames();
      $('gm-profile').value = name;
      $('gm-text').value = games.profiles[name];
    };
    $('gm-save').onclick = safe(async () => { games = await Agent.post('games', { profiles: games.profiles }); paintGames(); hint('gm-hint', 'Сохранено'); });
    $('gm-active').onchange = safe(async () => { games = await Agent.post('games', { active: $('gm-active').checked }); paintGames(); });
  }

  // ---------- умный дом ----------
  async function loadHome() {
    const data = await Agent.api('smarthome');
    const tv = data.config.tv || {}, lights = data.config.lights || {}, router = data.config.router || {};
    $('sh-tv-type').value = tv.type || '';
    $('sh-tv-ip').value = tv.ip || '';
    $('sh-tv-mac').value = tv.mac || '';
    $('sh-adb').hidden = tv.type !== 'android';
    $('sh-ya-token').value = lights.yandex_token || '';
    $('sh-ha-url').value = lights.ha_url || '';
    $('sh-ha-token').value = lights.ha_token || '';
    $('sh-hue-bridge').value = lights.hue_bridge || '';
    hint('sh-yee-hint', (lights.yeelight || []).length ? `Ламп: ${lights.yeelight.length}` : '');
    $('sh-r-type').value = router.type || '';
    $('sh-r-address').value = router.address || '';
    $('sh-r-login').value = router.login || '';
    $('sh-r-password').value = router.password || '';
    if (data.yandex_token_url) { $('sh-ya-link').hidden = false; $('sh-ya-link').href = data.yandex_token_url; }
  }
  onPage('smarthome', safe(loadHome));
  const save = (section, data) => Agent.post('smarthome/save', { section, data });
  if ($('sh-tv-save')) {
    $('sh-tv-type').onchange = () => { $('sh-adb').hidden = $('sh-tv-type').value !== 'android'; };
    $('sh-tv-find').onclick = safe(async () => {
      hint('sh-tv-hint', 'Ищу телевизоры в сети…');
      const { found } = await Agent.post('smarthome/discover', { what: 'tv' });
      const box = $('sh-tv-found');
      box.replaceChildren(...found.map(tv => {
        const b = Object.assign(document.createElement('button'), { className: 'btn ghost', textContent: `${tv.name} (${tv.ip})` });
        b.onclick = () => { $('sh-tv-ip').value = tv.ip; $('sh-tv-type').value = tv.type; $('sh-adb').hidden = tv.type !== 'android'; };
        return b;
      }));
      hint('sh-tv-hint', found.length ? 'Нажмите на свой телевизор.' : 'Не нашёл. Проверьте, что ТВ включён и в той же сети, или введите адрес.');
    });
    $('sh-tv-save').onclick = safe(async () => {
      await save('tv', { type: $('sh-tv-type').value, ip: $('sh-tv-ip').value.trim(), mac: $('sh-tv-mac').value.trim() });
      if (!$('sh-tv-type').value) { hint('sh-tv-hint', 'Сохранено'); return; }
      hint('sh-tv-hint', 'Подключаюсь — разрешите подключение на экране телевизора…');
      const { message } = await Agent.post('smarthome/pair', { what: 'tv' });
      hint('sh-tv-hint', message);
    });
    $('sh-adb').onclick = safe(async () => { hint('sh-tv-hint', 'Скачиваю ADB…'); hint('sh-tv-hint', (await Agent.post('smarthome/adb')).message); });
    $('sh-hue-find').onclick = safe(async () => {
      const { found } = await Agent.post('smarthome/discover', { what: 'hue' });
      if (found.length) $('sh-hue-bridge').value = found[0].ip; else Agent.toast('Мост Hue не найден');
    });
    $('sh-hue-pair').onclick = safe(async () => {
      await save('lights', { hue_bridge: $('sh-hue-bridge').value.trim() });
      hint('sh-light-hint', (await Agent.post('smarthome/pair', { what: 'hue' })).message);
    });
    $('sh-yee-find').onclick = safe(async () => {
      const { found } = await Agent.post('smarthome/discover', { what: 'yeelight' });
      await save('lights', { yeelight: found });
      hint('sh-yee-hint', `Ламп найдено: ${found.length}`);
    });
    $('sh-light-save').onclick = safe(async () => {
      await save('lights', { yandex_token: $('sh-ya-token').value.trim(), ha_url: $('sh-ha-url').value.trim(),
        ha_token: $('sh-ha-token').value.trim(), hue_bridge: $('sh-hue-bridge').value.trim() });
      hint('sh-light-hint', 'Сохранено');
    });
    $('sh-light-test').onclick = safe(async () => { hint('sh-light-hint', (await Agent.post('smarthome/test', { what: 'lights' })).message); });
    $('sh-r-save').onclick = safe(async () => {
      await save('router', { type: $('sh-r-type').value, address: $('sh-r-address').value.trim(),
        login: $('sh-r-login').value.trim(), password: $('sh-r-password').value });
      hint('sh-r-hint', 'Сохранено');
    });
    $('sh-r-test').onclick = safe(async () => { hint('sh-r-hint', (await Agent.post('smarthome/test', { what: 'router' })).message); });
  }

  // ---------- голоса ----------
  async function loadCatalog() {
    hint('vc-hint', 'Загружаю каталог…');
    const data = await Agent.api('voices/catalog?lang=' + encodeURIComponent($('vc-lang').value));
    const select = $('vc-lang'), current = select.value;
    select.replaceChildren(...Object.entries(data.languages).map(([code, name]) =>
      Object.assign(document.createElement('option'), { value: code, textContent: name })));
    select.value = current;
    $('vc-list').replaceChildren(...data.voices.map(v => {
      const row = document.createElement('div');
      row.className = 'found-row';
      const label = Object.assign(document.createElement('span'), { textContent: `${v.name} — ${v.quality}, ${v.size_mb} МБ` + (v.speakers > 1 ? `, голосов: ${v.speakers}` : '') });
      const b = Object.assign(document.createElement('button'), { className: 'btn ghost', textContent: v.installed ? 'Установлен' : 'Установить', disabled: v.installed });
      b.onclick = safe(async () => {
        b.disabled = true; b.textContent = 'Скачиваю…';
        const { voice } = await Agent.post('voices/install', { key: v.key });
        b.textContent = 'Установлен';
        Agent.toast(`Голос «${voice.title}» добавлен — выберите его в «Голос ассистента».`, 5000);
      });
      row.append(label, b);
      return row;
    }));
    hint('vc-hint', data.voices.length ? '' : 'Для этого языка голосов нет.');
  }
  if ($('vc-load')) {
    $('vc-load').onclick = safe(loadCatalog);
    $('vc-lang').onchange = safe(loadCatalog);
    $('vc-upload').onclick = safe(async () => {
      const files = $('vc-files').files;
      if (!files.length) { Agent.toast('Выберите файлы .onnx и .onnx.json'); return; }
      const form = new FormData();
      [...files].forEach(f => form.append('files', f));
      const { voice } = await Agent.api('voices/import', { method: 'POST', body: form });
      hint('vc-hint', `Голос «${voice.title}» добавлен.`);
    });
  }

  // ---------- зрение ----------
  if ($('vision-download')) {
    $('vision-download').onclick = safe(async () => {
      await Agent.post('models/download', { items: ['vision:' + $('vision-model').value] });
      hint('vision-state', 'Скачиваю модель зрения — прогресс в главном окне.');
    });
  }
})();
