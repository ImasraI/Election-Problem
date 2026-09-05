/* workshop session + polling */
(function (global) {
    const TOKEN_KEY = 'workshop-token';
    // How often the classroom asks the server for updates (milliseconds).
    // 5000 = every 5 seconds. Raise this to slow sync; lower it to refresh faster.
    const POLL_MS = 5000;

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
            if (!document.documentElement.dataset.publicPage) location.href = 'index.html';
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
            location.href = 'index.html';
        },
        async sync() { return request('GET', '/api/sync'); },
        async unlock(id) { return request('POST', '/api/unlock', { id }); },
        async hide(id) { return request('POST', '/api/hide', { id }); },
        startPolling(onData, ms) {
            const interval = ms || POLL_MS;
            const root = (function () {
                try { return window.top || window; } catch (e) { return window; }
            })();
            if (!root.__workshopPoll) {
                root.__workshopPoll = {
                    subscribers: [],
                    lastData: null,
                    version: -1,
                    timer: null,
                    inFlight: false
                };
            }
            const poll = root.__workshopPoll;
            poll.subscribers.push(onData);
            if (poll.lastData) {
                try { onData(poll.lastData, false); } catch (e) { /* ignore */ }
            }
            async function tick() {
                if (poll.inFlight) return;
                poll.inFlight = true;
                try {
                    const data = await Workshop.sync();
                    const changed = data.version !== poll.version;
                    if (changed) poll.version = data.version;
                    poll.lastData = data;
                    poll.subscribers.slice().forEach(fn => {
                        try { fn(data, changed); } catch (e) { /* ignore dead panels */ }
                    });
                } catch (e) { /* keep polling */ }
                poll.inFlight = false;
            }
            if (!poll.timer) {
                tick();
                poll.timer = setInterval(tick, interval);
            }
            function stop() {
                poll.subscribers = poll.subscribers.filter(fn => fn !== onData);
            }
            window.addEventListener('pagehide', stop, { once: true });
            return stop;
        }
    };

    global.Workshop = Workshop;

    if (!document.documentElement.dataset.publicPage && !token()) {
        location.href = 'index.html';
    }
})(window);
