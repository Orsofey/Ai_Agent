'use strict';
const $ = id => document.getElementById(id);

async function refresh() {
  const status = await chrome.runtime.sendMessage('status').catch(() => null);
  const online = !!(status && status.online);
  $('status').classList.toggle('online', online);
  $('status-text').textContent = online ? 'Подключено к ассистенту' : (status && status.error) || 'Нет связи с ассистентом';
}

(async () => {
  const { token = '', port = 5000 } = await chrome.storage.local.get(['token', 'port']);
  $('token').value = token;
  $('port').value = port;
  refresh();
  setInterval(refresh, 1500);
})();

$('save').onclick = async () => {
  await chrome.storage.local.set({ token: $('token').value.trim(), port: Number($('port').value) || 5000 });
  $('status-text').textContent = 'Подключаюсь…';
  setTimeout(refresh, 1200);
};
