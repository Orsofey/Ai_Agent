/* Settings: напоминания, макросы, узнавание голоса. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children.filter(c => c != null));
    return node;
  };
  const row = (label, hint, ...controls) => el('div', { className: 'row' },
    el('div', { className: 'label' }, el('b', { textContent: label }), hint ? el('small', { textContent: hint }) : null),
    el('div', { className: 'control' }, ...controls));
  const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  const address = () => {
    const a = (Agent.settings && Agent.settings.address) || 'сэр';
    return a === 'none' ? '' : a;
  };
  const preview = text => text.replace('{Address}', address() ? address()[0].toUpperCase() + address().slice(1) : '')
    .replace('{address}', address()).replace(/^\s*,\s*/, '');

  // ---------------- напоминания ----------------
  let reminders = [];

  function reminderCard(item, index) {
    const text = el('input', { value: item.text, maxLength: 300, style: 'width:100%' });
    const enabled = el('input', { type: 'checkbox', checked: item.enabled !== false });
    const kind = el('select', {}, ...[['once', 'Один раз'], ['daily', 'Каждый день'], ['weekly', 'По дням недели'],
      ['interval', 'Каждые N минут']].map(([v, t]) => el('option', { value: v, textContent: t, selected: item.kind === v })));
    const time = el('input', { type: 'time', value: item.time || '09:00' });
    const at = el('input', { type: 'datetime-local',
      value: item.at ? new Date(item.at * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : '' });
    const every = el('input', { type: 'number', min: 5, max: 1440, value: item.every || 60, style: 'width:90px' });
    const from = el('input', { type: 'time', value: item.from || '09:00' });
    const to = el('input', { type: 'time', value: item.to || '22:00' });
    const days = DAYS.map((d, i) => el('label', { className: 'day-chip' },
      el('input', { type: 'checkbox', checked: (item.days || [0, 1, 2, 3, 4]).includes(i) }), el('span', { textContent: d })));
    const test = el('button', { className: 'btn ghost', textContent: 'Прослушать' });
    const remove = el('button', { className: 'btn ghost', textContent: 'Удалить' });
    const rows = {
      time: row('Время', null, time), at: row('Когда', null, at),
      days: el('div', { className: 'row stack' }, el('div', { className: 'label' }, el('b', { textContent: 'Дни' })),
        el('div', { className: 'control days' }, ...days)),
      every: row('Каждые, минут', 'Звучит только в указанные часы.', every, el('span', { textContent: ' с ' }), from,
        el('span', { textContent: ' до ' }), to),
    };
    const show = () => {
      const k = kind.value;
      rows.time.hidden = !(k === 'daily' || k === 'weekly');
      rows.days.hidden = k !== 'weekly';
      rows.at.hidden = k !== 'once';
      rows.every.hidden = k !== 'interval';
    };
    kind.onchange = show;
    show();
    const note = item.builtin ? 'Встроенное — можно выключить или удалить.' : (item.when ? 'Сейчас: ' + item.when : null);
    const box = el('div', { className: 'card group' },
      row(preview(item.text) || 'Напоминание', note, el('label', { className: 'switch' }, enabled, el('span'))),
      el('div', { className: 'row stack' }, el('div', { className: 'label' }, el('b', { textContent: 'Текст' }),
        el('small', { textContent: '{Address} — ваше обращение («Сэр»).' })), text),
      row('Повторять', null, kind), rows.time, rows.days, rows.at, rows.every,
      el('div', { className: 'row stack' }, el('div', { className: 'control' }, test, remove)));
    box.read = () => {
      const value = { ...item, text: text.value.trim(), enabled: enabled.checked, kind: kind.value };
      if (kind.value === 'daily' || kind.value === 'weekly') value.time = time.value || '09:00';
      if (kind.value === 'weekly') value.days = days.map((d, i) => d.firstChild.checked ? i : -1).filter(i => i >= 0);
      if (kind.value === 'interval') Object.assign(value, { every: Number(every.value) || 60, from: from.value, to: to.value });
      if (kind.value === 'once') value.at = at.value ? new Date(at.value).getTime() / 1000 : Date.now() / 1000 + 3600;
      return value;
    };
    test.onclick = async () => {
      try { await saveReminders(true); Agent.toast((await Agent.post('reminders/test', { id: item.id })).text); }
      catch (e) { Agent.toast(e.message, 4000); }
    };
    remove.onclick = () => { collectReminders(); reminders.splice(index, 1); renderReminders(); $('rm-hint').textContent = 'Не забудьте сохранить.'; };
    return box;
  }

  const renderReminders = () => $('rm-list').replaceChildren(...reminders.map(reminderCard));
  const collectReminders = () => (reminders = [...$('rm-list').children].map(c => c.read()));

  async function saveReminders(quiet) {
    const data = await Agent.post('reminders', { items: collectReminders() });
    reminders = data.items;
    if (!quiet) { renderReminders(); Agent.toast('Напоминания сохранены.'); }
    $('rm-hint').textContent = '';
  }

  async function loadReminders() {
    try {
      const data = await Agent.api('reminders');
      reminders = data.items;
      $('rm-on').checked = !data.muted;
      renderReminders();
    } catch (e) { $('rm-hint').textContent = e.message; }
  }

  $('rm-add').onclick = () => {
    collectReminders();
    reminders.push({ text: 'Новое напоминание', kind: 'daily', time: '09:00', enabled: true });
    renderReminders();
  };
  $('rm-save').onclick = () => saveReminders(false).catch(e => Agent.toast(e.message, 4000));
  $('rm-on').onchange = e => Agent.post('reminders/mute', { muted: !e.target.checked }).catch(err => Agent.toast(err.message));
  $('rm-interview').onclick = async () => {
    try {
      const data = await Agent.post('chat', { message: 'настрой напоминания', id: Agent.uid().replace(/[^\w-]/g, '') });
      Agent.toast(data.response + ' Ответьте голосом или в главном окне.', 9000);
    } catch (e) { Agent.toast(e.message, 5000); }
  };

  // ---------------- макросы ----------------
  let macros = [];

  function macroCard(item, index) {
    const name = el('input', { value: item.name, maxLength: 40 });
    const phrase = el('input', { value: item.phrase || '', maxLength: 80, placeholder: 'необязательно, например: доброе утро' });
    const steps = el('textarea', { className: 'field', rows: 4, value: (item.steps || []).join('\n'),
      placeholder: 'открой почту\nподожди 3 секунды\nоткрой ютуб', style: 'width:100%;resize:vertical' });
    const run = el('button', { className: 'btn primary', textContent: 'Запустить' });
    const remove = el('button', { className: 'btn ghost', textContent: 'Удалить' });
    const box = el('div', { className: 'card group' },
      row('Название', '«Запусти макрос …»', name),
      row('Фраза запуска', 'Скажете её после имени — и макрос выполнится.', phrase),
      el('div', { className: 'row stack' }, el('div', { className: 'label' }, el('b', { textContent: 'Шаги' }),
        el('small', { textContent: 'По одной команде на строке.' })), steps),
      el('div', { className: 'row stack' }, el('div', { className: 'control' }, run, remove)));
    box.read = () => ({ name: name.value.trim(), phrase: phrase.value.trim(),
      steps: steps.value.split('\n').map(s => s.trim()).filter(Boolean) });
    run.onclick = async () => {
      try { await saveMacros(true); Agent.toast((await Agent.post('macros/run', { name: name.value.trim() })).message, 5000); }
      catch (e) { Agent.toast(e.message, 5000); }
    };
    remove.onclick = () => { collectMacros(); macros.splice(index, 1); renderMacros(); $('mc-hint').textContent = 'Не забудьте сохранить.'; };
    return box;
  }

  const renderMacros = () => $('mc-list').replaceChildren(...macros.map(macroCard));
  const collectMacros = () => (macros = [...$('mc-list').children].map(c => c.read()));

  async function saveMacros(quiet) {
    const data = await Agent.post('macros', { items: collectMacros() });
    macros = data.items;
    if (!quiet) { renderMacros(); Agent.toast('Макросы сохранены.'); }
    $('mc-hint').textContent = '';
  }

  $('mc-add').onclick = () => { collectMacros(); macros.push({ name: 'новый макрос', phrase: '', steps: [] }); renderMacros(); };
  $('mc-save').onclick = () => saveMacros(false).catch(e => Agent.toast(e.message, 4000));
  Agent.api('macros').then(d => { macros = d.items; renderMacros(); }).catch(() => {});

  // ---------------- узнавание голоса ----------------
  function showVoice(data) {
    $('vid-download').hidden = data.model_installed;
    $('vid-enroll').disabled = !data.model_installed;
    $('vid-hint').textContent = data.model_installed ? (data.enrolling ? 'Говорите три фразы…' : '') : 'Нужна модель (≈28 МБ).';
    $('vid-pass-state').textContent = data.has_password ? 'Пароль задан. Чтобы сменить — введите новый.'
      : 'Не задан: незнакомцам придётся знакомиться через ваши настройки.';
    $('vid-list').replaceChildren(...(data.profiles.length ? data.profiles.map(p => {
      const del = el('button', { className: 'btn ghost', textContent: 'Забыть' });
      del.onclick = async () => showVoice(await Agent.post('voiceid/delete', { id: p.id }));
      return el('li', {}, el('b', { textContent: p.name }), ` — запомнен ${p.created}, фраз: ${p.samples} `, del);
    }) : [el('li', { textContent: 'Пока ни одного — нажмите «Запомнить мой голос».' })]));
  }
  const loadVoice = () => Agent.api('voiceid').then(showVoice).catch(e => { $('vid-hint').textContent = e.message; });

  $('vid-download').onclick = async () => {
    await Agent.post('voiceid/download');
    $('vid-hint').textContent = 'Скачиваю модель…';
    const timer = setInterval(async () => {
      const data = await Agent.api('voiceid');
      if (data.model_installed) { clearInterval(timer); showVoice(data); Agent.toast('Модель голоса установлена.'); }
    }, 3000);
  };
  $('vid-enroll').onclick = async () => {
    try {
      const data = await Agent.post('voiceid/enroll', {});
      Agent.toast(data.message, 9000);
      showVoice(data);
    } catch (e) { Agent.toast(e.message, 5000); }
  };
  $('vid-password-save').onclick = async () => {
    try {
      showVoice(await Agent.post('voiceid/password', { password: $('vid-password').value }));
      $('vid-password').value = '';
      Agent.toast('Голосовой пароль сохранён.');
    } catch (e) { Agent.toast(e.message, 5000); }
  };
  Agent.connectEvents(e => {
    if (e.type === 'voiceid') {
      if (e.stage === 'sample') $('vid-hint').textContent = `Запомнил фразу ${e.count} из ${e.total}…`;
      if (e.stage === 'done' || e.stage === 'timeout') loadVoice();
    }
  });

  loadReminders();
  loadVoice();
})();
