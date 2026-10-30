/**
 * The app uses the URL hash for the few "special" pages that need no server
 * route: share links, the password-reset landing page and the browser-button
 * import. (A hash also works on any static host without extra config.)
 */

import type { ImportPayload } from '../types';

export type HashRoute =
  | { kind: 'share'; token: string }
  | { kind: 'recovery'; accessToken: string }
  | { kind: 'import' }
  | { kind: 'auth-error'; message: string };

/** Interpret `location.hash`. Returns null for an ordinary page load. */
export function parseHash(hash: string): HashRoute | null {
  const raw = hash.replace(/^#/, '');
  if (!raw) return null;

  const share = raw.match(/^\/share\/([A-Za-z0-9_-]{20,64})\/?$/);
  if (share) return { kind: 'share', token: share[1] };
  if (raw === '/import') return { kind: 'import' };

  // Supabase puts the session (or an error) after "#" as query-style parameters.
  const params = new URLSearchParams(raw);
  if (params.get('type') === 'recovery' && params.get('access_token')) {
    return { kind: 'recovery', accessToken: params.get('access_token')! };
  }
  const description = params.get('error_description');
  if (description) {
    const expired = params.get('error_code') === 'otp_expired' || /expired|invalid/i.test(description);
    return {
      kind: 'auth-error',
      message: expired
        ? 'That link has expired or was already used. Request a new one below.'
        : description.replace(/\+/g, ' '),
    };
  }
  return null;
}

/** Full link a person can open to see a shared chat / source. */
export function shareUrl(token: string, origin: string = window.location.origin, path: string = window.location.pathname): string {
  return `${origin}${path}#/share/${token}`;
}

/** Remove the hash from the address bar without reloading (keeps secrets out of history). */
export function clearHash() {
  history.replaceState(null, '', window.location.pathname + window.location.search);
}

// ── Browser button (bookmarklet) ─────────────────────────────────────

/**
 * A bookmark that sends the text of whatever page you are looking at — from
 * YOUR browser, with YOUR login and any paywall access you have — to this app.
 * The app shows what it received and asks before adding anything.
 */
export function buildBookmarklet(appOrigin: string): string {
  const origin = JSON.stringify(appOrigin);
  const code = `
(function () {
  var APP = ${origin};
  var text = (document.body && document.body.innerText) || '';
  if (text.trim().length < 20) { alert('This page has no readable text.'); return; }
  var win = window.open(APP + '/#/import', 'docuquery_import');
  if (!win) { alert('Please allow pop-ups so the page can be sent to DocuQuery.'); return; }
  var nonce = String(Date.now()) + Math.random();
  var done = false, tries = 0;
  window.addEventListener('message', function (e) {
    if (e.origin === APP && e.data && e.data.type === 'docuquery-received' && e.data.nonce === nonce) done = true;
  });
  var timer = setInterval(function () {
    if (done || ++tries > 40) { clearInterval(timer); return; }
    win.postMessage({ type: 'docuquery-import', nonce: nonce, title: document.title, url: location.href, text: text.slice(0, 1500000) }, APP);
  }, 500);
})();`;
  return 'javascript:' + code.replace(/\s*\n\s*/g, ' ').trim();
}

const MAX_IMPORT_CHARS = 1_500_000;

/** Validate a message from another window before it is shown to the user. */
export function readImportMessage(data: unknown): (ImportPayload & { nonce: string }) | null {
  if (!data || typeof data !== 'object') return null;
  const m = data as Record<string, unknown>;
  if (m.type !== 'docuquery-import' || typeof m.text !== 'string' || typeof m.nonce !== 'string') return null;
  const text = m.text.trim();
  if (text.length < 20 || text.length > MAX_IMPORT_CHARS) return null;
  const url = typeof m.url === 'string' && /^https?:\/\//i.test(m.url) ? m.url.slice(0, 2000) : '';
  const title = typeof m.title === 'string' ? m.title.trim().slice(0, 200) : '';
  return { title, url, text, nonce: m.nonce.slice(0, 100) };
}
