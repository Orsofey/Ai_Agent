let recognition = null;
let recording = false;
let voiceSession = false;
let voiceSendTimer = null;
let voiceTranscript = '';
let wakeMode = false;
let wakeWordHeard = false;
let wakeRestartTimer = null;
let wakePausedUntil = 0;
let wakeCommandTimer = null;
let WAKE_VARIANTS = [];
let recognitionTimeout = null;
let applications = [];

const $ = (id) => document.getElementById(id);

/* ============ ТЕМЫ ============ */
function applyTheme(theme) {
    const valid = ['light', 'dark', 'ocean', 'forest', 'sunset', 'cyberpunk', 'minimal'];
    const chosen = valid.includes(theme) ? theme : 'light';
    const root = document.documentElement;
    valid.forEach(function (t) { root.classList.remove('theme-' + t); });
    root.classList.add('theme-' + chosen);
    if (document.body) document.body.classList.toggle('dark', chosen === 'dark');
    try { localStorage.setItem('agent-theme', chosen); } catch (e) {}
}

function setupThemePreview() {
    const sel = $('setting-theme');
    if (!sel) return;
    sel.addEventListener('change', function () { applyTheme(this.value); });
}

/* ============ ИНИЦИАЛИЗАЦИЯ ============ */
window.addEventListener('DOMContentLoaded', function () {
    var saved = 'light';
    try { saved = localStorage.getItem('agent-theme') || 'light'; } catch (e) {}
    applyTheme(saved);

    setupNavigation();
    setupChat();
    setupVoice();
    setupWakeWord();
    setupHistory();
    setupSettings();
    setupThemePreview();
    setupApplications();
    setupPhoneUrlCopy();
    setupLogout();
    loadChatHistory();
    loadSettings();
});

/* ============ НАВИГАЦИЯ ============ */
function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(function (item) {
        item.addEventListener('click', function () {
            document.querySelectorAll('.nav-item').forEach(function (el) { el.classList.remove('active'); });
            document.querySelectorAll('.page').forEach(function (el) { el.classList.remove('active'); });
            item.classList.add('active');
            var page = $('page-' + item.dataset.page);
            if (page) page.classList.add('active');
            var sb = $('sidebar');
            if (sb) sb.classList.remove('open');
            if (item.dataset.page === 'history') loadHistory();
            if (item.dataset.page === 'apps') loadApplications();
        });
    });
    var mm = $('mobile-menu');
    if (mm) mm.addEventListener('click', function () { $('sidebar').classList.toggle('open'); });
}

/* ============ ЧАТ ============ */
function setupChat() {
    $('send-btn').addEventListener('click', function () { sendMessage(); });
    $('chat-input').addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }
    });
    $('chat-input').addEventListener('input', resizeInput);
    document.querySelectorAll('.quick-command').forEach(function (button) {
        button.addEventListener('click', function () {
            $('chat-input').value = button.dataset.command;
            $('chat-input').focus();
            resizeInput();
        });
    });
    $('clear-chat-btn').addEventListener('click', async function () {
        if (!confirm('Очистить историю команд?')) return;
        var data = await (await fetch('/clear_history', { method: 'POST' })).json();
        if (data.success) {
            $('chat-messages').innerHTML = '<div class="welcome-message"><h2>История очищена</h2><p>Можно начать новый диалог.</p></div>';
        }
    });
}

function resizeInput() {
    var field = $('chat-input');
    field.style.height = '88px';
    field.style.height = Math.min(field.scrollHeight, 240) + 'px';
}

async function sendMessage(messageOverride) {
    var field = $('chat-input');
    var message = String(messageOverride == null ? field.value : messageOverride).trim();
    if (!message) return false;
    addMessage(message, 'user');
    field.value = '';
    field.style.height = '88px';
    var loading = addMessage('Выполняю команду…', 'agent');
    try {
        var response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });
        var data = await response.json();
        loading.remove();
        addMessage(data.success ? data.response : ('Ошибка: ' + data.message), 'agent');
        return Boolean(data.success);
    } catch (error) {
        loading.remove();
        addMessage('Ошибка соединения: ' + error.message, 'agent');
        return false;
    }
}

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, function (char) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char];
    });
}

function addMessage(text, sender) {
    var box = $('chat-messages');
    var welcome = box.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    var item = document.createElement('div');
    item.className = 'message message-' + sender;
    item.innerHTML = '<div class="message-bubble">' + escapeHtml(text) + '</div><div class="message-time">' +
        new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) + '</div>';
    box.appendChild(item);
    box.scrollTop = box.scrollHeight;
    return item;
}

async function loadChatHistory() {
    try {
        var data = await (await fetch('/history')).json();
        if (!data.success || !data.history.length) return;
        $('chat-messages').innerHTML = '';
        data.history.forEach(function (item) { addMessage(item.user, 'user'); addMessage(item.agent, 'agent'); });
    } catch (e) {}
}

/* ============ ГОЛОС ============ */
function setupVoice() {
    var button = $('voice-chat-btn');
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        button.title = 'Распознавание речи не поддерживается';
        button.disabled = true;
        $('voice-status').textContent = 'Голосовой ввод недоступен в этом браузере';
        var wb = $('wake-btn');
        if (wb) wb.disabled = true;
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.lang = 'ru-RU';

    recognition.onstart = function () {
        recording = true;
        voiceSession = true;
        voiceTranscript = '';
        if (voiceSendTimer) { clearTimeout(voiceSendTimer); voiceSendTimer = null; }
        if (recognitionTimeout) { clearTimeout(recognitionTimeout); recognitionTimeout = null; }
        button.classList.add('recording');
        button.textContent = '⏹';
        recognitionTimeout = setTimeout(function () { try { recognition.abort(); } catch (e) {} }, 60000);
        if (!wakeMode) $('voice-status').textContent = 'Слушаю…';
        else $('voice-status').textContent = '🎤 Жду "' + ($('setting-wake-word').value || 'Орсофей') + '"...';
    };

    recognition.onresult = function (event) {
        if (recognitionTimeout) { clearTimeout(recognitionTimeout); recognitionTimeout = null; }
        var interim = '';
        var finalText = voiceTranscript;
        for (var i = event.resultIndex; i < event.results.length; i++) {
            var t = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalText += t; else interim += t;
        }
        voiceTranscript = finalText;
        var displayText = (finalText + interim).trim();
        if (!displayText) return;

        if (wakeMode) {
            $('voice-status').textContent = '📍 Слышу: "' + displayText + '"';
            if (!wakeWordHeard) {
                var wakeFound = findWakeWord(displayText);
                if (wakeFound >= 0) {
                    wakeWordHeard = true;
                    var tail = displayText.slice(wakeFound).replace(/^[\s,.:;!?—-]+/, '').trim();
                    if (tail) {
                        $('voice-status').textContent = '✓ Команда: "' + tail + '"';
                        executeWakeCommand(tail);
                    } else {
                        $('voice-status').textContent = '✓ Готов! Скажите команду…';
                        if (wakeCommandTimer) clearTimeout(wakeCommandTimer);
                        wakeCommandTimer = setTimeout(function () {
                            wakeCommandTimer = null;
                            wakeWordHeard = false;
                            $('voice-status').textContent = '⏱ Ожидание тайм-аута';
                        }, 5000);
                    }
                }
            } else if (finalText.trim()) {
                executeWakeCommand(finalText);
            }
            return;
        }

        $('chat-input').value = displayText;
        resizeInput();
        $('voice-status').textContent = 'Распознано: ' + displayText;
    };

    recognition.onerror = function (event) {
        if (recognitionTimeout) { clearTimeout(recognitionTimeout); recognitionTimeout = null; }
        recording = false;
        resetVoice();
        var msg = 'Неизвестная ошибка';
        if (event.error === 'network') msg = 'Ошибка сети';
        else if (event.error === 'aborted') msg = 'Распознавание отменено';
        else if (event.error === 'no-speech') msg = 'Речь не услышана';
        else if (event.error === 'audio-capture') msg = 'Микрофон не работает';
        else if (event.error === 'not-allowed') msg = 'Доступ к микрофону запрещён';
        else if (event.error === 'service-not-allowed') msg = 'Сервис недоступен';

        if (wakeMode) {
            if (event.error === 'no-speech' || event.error === 'aborted') { scheduleWakeRestart(800); return; }
            $('voice-status').textContent = '⚠ ' + msg;
            scheduleWakeRestart(2000);
        } else {
            $('voice-status').textContent = '⚠ ' + msg;
        }
    };

    recognition.onend = function () {
        if (recognitionTimeout) { clearTimeout(recognitionTimeout); recognitionTimeout = null; }
        recording = false;
        resetVoice();
        if (wakeMode) { scheduleWakeRestart(500); return; }
        if (!voiceSession) return;
        voiceSession = false;
        var transcript = (voiceTranscript || $('chat-input').value || '').trim();
        if (!transcript) { $('voice-status').textContent = 'Готов'; return; }
        $('chat-input').value = transcript;
        $('voice-status').textContent = 'Отправляю…';
        voiceSendTimer = setTimeout(async function () {
            voiceSendTimer = null;
            await sendMessage(transcript);
            $('voice-status').textContent = 'Готов';
        }, 800);
    };

    button.addEventListener('click', function () {
        if (wakeMode) return;
        if (recording) { try { recognition.abort(); } catch (e) {} return; }
        try {
            recognition.lang = $('setting-voice-language').value || 'ru-RU';
            voiceTranscript = '';
            recognition.start();
        } catch (error) {
            $('voice-status').textContent = 'Ошибка: ' + error.message;
        }
    });
}

function resetVoice() {
    var button = $('voice-chat-btn');
    button.classList.remove('recording');
    button.textContent = '🎤';
}

/* ============ WAKE WORD ============ */
function setupWakeWord() {
    var wakeButton = $('wake-btn');
    if (!wakeButton) return;
    wakeButton.addEventListener('click', function () {
        if (wakeMode) stopWakeMode(); else startWakeMode();
    });
}

function startWakeMode() {
    if (!recognition) return;
    wakeMode = true;
    wakeWordHeard = false;
    updateWakeUi();
    var wakeName = $('setting-wake-word').value || 'Орсофей';
    $('voice-status').textContent = '🔴 Режим "' + wakeName + '" включён!';
    startWakeCycle();
}

function stopWakeMode() {
    wakeMode = false;
    wakeWordHeard = false;
    if (wakeRestartTimer) { clearTimeout(wakeRestartTimer); wakeRestartTimer = null; }
    if (wakeCommandTimer) { clearTimeout(wakeCommandTimer); wakeCommandTimer = null; }
    updateWakeUi();
    try { recognition.abort(); } catch (e) {}
    $('voice-status').textContent = '⭕ Режим выключен';
}

function updateWakeUi() {
    var wakeButton = $('wake-btn');
    if (!wakeButton) return;
    var wakeName = ($('setting-wake-word') && $('setting-wake-word').value) || 'Орсофей';
    wakeButton.classList.toggle('active', wakeMode);
    wakeButton.textContent = wakeMode ? ('🔴 ' + wakeName + ': вкл') : ('🎙 ' + wakeName + ': выкл');
}

function scheduleWakeRestart(delay) {
    if (!wakeMode) return;
    if (wakeRestartTimer) clearTimeout(wakeRestartTimer);
    wakeRestartTimer = setTimeout(function () {
        wakeRestartTimer = null;
        if (wakeMode) startWakeCycle();
    }, delay);
}

function startWakeCycle() {
    if (!wakeMode) return;
    if (Date.now() < wakePausedUntil) { scheduleWakeRestart(500); return; }
    if (recording) return;
    try {
        voiceTranscript = '';
        wakeWordHeard = false;
        recognition.lang = $('setting-voice-language').value || 'ru-RU';
        recognition.start();
    } catch (e) {
        scheduleWakeRestart(1000);
    }
}

function findWakeWord(text) {
    var lower = String(text || '').toLowerCase().trim();
    for (var i = 0; i < WAKE_VARIANTS.length; i++) {
        if (lower.indexOf(WAKE_VARIANTS[i]) >= 0) {
            return lower.indexOf(WAKE_VARIANTS[i]) + WAKE_VARIANTS[i].length;
        }
    }
    return -1;
}

function executeWakeCommand(command) {
    if (!command) return;
    if (wakeCommandTimer) { clearTimeout(wakeCommandTimer); wakeCommandTimer = null; }
    wakeWordHeard = false;
    wakePausedUntil = Date.now() + 1500;
    try { recognition.abort(); } catch (e) {}
    sendMessage(command);
}

function updateWakeVariants(name) {
    var base = String(name || 'Орсофей').toLowerCase().trim();
    WAKE_VARIANTS = [base];
    if (base.length > 2) {
        WAKE_VARIANTS.push(base.slice(0, -1));
        WAKE_VARIANTS.push(base.replace(/й$/, 'и'));
    }
}

/* ============ ИСТОРИЯ ============ */
function setupHistory() {
    var btn = $('refresh-history-btn');
    if (btn) btn.addEventListener('click', loadHistory);
}

async function loadHistory() {
    var box = $('history-container');
    box.innerHTML = '<p class="muted">Загрузка…</p>';
    try {
        var data = await (await fetch('/history')).json();
        if (!data.success || !data.history.length) { box.innerHTML = '<p class="muted">История пуста.</p>'; return; }
        box.innerHTML = '';
        data.history.slice().reverse().forEach(function (item) {
            var row = document.createElement('div');
            row.className = 'history-item';
            row.innerHTML = '<div class="history-command">Команда: ' + escapeHtml(item.user) + '</div>' +
                '<div class="history-response">' + escapeHtml(item.agent) + '</div>' +
                '<div class="history-time">' + escapeHtml(new Date(item.timestamp).toLocaleString('ru-RU')) + '</div>';
            box.appendChild(row);
        });
    } catch (e) { box.innerHTML = '<p class="muted">Не удалось загрузить историю.</p>'; }
}

/* ============ НАСТРОЙКИ ============ */
function setupSettings() {
    $('save-settings-btn').addEventListener('click', saveSettings);
}

async function loadSettings() {
    try {
        var data = await (await fetch('/settings')).json();
        if (!data.success) return;
        $('setting-voice-enabled').checked = Boolean(data.settings.voice_enabled);
        $('setting-voice-language').value = data.settings.voice_language;
        $('setting-theme').value = data.settings.theme || 'light';
        $('setting-notifications').checked = Boolean(data.settings.notifications);
        $('setting-wake-word').value = data.settings.wake_word || 'Орсофей';
        if ($('setting-autostart')) $('setting-autostart').checked = Boolean(data.settings.autostart);
        updateWakeVariants(data.settings.wake_word || 'Орсофей');
        updateWakeUi();
        if ($('setting-microphone')) {
            loadMicrophones();
            if (data.settings.microphone) $('setting-microphone').value = data.settings.microphone;
        }
        applyTheme(data.settings.theme || 'light');
    } catch (e) {}
}

async function loadMicrophones() {
    try {
        var devices = await navigator.mediaDevices.enumerateDevices();
        var mics = devices.filter(function (d) { return d.kind === 'audioinput'; });
        var select = $('setting-microphone');
        if (!select) return;
        select.innerHTML = '<option value="">По умолчанию</option>';
        mics.forEach(function (mic, idx) {
            var opt = document.createElement('option');
            opt.value = mic.deviceId;
            opt.textContent = mic.label || ('Микрофон ' + (idx + 1));
            select.appendChild(opt);
        });
    } catch (e) {}
}

async function saveSettings() {
    var settings = {
        voice_enabled: $('setting-voice-enabled').checked,
        voice_language: $('setting-voice-language').value,
        theme: $('setting-theme').value || 'light',
        notifications: $('setting-notifications').checked,
        wake_word: $('setting-wake-word').value || 'Орсофей',
        microphone: $('setting-microphone') ? $('setting-microphone').value : '',
        autostart: $('setting-autostart') ? $('setting-autostart').checked : false
    };
    applyTheme(settings.theme);
    updateWakeVariants(settings.wake_word);
    updateWakeUi();
    var out = $('settings-message');
    try {
        var data = await (await fetch('/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        })).json();
        out.textContent = data.message || 'Готово';
        out.className = 'form-message ' + (data.success ? 'success' : 'error');
    } catch (e) {
        out.textContent = 'Настройки применены локально';
        out.className = 'form-message success';
    }
}

/* ============ ПРИЛОЖЕНИЯ ============ */
function setupApplications() {
    $('refresh-apps-btn').addEventListener('click', loadApplications);
    $('apps-filter').addEventListener('input', renderApplications);
}

async function loadApplications() {
    $('apps-grid').innerHTML = '<p class="muted">Сканирование меню Пуск…</p>';
    try {
        var data = await (await fetch('/apps')).json();
        if (!data.success) { $('apps-grid').innerHTML = '<p class="muted">Не удалось получить список.</p>'; return; }
        applications = data.applications || [];
        renderApplications();
    } catch (e) { $('apps-grid').innerHTML = '<p class="muted">Не удалось получить список.</p>'; }
}

function renderApplications() {
    var query = ($('apps-filter').value || '').toLowerCase().trim();
    var grid = $('apps-grid');
    var list = applications.filter(function (item) { return !query || item.name.toLowerCase().indexOf(query) >= 0; });
    if (!list.length) { grid.innerHTML = '<p class="muted">Ничего не найдено.</p>'; return; }
    grid.innerHTML = '';
    list.slice(0, 300).forEach(function (item) {
        var card = document.createElement('button');
        card.type = 'button';
        card.className = 'app-card';
        card.innerHTML = '<span class="app-card-name">' + escapeHtml(item.name) + '</span>';
        card.addEventListener('click', async function () {
            var data = await (await fetch('/apps/launch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: item.name })
            })).json();
            addMessage('Открыть: ' + item.name, 'user');
            addMessage(data.response || data.message || 'Готово', 'agent');
            document.querySelectorAll('.nav-item').forEach(function (el) { el.classList.remove('active'); });
            document.querySelectorAll('.page').forEach(function (el) { el.classList.remove('active'); });
            document.querySelector('.nav-item[data-page="chat"]').classList.add('active');
            $('page-chat').classList.add('active');
        });
        grid.appendChild(card);
    });
}

/* ============ КОПИРОВАНИЕ АДРЕСА ДЛЯ ТЕЛЕФОНА ============ */
function setupPhoneUrlCopy() {
    var btn = $('copy-phone-url');
    if (!btn) return;
    btn.addEventListener('click', async function () {
        var urlEl = $('phone-url');
        var msg = $('phone-url-message');
        var url = urlEl ? urlEl.textContent.trim() : '';
        if (!url) {
            if (msg) { msg.textContent = 'Адрес не найден'; msg.className = 'form-message error'; }
            return;
        }
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(url);
            } else {
                var ta = document.createElement('textarea');
                ta.value = url;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            if (msg) { msg.textContent = 'Адрес скопирован: ' + url; msg.className = 'form-message success'; }
        } catch (e) {
            if (msg) { msg.textContent = 'Скопируйте вручную: ' + url; msg.className = 'form-message'; }
        }
    });
}

/* ============ ВЫХОД ============ */
function setupLogout() {
    $('logout-btn').addEventListener('click', async function () {
        await fetch('/logout', { method: 'POST' });
        location.href = '/';
    });
}
