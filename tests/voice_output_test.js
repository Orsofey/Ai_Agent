/* Run with node tests/voice_output_test.js. No browser or audio hardware required. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require('node:path').join(__dirname, '../static/voice-output.js'), 'utf8');

function fixture(api, playError) {
  const spoken = [], players = [], revoked = [];
  const context = {
    Agent: { settings: { tts_enabled: true, tts_rate: 100 }, api },
    AbortController, Uint8Array, Blob,
    atob: s => Buffer.from(s, 'base64').toString('binary'),
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url) },
    Audio: class {
      constructor() { players.push(this); }
      async play() { if (playError) throw playError; }
      pause() { this.paused = true; }
      removeAttribute() {}
      load() {}
    },
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
    speechSynthesis: { cancel() {}, getVoices: () => [], speak: utterance => spoken.push(utterance) },
  };
  context.window = context;
  vm.runInNewContext(code, context);
  return { voice: context.AgentVoice, players, spoken, revoked };
}

(async () => {
  const data = { audio: Buffer.from('RIFF').toString('base64'), mime: 'audio/wav' };
  const normal = fixture(async path => { assert.equal(path, 'tts/phone'); return data; });
  await normal.voice.speak('Да, сэр.');
  assert.equal(normal.players.length, 1);
  assert.equal(normal.spoken.length, 0);
  normal.voice.stop();
  assert.equal(normal.players[0].paused, true);
  assert.equal(normal.revoked.length, 1);

  let resolve;
  const cancelled = fixture(() => new Promise(done => { resolve = done; }));
  const pending = cancelled.voice.speak('Старая фраза');
  cancelled.voice.stop();
  resolve(data);
  await pending;
  assert.equal(cancelled.players.length, 0);
  assert.equal(cancelled.spoken.length, 0);

  const fallback = fixture(async () => { throw new Error('offline'); });
  await fallback.voice.speak('Ответ');
  assert.equal(fallback.spoken.length, 1);

  const blocked = fixture(async () => data, Object.assign(new Error('autoplay'), { name: 'NotAllowedError' }));
  await blocked.voice.speak('Ответ');
  assert.equal(blocked.spoken.length, 0);
  assert.equal(blocked.revoked.length, 1);
  console.log('Voice output: 4 checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
