/*
 * Shared front-end helpers for all pages.
 * Loaded synchronously in <head> so the theme is applied before first paint
 * and the helpers below are available to each page's inline scripts.
 */

/* ---- Theme ---- */
(function () {
    const html = document.documentElement;
    html.dataset.theme = localStorage.getItem('theme') || 'light';

    const icon = () => (html.dataset.theme === 'dark' ? '☀' : '☾');

    document.addEventListener('DOMContentLoaded', () => {
        const toggle = document.getElementById('theme-toggle');
        if (!toggle) return;
        toggle.textContent = icon();
        toggle.addEventListener('click', () => {
            html.dataset.theme = html.dataset.theme === 'dark' ? 'light' : 'dark';
            localStorage.setItem('theme', html.dataset.theme);
            toggle.textContent = icon();
        });
    });
})();

/* ---- Event delegation (CSP: no inline on* handlers) ----
 * The strict Content-Security-Policy forbids inline event handlers, so instead
 * of onclick="fn()" the markup carries data-action="fn" (+ data-* params) and a
 * single delegated listener dispatches to a registered handler. Delegation also
 * covers dynamically-inserted elements automatically. Register handlers with
 * registerActions({name: (el, event) => ...}); read params from el.dataset. */
const _actionRegistry = {};
function registerActions(map) { Object.assign(_actionRegistry, map); }

function _delegate(datasetKey, event) {
    const el = event.target.closest('[data-' + datasetKey + ']');
    if (!el) return;
    const camel = datasetKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const fn = _actionRegistry[el.dataset[camel]];
    if (fn) fn(el, event);
}

document.addEventListener('click', (e) => _delegate('action', e));
document.addEventListener('change', (e) => _delegate('action-change', e));
document.addEventListener('keyup', (e) => _delegate('action-keyup', e));
document.addEventListener('submit', (e) => _delegate('action-submit', e));

/* ---- i18n ----
 * window.T (current-language strings) and window.LANG are provided by the
 * synchronously loaded /i18n.js, so t() is safe from the first render. */
function t(key, vars) {
    let s = (window.T && window.T[key]) || key;
    if (vars) {
        for (const k in vars) {
            s = s.split('{' + k + '}').join(vars[k]);
        }
    }
    return s;
}

function toggleLang() {
    const next = (window.LANG === 'de') ? 'en' : 'de';
    document.cookie = 'lang=' + next + ';path=/;max-age=31536000;samesite=lax';
    location.reload();
}

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('lang-toggle');
    if (!btn) return;
    btn.textContent = (window.LANG === 'de') ? 'EN' : 'DE';
    btn.title = t('lang.switch_title');
    btn.addEventListener('click', toggleLang);
});

/* ---- HTML escaping ----
   Every user-controlled string (player/team/club names) that ends up in an
   innerHTML template literal MUST pass through escapeHtml first. */
function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ---- Player name / LK (Leistungsklasse) helpers ---- */
function parseLK(fullName) {
    if (!fullName) return { name: fullName || '', lk: null };
    const m = fullName.match(/^(.*?)\s*\(LK\s+([^)]+)\)$/);
    if (m) return { name: m[1].trim(), lk: m[2] };
    return { name: fullName, lk: null };
}

function stripLK(fullName) {
    return parseLK(fullName).name;
}

function formatPlayerNameHTML(fullName) {
    const p = parseLK(fullName);
    if (p.lk) return `<span class="player-name-text">${escapeHtml(p.name)}</span><span class="player-lk">LK ${escapeHtml(p.lk)}</span>`;
    return escapeHtml(p.name);
}

function formatNameForTable(fullName, fallback) {
    return formatPlayerNameHTML(fullName || fallback);
}

function formatDoublesForTable(p1, p2, fb1, fb2) {
    const a = parseLK(p1 || fb1);
    const b = parseLK(p2 || fb2);
    const name = `${a.name} / ${b.name}`;
    const lks = [a.lk, b.lk].filter(Boolean);
    if (lks.length) return `<span class="player-name-text">${escapeHtml(name)}</span><span class="player-lk">LK ${escapeHtml(lks.join(' / '))}</span>`;
    return escapeHtml(name);
}

/* ---- Scorer authorization ---- */
function getScorerToken() {
    return sessionStorage.getItem('scorer_token') || (window.SCORER_TOKEN || '');
}

function getAuthHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    const token = getScorerToken();
    if (token) headers['X-Scorer-Token'] = token;
    return headers;
}

/* ---- Time formatting ---- */
function formatElapsed(totalSeconds) {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
    return `${m}m ${String(s).padStart(2, '0')}s`;
}

function parseUtc(str) {
    if (!str) return null;
    const utcStr = str.endsWith('Z') || str.includes('+') ? str : str + 'Z';
    const ms = new Date(utcStr).getTime();
    return isNaN(ms) ? null : ms;
}

/* ---- UX helpers ---- */
function vibrate(pattern) {
    if ('vibrate' in navigator) navigator.vibrate(pattern);
}

let _toastTimer = null;
function showToast(message, type = 'info') {
    let toast = document.getElementById('app-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'app-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = `toast toast-${type} show`;
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}

async function copyToClipboard(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (e) {
        /* fall through to legacy path */
    }
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        return true;
    } catch (e) {
        return false;
    }
}
