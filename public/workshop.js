/* workshop session + polling */
(function (global) {
    const TOKEN_KEY = 'workshop-token';

    function token() {
        return localStorage.getItem(TOKEN_KEY) || '';
    }
    function setToken(value) {
        if (value) localStorage.setItem(TOKEN_KEY, value);
        else localStorage.removeItem(TOKEN_KEY);
    }
    function authHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        if (token()) headers.Authorization = 'Bearer ' + token();
        return headers;
    }
    async function request(method, path, body) {
        const res = await fetch(path, {
            method,
            headers: authHeaders(),
            body: body === undefined ? undefined : JSON.stringify(body)
        });
        let data = {};
        try { data = await res.json(); } catch (e) { data = {}; }
        if (res.status === 401 && !path.includes('/api/auth/login')) {
            setToken('');
            if (!document.documentElement.dataset.publicPage) location.href = 'login.html';
        }
        if (!res.ok) throw new Error((data && data.error) || 'درخواست ناموفق بود.');
        return data;
    }

    const Workshop = {
        token,
        setToken,
        request,
        async login(username, password, name, team) {
            const data = await request('POST', '/api/auth/login', { username, password, name, team });
            setToken(data.token);
            return data.user;
        },
        async logout() {
            try { await request('POST', '/api/auth/logout', {}); } catch (e) { /* ignore */ }
            setToken('');
            location.href = 'login.html';
        },
        async sync() { return request('GET', '/api/sync'); },
        async unlock(id) { return request('POST', '/api/unlock', { id }); },
        startPolling(onData, ms) {
            let version = -1;
            let timer = null;
            async function tick() {
                try {
                    const data = await Workshop.sync();
                    if (data.version !== version) {
                        version = data.version;
                        onData(data, true);
                    } else {
                        onData(data, false);
                    }
                } catch (e) { /* keep polling */ }
            }
            tick();
            timer = setInterval(tick, ms || 2000);
            return () => clearInterval(timer);
        }
    };

    global.Workshop = Workshop;

    if (!document.documentElement.dataset.publicPage && !token()) {
        location.href = 'login.html';
    }
})(window);
