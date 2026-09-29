/* Living backgrounds: petals for Sakura, bubbles for Ocean, cobalt petals for Gzhel, embers for Slavic. */
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
