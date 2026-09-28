/* Красивые выпадающие списки для всех тем: плавно раскрываются и сворачиваются, работают с клавиатуры.
   Настоящий <select> остаётся на месте (скрыт) — значения, события change и автосохранение не меняются. */
(() => {
  'use strict';
  const CHEVRON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>';
  const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7"/></svg>';
  let open = null;

  function label(select) {
    const option = select.options[select.selectedIndex];
    return option ? option.textContent : '—';
  }

  function build(select) {
    const wrap = document.createElement('div');
    wrap.className = 'dd';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'dd-btn';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = '<span class="dd-value"></span><span class="dd-chevron">' + CHEVRON + '</span>';
    const list = document.createElement('ul');
    list.className = 'dd-list';
    list.setAttribute('role', 'listbox');
    list.tabIndex = -1;
    select.parentNode.insertBefore(wrap, select);
    wrap.append(select, button, list);
    select.classList.add('dd-native');
    select.tabIndex = -1;

    const sync = () => {
      button.querySelector('.dd-value').textContent = label(select);
      button.disabled = select.disabled;
      [...list.children].forEach((li, i) => li.setAttribute('aria-selected', i === select.selectedIndex));
    };
    const fill = () => {
      list.replaceChildren(...[...select.options].map((option, index) => {
        const li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.dataset.index = index;
        li.innerHTML = '<span></span><i>' + CHECK + '</i>';
        li.firstChild.textContent = option.textContent;
        if (option.disabled) li.setAttribute('aria-disabled', 'true');
        li.onclick = () => choose(index);
        return li;
      }));
      sync();
    };
    const choose = index => {
      if (select.options[index].disabled) return;
      const changed = select.selectedIndex !== index;
      select.selectedIndex = index;
      sync();
      close();
      button.focus();
      if (changed) select.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const focusItem = index => {
      const items = [...list.children];
      const i = Math.max(0, Math.min(items.length - 1, index));
      items.forEach(li => li.classList.toggle('active', li === items[i]));
      if (items[i]) items[i].scrollIntoView({ block: 'nearest' });
      return i;
    };
    let active = 0;
    const show = () => {
      if (button.disabled) return;
      if (open && open !== close) open();
      sync();
      const rect = button.getBoundingClientRect();
      wrap.classList.toggle('up', window.innerHeight - rect.bottom < 280 && rect.top > window.innerHeight - rect.bottom);
      wrap.classList.add('open');
      button.setAttribute('aria-expanded', 'true');
      active = focusItem(select.selectedIndex);
      open = close;
    };
    function close() {
      wrap.classList.remove('open');
      button.setAttribute('aria-expanded', 'false');
      if (open === close) open = null;
    }
    button.onclick = () => (wrap.classList.contains('open') ? close() : show());
    button.addEventListener('keydown', e => {
      const isOpen = wrap.classList.contains('open');
      if (['ArrowDown', 'ArrowUp'].includes(e.key)) {
        e.preventDefault();
        if (!isOpen) return show();
        active = focusItem(active + (e.key === 'ArrowDown' ? 1 : -1));
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        isOpen ? choose(active) : show();
      } else if (e.key === 'Escape' && isOpen) {
        e.preventDefault(); e.stopPropagation(); close();
      } else if (e.key === 'Tab') {
        close();
      } else if (e.key.length === 1 && isOpen) {
        const found = [...select.options].findIndex(o => o.textContent.toLowerCase().startsWith(e.key.toLowerCase()));
        if (found >= 0) active = focusItem(found);
      }
    });
    select.addEventListener('change', sync);
    new MutationObserver(fill).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
    wrap._sync = sync;
    fill();
  }

  function enhance(root = document) {
    root.querySelectorAll('select:not([hidden]):not([data-native]):not(.dd-native)').forEach(build);
  }

  // Значения меняются и из кода (загрузка настроек) — подпись обновляем сами.
  setInterval(() => document.querySelectorAll('.dd').forEach(d => d._sync && d._sync()), 400);
  document.addEventListener('click', e => { if (open && !e.target.closest('.dd.open')) open(); });
  window.addEventListener('resize', () => open && open());
  window.AgentSelect = { enhance };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => enhance());
  else enhance();
})();
