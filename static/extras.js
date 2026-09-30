/* 6.0: «Ваши предложения», карточки документов в чате, мгновенный поиск файлов. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ICONS = { pdf: 'PDF', word: 'DOC', table: 'XLS', text: 'TXT', image: 'IMG', archive: 'ZIP', file: 'FILE' };

  function size(bytes) {
    if (!bytes) return '';
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    let n = bytes, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1).replace('.', ',') : n) + ' ' + units[i];
  }

  async function act(id, action, body) {
    try {
      const data = await Agent.post(`documents/${id}/${action}`, body || {});
      if (data.message) Agent.toast(data.message, 4000);
    } catch (e) { Agent.toast(e.message, 5000); }
  }

  // ---------- документ в чате ----------
  function card(bubbleEl, doc) {
    const box = document.createElement('div');
    box.className = 'doc-card';
    const icon = document.createElement('span');
    icon.className = 'doc-icon kind-' + (doc.kind || 'file');
    icon.textContent = ICONS[doc.kind] || 'FILE';
    const info = document.createElement('div');
    info.className = 'doc-info';
    const name = document.createElement('b');
    name.textContent = doc.name;
    name.title = doc.path || '';
    const meta = document.createElement('small');
    meta.textContent = size(doc.size);
    info.append(name, meta);
    const actions = document.createElement('div');
    actions.className = 'doc-actions';
    const buttons = [
      ['Открыть', () => act(doc.id, 'open')],
      ['В папке', () => act(doc.id, 'reveal')],
      ['Копировать', () => act(doc.id, 'copy')],
      ['Отправить…', () => sendMenu(doc, actions)],
    ];
    buttons.forEach(([label, fn]) => {
      const b = document.createElement('button');
      b.className = 'btn ghost';
      b.textContent = label;
      b.addEventListener('click', fn);
      actions.appendChild(b);
    });
    box.append(icon, info, actions);
    bubbleEl.appendChild(box);
  }

  function sendMenu(doc, anchor) {
    const old = anchor.parentElement.querySelector('.doc-send');
    if (old) { old.remove(); return; }
    const form = document.createElement('div');
    form.className = 'doc-send';
    form.innerHTML = '<select class="doc-where"><option value="telegram">Telegram</option><option value="whatsapp">WhatsApp</option>' +
      '<option value="email">Почта</option><option value="save">Сохранить в папку</option></select>' +
      '<input class="doc-to" type="text" placeholder="Кому: Милана / ivan@mail.ru / рабочий стол">' +
      '<button class="btn primary">Отправить</button>';
    const where = form.querySelector('.doc-where');
    const to = form.querySelector('.doc-to');
    form.querySelector('button').addEventListener('click', () => {
      const value = to.value.trim();
      if (where.value === 'email') act(doc.id, 'email', { to: value });
      else if (where.value === 'save') act(doc.id, 'save', { folder: value || 'рабочий стол' });
      else if (!value) { Agent.toast('Кому отправить?'); return; }
      else act(doc.id, 'telegram', { app: where.value, who: value });
      form.remove();
    });
    anchor.parentElement.appendChild(form);
    to.focus();
  }

  // ---------- «Ваши предложения» ----------
  function openSupport() {
    $('support').hidden = false;
    $('support-text').focus();
  }
  function closeSupport() { $('support').hidden = true; }

  async function sendSupport() {
    const text = $('support-text').value.trim();
    if (text.length < 3) { Agent.toast('Напишите предложение — хотя бы пару слов.'); return; }
    $('support-send').disabled = true;
    try {
      const data = await Agent.post('support/feedback', { text, contact: $('support-contact').value.trim() });
      Agent.toast(data.message, 5000);
      $('support-text').value = '';
      closeSupport();
    } catch (e) {
      Agent.toast(e.message, 5000);
    } finally {
      $('support-send').disabled = false;
    }
  }

  async function telegram() {
    try {
      const data = await Agent.post('support/telegram', { text: $('support-text').value.trim() });
      Agent.toast(data.message, 5000);
    } catch (e) { Agent.toast(e.message, 5000); }
  }

  // ---------- мгновенный поиск ----------
  let timer = null, seq = 0;
  async function search(query) {
    const box = $('fs-results');
    const mine = ++seq;
    if (!query) { box.hidden = true; return; }
    try {
      const data = await Agent.api('files/search?q=' + encodeURIComponent(query));
      if (mine !== seq) return;
      box.replaceChildren();
      const head = document.createElement('div');
      head.className = 'fs-head';
      head.textContent = data.status && !data.status.ready ? 'Индекс ещё строится…' :
        `Найдено: ${data.results.length} · ${Math.round(data.elapsed_ms || 0)} мс`;
      box.appendChild(head);
      data.results.forEach(r => {
        const row = document.createElement('button');
        row.className = 'fs-row';
        row.title = r.path;
        const b = document.createElement('b'); b.textContent = r.name;
        const s = document.createElement('small'); s.textContent = r.snippet ? '…' + r.snippet + '…' : r.folder;
        row.append(b, s);
        row.addEventListener('click', e => open(r.path, e.shiftKey));
        row.addEventListener('contextmenu', e => { e.preventDefault(); open(r.path, true); });
        box.appendChild(row);
      });
      box.hidden = false;
    } catch (e) {
      box.hidden = true;
    }
  }
  async function open(path, reveal) {
    try { await Agent.post('files/open', { path, reveal }); } catch (e) { Agent.toast(e.message); }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if ($('suggest-btn')) $('suggest-btn').addEventListener('click', openSupport);
    if ($('support-send')) $('support-send').addEventListener('click', sendSupport);
    if ($('support-tg')) $('support-tg').addEventListener('click', telegram);
    if ($('support-close')) $('support-close').addEventListener('click', closeSupport);
    if ($('support')) $('support').addEventListener('click', e => { if (e.target.id === 'support') closeSupport(); });
    const input = $('file-search');
    if (input) {
      input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => search(input.value.trim()), 60); });
      input.addEventListener('keydown', e => {
        if (e.key === 'Escape') { input.value = ''; $('fs-results').hidden = true; }
        if (e.key === 'Enter') { const first = $('fs-results').querySelector('.fs-row'); if (first) first.click(); }
      });
      document.addEventListener('click', e => { if (!e.target.closest('.file-search')) $('fs-results').hidden = true; });
    }
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && $('support') && !$('support').hidden) closeSupport();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && input) { e.preventDefault(); input.focus(); }
    });
  });

  window.AgentExtras = { card, openSupport };
})();
