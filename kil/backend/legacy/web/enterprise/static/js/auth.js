/**
 * SanoCare Enterprise Authentication Client
 * ===========================================
 * Standalone JWT auth - no external dependencies.
 * Handles login, token refresh, session management.
 */

const AUTH_API = '/api/v1/auth';

// Storage keys
const TOKEN_KEY = 'sc_access_token';
const REFRESH_KEY = 'sc_refresh_token';
const USER_KEY = 'sc_user';

let _currentUser = null;

/**
 * Check if user is authenticated (has valid token)
 */
function isAuthenticated() {
    return !!localStorage.getItem(TOKEN_KEY);
}

/**
 * Get stored access token
 */
function getAccessToken() {
    return localStorage.getItem(TOKEN_KEY);
}

/**
 * Get current user from cache
 */
function getCachedUser() {
    if (_currentUser) return _currentUser;
    const stored = localStorage.getItem(USER_KEY);
    if (stored) {
        try {
            _currentUser = JSON.parse(stored);
            return _currentUser;
        } catch (e) { /* ignore */ }
    }
    return null;
}

/**
 * Sign in with ID Pekerja/email and password
 */
async function signIn(login, password) {
    const res = await fetch(`${AUTH_API}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password })
    });

    const data = await res.json();

    if (!res.ok) {
        throw new Error(data.error || 'Login failed');
    }

    // Store tokens
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    _currentUser = data.user;

    return data;
}

/**
 * Sign out - revoke tokens and clear storage
 */
async function signOut() {
    const refreshToken = localStorage.getItem(REFRESH_KEY);

    try {
        await fetch(`${AUTH_API}/logout`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken })
        });
    } catch (e) {
        // Best-effort logout
    }

    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
    _currentUser = null;

    window.location.href = '/enterprise/login';
}

/**
 * Refresh the access token using the refresh token
 */
async function refreshAccessToken() {
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    if (!refreshToken) return false;

    try {
        const res = await fetch(`${AUTH_API}/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken })
        });

        if (!res.ok) {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(REFRESH_KEY);
            localStorage.removeItem(USER_KEY);
            return false;
        }

        const data = await res.json();
        localStorage.setItem(TOKEN_KEY, data.access_token);
        localStorage.setItem(REFRESH_KEY, data.refresh_token);
        localStorage.setItem(USER_KEY, JSON.stringify(data.user));
        _currentUser = data.user;
        return true;
    } catch (e) {
        return false;
    }
}

/**
 * Get current user profile from server
 */
async function getCurrentUser() {
    const token = getAccessToken();
    if (!token) return null;

    try {
        const res = await fetch(`${AUTH_API}/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (res.status === 401) {
            const refreshed = await refreshAccessToken();
            if (refreshed) {
                const retryRes = await fetch(`${AUTH_API}/me`, {
                    headers: { 'Authorization': `Bearer ${getAccessToken()}` }
                });
                if (retryRes.ok) {
                    const data = await retryRes.json();
                    _currentUser = data.user;
                    return data.user;
                }
            }
            return null;
        }

        if (res.ok) {
            const data = await res.json();
            _currentUser = data.user;
            return data.user;
        }
        return null;
    } catch (e) {
        return getCachedUser();
    }
}

/**
 * Make authenticated API call
 * Automatically adds Authorization header and handles token refresh.
 */
async function authenticatedFetch(url, options = {}) {
    const token = getAccessToken();

    // No token at all → redirect to login immediately
    if (!token) {
        window.location.href = '/enterprise/login';
        throw new Error('Not authenticated');
    }

    const headers = {
        ...options.headers,
        'Authorization': `Bearer ${token}`
    };

    // Only set Content-Type for non-FormData bodies (FormData needs browser-set multipart boundary)
    if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    }

    let response = await fetch(url, { ...options, headers });

    // Handle 401 - try token refresh
    if (response.status === 401) {
        const refreshed = await refreshAccessToken();

        if (refreshed) {
            headers['Authorization'] = `Bearer ${getAccessToken()}`;
            response = await fetch(url, { ...options, headers });
        } else {
            window.location.href = '/enterprise/login';
            throw new Error('Session expired');
        }
    }

    return response;
}

/**
 * Display user info in header
 */
function displayUserInfo(user) {
    const el = document.getElementById('user-info');
    if (!el || !user) return;

    const roleBadge = {
        admin: 'bg-red-100 text-red-700',
        koordinator: 'bg-purple-100 text-purple-700',
        supervisor: 'bg-blue-100 text-blue-700',
        viewer: 'bg-slate-100 text-slate-600',
        technician: 'bg-emerald-100 text-emerald-700',
    };

    const initial = (user.full_name || user.email || '?').charAt(0).toUpperCase();
    const photoId = user.p_user_id;
    const avatarImg = photoId
        ? `<img src="/enterprise/static/img/staff/${photoId}.jpg" class="w-8 h-8 rounded-full object-cover" onerror="this.outerHTML='<div class=\\'w-8 h-8 rounded-full bg-[#F97316] flex items-center justify-center text-white text-xs font-bold\\'>${initial}</div>'" alt="${user.full_name || ''}">`
        : `<div class="w-8 h-8 rounded-full bg-[#F97316] flex items-center justify-center text-white text-xs font-bold">${initial}</div>`;

    el.innerHTML = `
        <div class="flex items-center gap-3">
            ${avatarImg}
            <div class="hidden sm:block">
                <p class="text-xs font-medium text-slate-700 leading-tight">${user.full_name || user.email}</p>
                <span class="text-[10px] font-bold px-1.5 py-0.5 rounded ${roleBadge[user.role] || roleBadge.viewer}">${user.role}</span>
            </div>
            <button onclick="window.SanoCareAuth.signOut()" class="p-1.5 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-500 transition-colors" title="Logout">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
                </svg>
            </button>
        </div>
    `;
}

/**
 * Initialize auth state on page load.
 * Redirects to /enterprise/login if not authenticated.
 */
async function initAuth() {
    if (!isAuthenticated()) {
        window.location.href = '/enterprise/login';
        return;
    }

    const user = getCachedUser();
    if (user) {
        displayUserInfo(user);
    }

    // Verify token is still valid with server
    const serverUser = await getCurrentUser();
    if (serverUser) {
        displayUserInfo(serverUser);
    } else {
        // Token invalid/expired and refresh failed
        window.location.href = '/enterprise/login';
    }
}

// Export
window.SanoCareAuth = {
    signIn,
    signOut,
    getCurrentUser,
    getCachedUser,
    authenticatedFetch,
    initAuth,
    isAuthenticated,
    getAccessToken,
    refreshAccessToken,
    get isAvailable() { return true; }
};

// Auto-initialize on page load (except login page)
if (!window.location.pathname.includes('/login')) {
    document.addEventListener('DOMContentLoaded', () => {
        initAuth();
    });
}
