/* Living backgrounds: petals for Sakura, bubbles for Ocean, cobalt petals for Gzhel, embers for Slavic,
   floating glass shapes for Glass. */
(() => {
  'use strict';
  const random = (a, b) => a + Math.random() * (b - a);
  function decorate(scene, theme) {
    if (!scene) return;
    scene.querySelectorAll('.particle').forEach(p => p.remove());
    const compact = scene.dataset.compact === '1';
    if (theme === 'sakura') {
      for (let i = 0; i < (compact ? 6 : 22); i++) {
        const p = document.createElement('i');
        p.className = 'particle petal';
        const fall = random(9, 20), sway = random(2.5, 5);
        p.style.left = random(-5, 100) + '%';
        p.style.transform = `scale(${random(.6, 1.3)})`;
        p.style.animationDuration = `${fall}s, ${sway}s`;
        p.style.animationDelay = `${-random(0, fall)}s, ${-random(0, sway)}s`;
        scene.appendChild(p);
      }
    } else if (theme === 'gzhel') {
      for (let i = 0; i < (compact ? 3 : 10); i++) {
        const p = document.createElement('i');
        p.className = 'particle gz-petal';
        const fall = random(16, 30), sway = random(4, 7);
        p.style.left = random(0, 100) + '%';
        p.style.transform = `scale(${random(.6, 1.2)}) rotate(${random(0, 360)}deg)`;
        p.style.animationDuration = `${fall}s, ${sway}s`;
        p.style.animationDelay = `${-random(0, fall)}s, ${-random(0, sway)}s`;
        scene.appendChild(p);
      }
    } else if (theme === 'slavic') {
      for (let i = 0; i < (compact ? 6 : 22); i++) {
        const e = document.createElement('i');
        e.className = 'particle ember';
        const size = random(2, compact ? 4 : 6), rise = random(12, 28), wobble = random(2, 5);
        e.style.width = e.style.height = size + 'px';
        e.style.left = random(0, 100) + '%';
        e.style.animationDuration = `${rise}s, ${wobble}s, ${random(1, 2.4)}s`;
        e.style.animationDelay = `${-random(0, rise)}s, ${-random(0, wobble)}s, ${-random(0, 2)}s`;
        scene.appendChild(e);
      }
    } else if (theme.startsWith('glass')) {
      // Объёмные стеклянные фигуры (SVG из glass.js) по краям окна; data-depth — сила параллакса за курсором.
      const kinds = [
        ['disc', ['#ff6a3d', '#ff9d4a', '#ffd66e']], ['squircle', ['#f6aaee', '#b46cf0', '#7b3fd8']],
        ['layers', ['#7ee8ff', '#a096ff', '#4a7dff']], ['ring', ['#d9ff7a', '#7fd65a', '#1f9a4b']],
        ['arch', ['#ffb46b', '#ff78b6', '#b98cff']], ['drop', ['#ffffff', '#e8ecff', '#c9d2ff']],
        ['shield', ['#bae2ff', '#5a9dff', '#2c5fe0']], ['pill', ['#a0ffe6', '#3cc6b0', '#169a8f']],
      ];
      const spots = compact
        ? [[68, 6, 50], [80, 56, 44], [2, 66, 36]]
        : [[3, 12, 160], [83, 8, 140], [87, 55, 180], [2, 60, 130], [41, 79, 120], [57, 3, 96], [23, 38, 84], [69, 75, 104]];
      spots.forEach(([x, y, size], i) => {
        const [kind, colors] = kinds[i % kinds.length];
        const g = document.createElement('i');
        g.className = `particle glass-shape gs-${kind}`;
        g.style.left = x + '%';
        g.style.top = y + '%';
        g.style.width = g.style.height = (compact ? size : size * random(.88, 1.12)) + 'px';
        g.style.setProperty('--r', random(-22, 22).toFixed(1) + 'deg');
        g.style.setProperty('--tone', colors[1]);
        g.dataset.depth = (size / 120).toFixed(2);
        if (window.LiquidGlass) g.innerHTML = LiquidGlass.shape(kind, colors);
        const float = random(8, 14);
        g.style.animationDuration = float + 's';
        g.style.animationDelay = -random(0, float) + 's';
        scene.appendChild(g);
      });
    } else if (theme === 'ocean') {
      for (let i = 0; i < (compact ? 7 : 26); i++) {
        const b = document.createElement('i');
        b.className = 'particle bubble';
        const size = random(4, compact ? 12 : 22), rise = random(10, 26), wobble = random(2, 4);
        b.style.width = b.style.height = size + 'px';
        b.style.left = random(0, 100) + '%';
        b.style.animationDuration = `${rise}s, ${wobble}s`;
        b.style.animationDelay = `${-random(0, rise)}s, ${-random(0, wobble)}s`;
        scene.appendChild(b);
      }
    }
  }
  window.AgentMotion = { decorate };
})();
