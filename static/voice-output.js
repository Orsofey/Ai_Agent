/* Browser speech output — only when the PC did not speak the answer itself
   (for example, the page is opened from a phone or another computer). */
(() => {
  'use strict';
  let generation = 0, controller = null, audio = null, audioUrl = null;
  function stop() {
    generation += 1;
    if (controller) controller.abort();
    controller = null;
    if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
    audio = null;
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = null;
    if ('speechSynthesis' in window) speechSynthesis.cancel();
  }
  const clean = text => String(text).replace(/https?:\/\/\S+/g, 'ссылку').replace(/[*_#`>|]+/g, ' ')
    .replace(/\s{2,}/g, ' ').trim().slice(0, 600);
  window.AgentVoice = {
    async speak(text) {
      if (!(window.Agent && Agent.settings.tts_enabled)) return;
      stop();
      const current = generation;
      controller = new AbortController();
      try {
        const data = await Agent.api('tts/phone', { method: 'POST', signal: controller.signal,
          body: JSON.stringify({ text: clean(text) }) });
        if (current !== generation) return;
        const bytes = Uint8Array.from(atob(data.audio), ch => ch.charCodeAt(0));
        audioUrl = URL.createObjectURL(new Blob([bytes], { type: data.mime || 'audio/wav' }));
        audio = new Audio(audioUrl);
        audio.onended = () => { if (current === generation) stop(); };
        await audio.play();
        return;
      } catch (error) {
        if (current !== generation || error.name === 'AbortError') return;
        // If browser autoplay is blocked, do not speak again through another engine.
        if (error.name === 'NotAllowedError') { stop(); return; }
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        audioUrl = null;
        audio = null;
      }
      if (!('speechSynthesis' in window)) return;
      const u = new SpeechSynthesisUtterance(clean(text));
      const latin = (text.match(/[a-z]/gi) || []).length, cyr = (text.match(/[а-яё]/gi) || []).length;
      u.lang = latin > cyr * 2 ? 'en-US' : 'ru-RU';
      const voice = speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith(u.lang.slice(0, 2)));
      if (voice) u.voice = voice;
      u.rate = (Agent.settings.tts_rate || 100) / 100;
      speechSynthesis.speak(u);
    },
    stop,
  };
})();

