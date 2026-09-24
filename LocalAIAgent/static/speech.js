/* Browser microphone fallback (phone browser / remote PC). On the desktop the native
   background listener is used instead: it works even when this window is hidden. */
(() => {
  'use strict';
  let recorder = null, stream = null, context = null, timer = null, chunks = [];
  const state = { recording: false };

  function release() {
    clearInterval(timer);
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (context) context.close().catch(() => {});
    stream = context = null;
  }

  async function start(onText, onStatus) {
    if (state.recording) return stop();
    if (!navigator.mediaDevices || !window.MediaRecorder) throw new Error('Запись звука недоступна в этом браузере.');
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find(m => MediaRecorder.isTypeSupported(m));
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
    chunks = [];
    recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: recorder.mimeType });
      release();
      state.recording = false;
      onStatus('transcribing');
      try {
        const form = new FormData();
        form.append('audio', blob, 'speech');
        form.append('language', Agent.settings.voice_language || 'auto');
        const result = await Agent.api('transcribe', { method: 'POST', body: form });
        onText(String(result.text || '').trim());
      } catch (e) { Agent.toast(e.message); }
      onStatus('idle');
    };
    context = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);
    const data = new Float32Array(analyser.fftSize);
    let heard = false, last = Date.now();
    const started = Date.now();
    recorder.start();
    state.recording = true;
    onStatus('recording');
    timer = setInterval(() => {
      analyser.getFloatTimeDomainData(data);
      const rms = Math.sqrt(data.reduce((s, x) => s + x * x, 0) / data.length);
      document.documentElement.style.setProperty('--level', Math.min(1, rms * 8).toFixed(3));
      if (rms > 0.015) { heard = true; last = Date.now(); }
      const silence = Agent.settings.silence_ms || 600;
      if ((heard && Date.now() - last > silence) || Date.now() - started > 30000) stop();
    }, 60);
  }

  function stop() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  window.BrowserRecorder = { start, stop, state };
})();
