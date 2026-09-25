/* Living backgrounds: petals for Sakura, bubbles for Ocean. */
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
