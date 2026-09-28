/* Settings: сценарии («Работа», «Игра»…) и подключение Трекера. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children.filter(c => c != null));
    return node;
  };
  const minutesText = m => {
    if (m == null) return '';
    const h = Math.floor(m / 60), r = m % 60;
    return [h ? h + ' ч' : '', r ? r + ' мин' : ''].filter(Boolean).join(' ') || 'меньше минуты';
  };

  // ---------------- сценарии ----------------
  let scenarios = [];

  function row(label, hint, control) {
    return el('div', { className: 'row' },
      el('div', { className: 'label' }, el('b', { textContent: label }), hint ? el('small', { textContent: hint }) : null),
      el('div', { className: 'control' }, control));
  }

  function listField(value, placeholder) {
    return el('textarea', { className: 'field', rows: 2, value: (value || []).join(', '), placeholder,
      style: 'width:100%;resize:vertical', maxLength: 2000 });
  }

  function card(item, index) {
    const name = el('input', { value: item.name, maxLength: 40 });
    const minutes = el('input', { type: 'number', min: 1, max: 1440, value: item.minutes, style: 'width:110px' });
    const sites = listField(item.sites, 'youtube.com, vk.com, tiktok.com');
    const apps = listField(item.apps, 'steam, discord');
    const open = listField(item.open, 'например: steam, discord');
    const gray = el('input', { type: 'checkbox', checked: !!item.grayscale });
    const start = el('button', { className: 'btn primary', textContent: 'Включить' });
    const remove = el('button', { className: 'btn ghost', textContent: 'Удалить' });
    const box = el('div', { className: 'card group' },
      row('Название', 'Так и говорите: «включи сценарий …»', name),
      row('Длительность, минут', 'Можно назвать другое время голосом: «…на 2 часа».', minutes),
      el('div', { className: 'row stack' }, el('div', { className: 'label' }, el('b', { textContent: 'Блокировать сайты' }),
        el('small', { textContent: 'Через запятую: адреса или названия доменов.' })), sites),
      el('div', { className: 'row stack' }, el('div', { className: 'label' }, el('b', { textContent: 'Блокировать приложения' }),
        el('small', { textContent: 'Через запятую, как вы их называете: steam, discord, telegram.' })), apps),
      el('div', { className: 'row stack' }, el('div', { className: 'label' }, el('b', { textContent: 'Запустить при включении' })), open),
      row('Чёрно-белый экран', 'На время сценария — меньше хочется залипать.', el('label', { className: 'switch' }, gray, el('span'))),
      el('div', { className: 'row stack' }, el('div', { className: 'control' }, start, remove)));
    const split = t => t.value.split(/[,\n;]+/).map(s => s.trim()).filter(Boolean);
    box.read = () => ({ name: name.value.trim(), minutes: Number(minutes.value) || 60, sites: split(sites),
      apps: split(apps), open: split(open), grayscale: gray.checked });
    start.onclick = async () => {
      try {
        await save(true);
        const data = await Agent.post('scenarios/start', { name: name.value.trim(), minutes: Number(minutes.value) || null });
        Agent.toast(data.message, 4000);
        showState(data.state);
      } catch (e) { Agent.toast(e.message, 4000); }
    };
    remove.onclick = () => { collect(); scenarios.splice(index, 1); render(); $('sc-hint').textContent = 'Не забудьте сохранить.'; };
    return box;
  }

  function render() {
    $('sc-list').replaceChildren(...scenarios.map(card));
  }

  function collect() {
    scenarios = [...$('sc-list').children].map(c => c.read());
    return scenarios;
  }

  async function save(quiet) {
    const data = await Agent.post('scenarios', { scenarios: collect() });
    scenarios = data.scenarios;
    if (!quiet) { render(); Agent.toast('Сценарии сохранены.'); }
    $('sc-hint').textContent = '';
  }

  function showState(state) {
    if (!state) return;
    $('sc-state').textContent = state.scenario ? `Включён «${state.scenario}», осталось ${minutesText(state.left)}.`
      : state.blocks.length ? 'Сценарий не включён, есть отдельные блокировки.' : 'Ничего не заблокировано.';
    const own = state.blocks.filter(b => !b.source);
    $('sc-blocks').hidden = !own.length;
    $('sc-blocks').replaceChildren(...own.map(b =>
      el('li', {}, el('b', { textContent: b.value }), ` — ${b.kind === 'site' ? 'сайт' : 'приложение'}, ещё ${minutesText(b.left)}`)));
  }

  async function loadScenarios() {
    try {
      const data = await Agent.api('scenarios');
      scenarios = data.scenarios;
      render();
      showState(data.state);
    } catch (e) { $('sc-state').textContent = e.message; }
  }

  $('sc-add').onclick = () => {
    collect();
    scenarios.push({ name: 'Новый сценарий', minutes: 60, sites: [], apps: [], open: [], grayscale: false });
    render();
  };
  $('sc-save').onclick = () => save(false).catch(e => Agent.toast(e.message, 4000));
  $('sc-stop').onclick = async () => {
    try {
      const data = await Agent.post('scenarios/stop', { unblock: true });
      Agent.toast(data.message);
      showState(data.state);
    } catch (e) { Agent.toast(e.message, 4000); }
  };

  // ---------------- Трекер ----------------
  function showTracker(status) {
    $('tr-state').textContent = status.connected ? `Подключён: ${status.user || 'аккаунт'} · ${status.url}`
      : status.url ? 'Вход устарел — войдите снова.' : 'Не подключён.';
    $('tr-form').hidden = status.connected;
    $('tr-test').hidden = $('tr-logout').hidden = !status.connected;
    if (status.url && !$('tr-url').value) $('tr-url').value = status.url;
  }

  async function loadTracker() {
    try { showTracker(await Agent.api('tracker')); } catch (e) { $('tr-state').textContent = e.message; }
  }

  $('tr-login').onclick = async () => {
    $('tr-hint').textContent = 'Подключаюсь…';
    try {
      const status = await Agent.post('tracker/login', { url: $('tr-url').value.trim(), email: $('tr-email').value.trim(),
        password: $('tr-password').value, token: $('tr-token').value.trim() });
      $('tr-password').value = $('tr-token').value = '';
      $('tr-hint').textContent = '';
      showTracker(status);
      Agent.toast('Трекер подключён. Спросите: «Что в трекере на сегодня?»', 4000);
    } catch (e) { $('tr-hint').textContent = e.message; }
  };
  $('tr-logout').onclick = async () => { showTracker(await Agent.post('tracker/logout')); };
  $('tr-test').onclick = async () => {
    try { Agent.toast((await Agent.post('tracker/test')).message, 4000); } catch (e) { Agent.toast(e.message, 5000); }
  };

  loadScenarios();
  loadTracker();
  setInterval(() => {
    if ($('page-scenarios').classList.contains('active')) Agent.api('scenarios').then(d => showState(d.state)).catch(() => {});
  }, 30000);
})();
