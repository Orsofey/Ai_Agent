/* «Жидкое стекло» для тем «Стекло» и «Стекло: ночь».
   1) Настоящее преломление: для каждой стеклянной панели рассчитывается карта смещений по её форме (профиль выпуклой
      линзы у кромки) → SVG-фильтр feDisplacementMap в backdrop-filter. Три канала смещаются по-разному — радужная
      дисперсия на кромке, как у призмы. Работает в Chromium (Windows, WebView2); в Safari — матовое стекло без линзы.
   2) Свет: блик на кромках следует за курсором (одни координаты на всё окно, background-attachment: fixed).
   3) Объёмные стеклянные фигуры фона (SVG) с параллаксом.
   4) Если компьютер не тянет (меньше ~40 кадров/с), преломление само выключается. */
(() => {
  'use strict';
  const root = document.documentElement;
  const NS = 'http://www.w3.org/2000/svg';
  const SELECTOR = '.card, .topbar, .side, .btn.primary, .pill, .chip, .suggest-chip, .dd-list, .pause-btn, .account-chip, .doc-card';
  const chromium = /Chrome\/|Edg\//.test(navigator.userAgent) && !/Firefox\//.test(navigator.userAgent);
  const active = () => /^glass/.test(root.dataset.theme || '');
  const maps = new Map();          // ключ размера → id фильтра
  let defs = null, uid = 0, lite = false;

  // ---------- карта смещений ----------
  function refractionMap(w, h, radius, bezel) {
    // Считаем в половинном разрешении — feImage растягивает без потери качества (смещения плавные).
    const k = w * h > 250000 ? 0.5 : 1;
    const cw = Math.max(2, Math.round(w * k)), ch = Math.max(2, Math.round(h * k));
    const canvas = document.createElement('canvas');
    canvas.width = cw; canvas.height = ch;
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(cw, ch);
    const data = img.data;
    const r = radius * k, b = Math.max(2, bezel * k), hw = cw / 2, hh = ch / 2;
    for (let y = 0; y < ch; y++) {
      for (let x = 0; x < cw; x++) {
        const i = (y * cw + x) * 4;
        let dx = 128, dy = 128;
        const px = x + 0.5 - hw, py = y + 0.5 - hh;
        const ax = Math.abs(px), ay = Math.abs(py);
        const qx = ax - (hw - r), qy = ay - (hh - r);
        let d, nx, ny;
        if (qx > 0 && qy > 0) { const len = Math.hypot(qx, qy) || 1; d = len - r; nx = qx / len; ny = qy / len; }
        else if (qx > qy) { d = qx - r; nx = 1; ny = 0; } else { d = qy - r; nx = 0; ny = 1; }
        const inside = -d;
        if (inside >= 0 && inside < b) {
          // Профиль «squircle»: поверхность круто уходит вниз у самой кромки — там и сильнее всего преломление.
          const t = inside / b;
          const slope = Math.pow(1 - t, 2.2);
          const sx = Math.sign(px) || 1, sy = Math.sign(py) || 1;
          dx = 128 - nx * sx * slope * 127;   // берём пиксели ближе к центру — край «собирает» фон, как линза
          dy = 128 - ny * sy * slope * 127;
        }
        data[i] = dx; data[i + 1] = dy; data[i + 2] = 128; data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL();
  }

  function ensureDefs() {
    if (defs) return defs;
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('width', '0'); svg.setAttribute('height', '0');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
    defs = document.createElementNS(NS, 'defs');
    svg.appendChild(defs);
    document.body.appendChild(svg);
    return defs;
  }

  function filterFor(w, h, radius) {
    const W = Math.round(w / 4) * 4, H = Math.round(h / 4) * 4, R = Math.min(Math.round(radius), W / 2, H / 2);
    const key = `${W}x${H}r${R}`;
    if (maps.has(key)) return maps.get(key);
    const bezel = Math.min(Math.max(10, Math.min(W, H) * 0.22), 34);
    const scale = Math.min(bezel * 1.35, 44);
    const id = 'lg' + (++uid);
    const href = refractionMap(W, H, R, bezel);
    // Карта должна быть декодирована ДО того, как фильтр попадёт в backdrop-filter: иначе Chromium возьмёт пустую
    // карту (сдвиг на полшкалы) и не перерисует панель, когда картинка догрузится.
    const image = new Image();
    image.src = href;
    const ready = (image.decode ? image.decode() : Promise.resolve()).catch(() => {});
    const channel = (s, m, res) => `
      <feDisplacementMap in="SourceGraphic" in2="map" scale="${s.toFixed(1)}" xChannelSelector="R" yChannelSelector="G" result="d${res}"/>
      <feColorMatrix in="d${res}" type="matrix" values="${m} 0 0 0 1 0" result="${res}"/>`;
    const f = document.createElementNS(NS, 'filter');
    f.setAttribute('id', id);
    f.setAttribute('x', '0'); f.setAttribute('y', '0'); f.setAttribute('width', W); f.setAttribute('height', H);
    f.setAttribute('filterUnits', 'userSpaceOnUse');
    f.setAttribute('color-interpolation-filters', 'sRGB');
    f.innerHTML = `
      <feImage href="${href}" x="0" y="0" width="${W}" height="${H}" preserveAspectRatio="none" result="map"/>
      ${channel(scale, '1 0 0 0 0  0 0 0 0 0  0 0 0 0 0', 'r')}
      ${channel(scale * 0.9, '0 0 0 0 0  0 1 0 0 0  0 0 0 0 0', 'g')}
      ${channel(scale * 0.8, '0 0 0 0 0  0 0 0 0 0  0 0 1 0 0', 'b')}
      <feBlend in="r" in2="g" mode="screen" result="rg"/>
      <feBlend in="rg" in2="b" mode="screen"/>`;
    const entry = { id, ready: ready.then(() => { ensureDefs().appendChild(f); }) };
    maps.set(key, entry);
    if (maps.size > 90) {                           // не копим фильтры бесконечно
      const [oldKey, old0] = maps.entries().next().value;
      const oldId = old0.id;
      maps.delete(oldKey);
      const old = document.getElementById(oldId);
      if (old && !document.querySelector(`[style*="#${oldId})"]`)) old.remove();
    }
    return entry;
  }

  // ---------- применение к элементам ----------
  const sized = new WeakMap();
  // Стекло внутри другого стекла не видит страницу (Chromium ограничивает «фон» внешней панелью) —
  // преломляем только панели верхнего уровня, вложенным остаётся матовое стекло.
  const NESTING = SELECTOR + ', .msg';
  function refract(el) {
    if (!active() || lite || !chromium || el.parentElement?.closest(NESTING)) { el.style.removeProperty('--lg-filter'); return; }
    const box = el.getBoundingClientRect();
    if (box.width < 8 || box.height < 8) return;
    const radius = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
    const key = `${Math.round(box.width / 4)}:${Math.round(box.height / 4)}:${Math.round(radius)}`;
    if (sized.get(el) === key) return;
    sized.set(el, key);
    const entry = filterFor(box.width, box.height, radius);
    entry.ready.then(() => {
      // Даём браузеру один кадр, чтобы фильтр с готовой картой попал в дерево SVG.
      requestAnimationFrame(() => {
        if (sized.get(el) === key && active() && !lite) el.style.setProperty('--lg-filter', `url(#${entry.id})`);
      });
    });
  }

  const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(entries => entries.forEach(e => refract(e.target))) : null;
  const watched = new WeakSet();
  function scan(scope = document) {
    if (!active()) return;
    scope.querySelectorAll?.(SELECTOR).forEach(el => {
      if (!watched.has(el)) { watched.add(el); resize && resize.observe(el); }
      refract(el);
    });
  }
  const mutations = new MutationObserver(list => {
    if (!active()) return;
    for (const m of list) m.addedNodes.forEach(n => {
      if (n.nodeType !== 1) return;
      if (n.matches?.(SELECTOR)) scan(n.parentNode || document); else scan(n);
    });
  });

  // ---------- свет за курсором и параллакс ----------
  let pending = false, lx = innerWidth * 0.3, ly = innerHeight * 0.2;
  function light() {
    pending = false;
    root.style.setProperty('--lx', lx + 'px');
    root.style.setProperty('--ly', ly + 'px');
    if (lite) return;
    const cx = (lx / innerWidth - 0.5), cy = (ly / innerHeight - 0.5);
    document.querySelectorAll('body > .scene .glass-shape').forEach(s => {
      const depth = parseFloat(s.dataset.depth || '1');
      s.style.translate = `${(-cx * 26 * depth).toFixed(1)}px ${(-cy * 20 * depth).toFixed(1)}px`;
    });
  }
  addEventListener('pointermove', e => {
    if (!active()) return;
    lx = e.clientX; ly = e.clientY;
    if (!pending) { pending = true; requestAnimationFrame(light); }
  }, { passive: true });

  // ---------- защита производительности ----------
  const forced = () => { try { return localStorage.getItem('glass_quality'); } catch (e) { return null; } };
  function measure() {
    if (!active() || !chromium || root.dataset.animations === 'off' || forced() === 'max') return;
    let frames = 0, start = 0;
    const tick = t => {
      if (!start) start = t;
      frames++;
      if (t - start < 1500) return requestAnimationFrame(tick);
      const fps = frames * 1000 / (t - start);
      if (fps < 40 && !lite) {
        lite = true;
        root.classList.add('lg-lite');
        root.classList.remove('lg-refract');
        document.querySelectorAll(SELECTOR).forEach(el => el.style.removeProperty('--lg-filter'));
      }
    };
    setTimeout(() => requestAnimationFrame(tick), 1200);
  }

  function update() {
    if (forced() === 'lite') { lite = true; root.classList.add('lg-lite'); }
    root.classList.toggle('lg-refract', active() && chromium && !lite);
    if (active()) { scan(); light(); }
  }

  // ---------- объёмные стеклянные фигуры фона ----------
  const SHAPES = {
    disc: a => `<path d="M58 16a44 44 0 1 0 46 46H58z" ${a}/><path d="M66 8a46 46 0 0 1 46 46H66z" ${a}/>`,
    squircle: a => `<path d="M60 10c34 0 50 16 50 50s-16 50-50 50-50-16-50-50 16-50 50-50z" ${a}/>`,
    layers: a => `<rect x="18" y="12" width="84" height="30" rx="14" ${a}/><rect x="18" y="45" width="84" height="30" rx="14" ${a}/><rect x="18" y="78" width="84" height="30" rx="14" ${a}/>`,
    shield: a => `<path d="M60 8l44 14v36c0 28-20 46-44 56-24-10-44-28-44-56V22z" ${a}/>`,
    ring: a => `<path fill-rule="evenodd" d="M60 12a48 48 0 1 1 0 96a48 48 0 1 1 0-96zm0 28a20 20 0 1 0 0 40a20 20 0 1 0 0-40z" ${a}/>`,
    drop: a => `<path d="M60 6s44 46 44 70c0 24-20 38-44 38S16 100 16 76C16 52 60 6 60 6z" ${a}/>`,
    arch: a => `<path d="M12 84a48 48 0 0 1 96 0v12a8 8 0 0 1-8 8H84a8 8 0 0 1-8-8V84a16 16 0 0 0-32 0v12a8 8 0 0 1-8 8H20a8 8 0 0 1-8-8z" ${a}/>`,
    pill: a => `<rect x="10" y="36" width="100" height="48" rx="24" ${a}/>`,
  };
  function shape(kind, colors) {
    const n = ++uid, [c1, c2, c3] = colors;
    const draw = SHAPES[kind] || SHAPES.squircle;
    return `<svg viewBox="0 0 120 120" aria-hidden="true"><defs>
      <linearGradient id="b${n}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c1}" stop-opacity=".95"/>
        <stop offset=".55" stop-color="${c2}" stop-opacity=".78"/><stop offset="1" stop-color="${c3}" stop-opacity=".92"/></linearGradient>
      <radialGradient id="g${n}" cx=".3" cy=".2" r=".75"><stop offset="0" stop-color="#fff" stop-opacity=".8"/>
        <stop offset=".45" stop-color="#fff" stop-opacity=".14"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
      <radialGradient id="c${n}" cx=".72" cy=".9" r=".55"><stop offset="0" stop-color="#fff" stop-opacity=".7"/>
        <stop offset=".35" stop-color="${c1}" stop-opacity=".45"/><stop offset="1" stop-color="${c1}" stop-opacity="0"/></radialGradient>
      <linearGradient id="r${n}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".98"/>
        <stop offset=".35" stop-color="#fff" stop-opacity=".18"/><stop offset=".7" stop-color="#fff" stop-opacity=".06"/>
        <stop offset="1" stop-color="#fff" stop-opacity=".7"/></linearGradient>
      <clipPath id="k${n}">${draw('')}</clipPath>
      <filter id="f${n}" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.6"/></filter>
      </defs>
      ${draw(`fill="url(#b${n})"`)}
      <g clip-path="url(#k${n})">
        <rect width="120" height="120" fill="url(#c${n})"/><rect width="120" height="120" fill="url(#g${n})"/>
        <ellipse cx="42" cy="26" rx="28" ry="9" fill="#fff" opacity=".6" filter="url(#f${n})" transform="rotate(-22 42 26)"/>
        <g filter="url(#f${n})" opacity=".55">${draw('fill="none" stroke="#fff" stroke-width="5"')}</g>
      </g>
      ${draw(`fill="none" stroke="url(#r${n})" stroke-width="1.5"`)}
    </svg>`;
  }

  window.LiquidGlass = { shape, scan, update, get lite() { return lite; } };

  const start = () => {
    mutations.observe(document.body, { childList: true, subtree: true });
    new MutationObserver(() => { update(); if (active()) measure(); })
      .observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    update();
    measure();
    addEventListener('resize', () => active() && scan());
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
