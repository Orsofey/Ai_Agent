document.addEventListener('DOMContentLoaded', () => {
    const loginTab = document.querySelector('[data-tab="login"]');
    const registerTab = document.querySelector('[data-tab="register"]');
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const message = (el, text, ok) => { el.textContent = text; el.className = `form-message ${ok ? 'success' : 'error'}`; };

    loginTab.addEventListener('click', () => { loginTab.classList.add('active'); registerTab.classList.remove('active'); loginForm.classList.add('active'); registerForm.classList.remove('active'); });
    registerTab.addEventListener('click', () => { registerTab.classList.add('active'); loginTab.classList.remove('active'); registerForm.classList.add('active'); loginForm.classList.remove('active'); });

    loginForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const output = document.getElementById('login-message');
        try {
            const response = await fetch('/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username: document.getElementById('login-username').value, password: document.getElementById('login-password').value}) });
            const data = await response.json();
            message(output, data.message, data.success);
            if (data.success) setTimeout(() => { location.href = '/'; }, 350);
        } catch (_) { message(output, 'Сервер недоступен.', false); }
    });

    registerForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const output = document.getElementById('register-message');
        const username = document.getElementById('register-username').value;
        const password = document.getElementById('register-password').value;
        if (password !== document.getElementById('register-password-confirm').value) { message(output, 'Пароли не совпадают.', false); return; }
        try {
            const response = await fetch('/register', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username, password, email: document.getElementById('register-email').value}) });
            const data = await response.json();
            message(output, data.message, data.success);
            if (data.success) setTimeout(() => { loginTab.click(); document.getElementById('login-username').value = username; }, 700);
        } catch (_) { message(output, 'Сервер недоступен.', false); }
    });

    document.getElementById('guest-btn').addEventListener('click', async () => {
        const output = document.getElementById('login-message');
        try {
            const response = await fetch('/guest', {method: 'POST'});
            const data = await response.json();
            message(output, data.message, data.success);
            if (data.success) setTimeout(() => { location.href = '/'; }, 250);
        } catch (_) { message(output, 'Сервер недоступен.', false); }
    });
});
