import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildBookmarklet, parseHash, readImportMessage, shareUrl } from './route';
import { pageCountLabel, pageUnit, splitHighlight } from './format';

const TOKEN = 'abcdefghijklmnopqrstuvwxyz0123456789_-AB';

describe('parseHash', () => {
  it('recognises share links', () => {
    expect(parseHash(`#/share/${TOKEN}`)).toEqual({ kind: 'share', token: TOKEN });
    expect(parseHash(`#/share/${TOKEN}/`)).toEqual({ kind: 'share', token: TOKEN });
  });

  it('rejects malformed share tokens', () => {
    for (const bad of ['#/share/short', '#/share/', `#/share/${TOKEN}/extra`, '#/share/has space-aaaaaaaaaaaaaaaaaaaaaaa', '#/share/<script>aaaaaaaaaaaaaaaaaaaaaa']) {
      expect(parseHash(bad), bad).toBeNull();
    }
  });

  it('recognises the password-reset landing page', () => {
    expect(parseHash('#access_token=abc.def.ghi&refresh_token=x&type=recovery&expires_in=3600')).toEqual({
      kind: 'recovery',
      accessToken: 'abc.def.ghi',
    });
  });

  it('does not treat other Supabase redirects (e.g. email confirmation) as a reset', () => {
    expect(parseHash('#access_token=abc&type=signup')).toBeNull();
    expect(parseHash('#type=recovery')).toBeNull();
  });

  it('turns an expired email link into a friendly message', () => {
    const route = parseHash('#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired');
    expect(route).toMatchObject({ kind: 'auth-error' });
    expect((route as { message: string }).message).toContain('expired');
  });

  it('recognises the browser-button landing page', () => {
    expect(parseHash('#/import')).toEqual({ kind: 'import' });
  });

  it('returns null for ordinary loads', () => {
    expect(parseHash('')).toBeNull();
    expect(parseHash('#')).toBeNull();
    expect(parseHash('#something-else')).toBeNull();
  });
});

describe('shareUrl', () => {
  it('builds a hash link on the given site', () => {
    expect(shareUrl(TOKEN, 'https://docuquery.vercel.app', '/')).toBe(`https://docuquery.vercel.app/#/share/${TOKEN}`);
  });
  it('round-trips through parseHash', () => {
    const hash = shareUrl(TOKEN, 'https://x.test', '/').split('x.test/')[1];
    expect(parseHash(hash)).toEqual({ kind: 'share', token: TOKEN });
  });
});

describe('readImportMessage', () => {
  const good = { type: 'docuquery-import', nonce: 'n1', title: 'A page', url: 'https://example.com/a', text: 'x'.repeat(50) };

  it('accepts a well-formed message', () => {
    expect(readImportMessage(good)).toEqual({ title: 'A page', url: 'https://example.com/a', text: 'x'.repeat(50), nonce: 'n1' });
  });
  it('ignores anything that is not an import message', () => {
    for (const bad of [null, undefined, 'text', 42, {}, { ...good, type: 'other' }, { ...good, nonce: 5 }, { ...good, text: 5 }]) {
      expect(readImportMessage(bad)).toBeNull();
    }
  });
  it('rejects empty and oversized text', () => {
    expect(readImportMessage({ ...good, text: 'short' })).toBeNull();
    expect(readImportMessage({ ...good, text: 'x'.repeat(1_600_000) })).toBeNull();
  });
  it('never keeps a non-http link (it is shown as a link)', () => {
    expect(readImportMessage({ ...good, url: 'javascript:alert(1)' })?.url).toBe('');
    expect(readImportMessage({ ...good, url: 'data:text/html,<b>' })?.url).toBe('');
  });
  it('trims long titles', () => {
    expect(readImportMessage({ ...good, title: 'T'.repeat(500) })?.title.length).toBe(200);
  });
});

describe('browser button (bookmarklet)', () => {
  afterEach(() => vi.useRealTimers());

  const APP = 'https://docuquery.example.com';

  /** Run the bookmarklet code against a fake page and fake popup. */
  function run(options: { text?: string; popupBlocked?: boolean } = {}) {
    const code = buildBookmarklet(APP).replace(/^javascript:/, '');
    const posted: { message: any; origin: string }[] = [];
    const alerts: string[] = [];
    const listeners: Array<(e: any) => void> = [];
    const popup = { postMessage: (message: unknown, origin: string) => posted.push({ message, origin }) };
    const win = {
      open: vi.fn(() => (options.popupBlocked ? null : popup)),
      addEventListener: (_: string, fn: (e: any) => void) => listeners.push(fn),
    };
    const doc = { title: 'Medium article', body: { innerText: options.text ?? 'Paragraph one. '.repeat(20) } };
    new Function('window', 'document', 'location', 'alert', 'setInterval', 'clearInterval', 'String', code)(
      win, doc, { href: 'https://medium.com/p/abc' }, (m: string) => alerts.push(m), setInterval, clearInterval, String,
    );
    return { posted, alerts, win, hear: (data: unknown, origin = APP) => listeners.forEach((fn) => fn({ origin, data })) };
  }

  it('is a javascript: URL on a single line', () => {
    const url = buildBookmarklet(APP);
    expect(url.startsWith('javascript:')).toBe(true);
    expect(url).not.toMatch(/\n/);
  });

  it('only ever addresses the app origin', () => {
    vi.useFakeTimers();
    const { posted, win } = run();
    vi.advanceTimersByTime(600);
    expect(win.open).toHaveBeenCalledWith(`${APP}/#/import`, 'docuquery_import');
    expect(posted.length).toBeGreaterThan(0);
    expect(posted.every((p) => p.origin === APP)).toBe(true);
  });

  it('sends the page title, link and text, and keeps retrying until the app confirms', () => {
    vi.useFakeTimers();
    const { posted, hear } = run();
    vi.advanceTimersByTime(1600); // 3 attempts: the app window is still loading
    expect(posted.length).toBe(3);
    const message = posted[0].message;
    expect(message).toMatchObject({ type: 'docuquery-import', title: 'Medium article', url: 'https://medium.com/p/abc' });
    expect(message.text).toContain('Paragraph one.');

    hear({ type: 'docuquery-received', nonce: message.nonce });
    vi.advanceTimersByTime(5000);
    expect(posted.length).toBe(3); // stopped after the confirmation
  });

  it('ignores confirmations from other origins or for other pages', () => {
    vi.useFakeTimers();
    const { posted, hear } = run();
    vi.advanceTimersByTime(600);
    const { nonce } = posted[0].message;
    hear({ type: 'docuquery-received', nonce }, 'https://evil.example.com');
    hear({ type: 'docuquery-received', nonce: 'someone-else' });
    const before = posted.length;
    vi.advanceTimersByTime(1000);
    expect(posted.length).toBeGreaterThan(before);
  });

  it('gives up after a while instead of retrying forever', () => {
    vi.useFakeTimers();
    const { posted } = run();
    vi.advanceTimersByTime(60_000);
    expect(posted.length).toBeLessThanOrEqual(40);
  });

  it('tells the user when the page has no text or pop-ups are blocked', () => {
    expect(run({ text: 'tiny' }).alerts[0]).toContain('no readable text');
    const blocked = run({ popupBlocked: true });
    expect(blocked.alerts[0]).toContain('pop-ups');
  });

  it('caps how much text it sends', () => {
    vi.useFakeTimers();
    const { posted } = run({ text: 'x'.repeat(3_000_000) });
    vi.advanceTimersByTime(600);
    expect(posted[0].message.text.length).toBe(1_500_000);
  });

  it('cannot be broken out of by a hostile origin string', () => {
    const url = buildBookmarklet('https://x.test"; alert(1); "');
    expect(() => new Function(url.replace(/^javascript:/, ''))).not.toThrow(SyntaxError);
  });
});

describe('format helpers added for the new file types', () => {
  it('uses slides for presentations', () => {
    expect(pageUnit('pptx')).toBe('slide');
    expect(pageUnit('pdf')).toBe('page');
    expect(pageUnit('xlsx')).toBe('section');
    expect(pageCountLabel('pptx', 1)).toBe('1 slide');
    expect(pageCountLabel('pptx', 24)).toBe('24 slides');
  });

  it('splits text around every match, case-insensitively', () => {
    expect(splitHighlight('The Refund policy: refund in 30 days', 'refund')).toEqual([
      { text: 'The ', match: false },
      { text: 'Refund', match: true },
      { text: ' policy: ', match: false },
      { text: 'refund', match: true },
      { text: ' in 30 days', match: false },
    ]);
  });
  it('returns the text untouched when there is nothing to highlight', () => {
    expect(splitHighlight('hello', '')).toEqual([{ text: 'hello', match: false }]);
    expect(splitHighlight('hello', 'zzz')).toEqual([{ text: 'hello', match: false }]);
  });
  it('treats the query as plain text, not a pattern', () => {
    expect(splitHighlight('a.b (c)', '.b (')).toEqual([
      { text: 'a', match: false },
      { text: '.b (', match: true },
      { text: 'c)', match: false },
    ]);
  });
});
