/* Browser speech output — only when the PC did not speak the answer itself
   (for example, the page is opened from a phone or another computer). */
(() => {
  'use strict';
  const clean = text => String(text).replace(/https?:\/\/\S+/g, 'ссылку').replace(/[*_#`>|]+/g, ' ')
    .replace(/\s{2,}/g, ' ').trim().slice(0, 600);
  window.AgentVoice = {
    speak(text) {
      if (!('speechSynthesis' in window) || !(window.Agent && Agent.settings.tts_enabled)) return;
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(clean(text));
      const latin = (text.match(/[a-z]/gi) || []).length, cyr = (text.match(/[а-яё]/gi) || []).length;
      u.lang = latin > cyr * 2 ? 'en-US' : 'ru-RU';
      const voice = speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith(u.lang.slice(0, 2)));
      if (voice) u.voice = voice;
      u.rate = (Agent.settings.tts_rate || 100) / 100;
      speechSynthesis.speak(u);
    },
    stop() { if ('speechSynthesis' in window) speechSynthesis.cancel(); },
  };
})();
