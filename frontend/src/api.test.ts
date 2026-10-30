import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** The api module keeps the session in module state, so load a fresh copy per test. */
async function freshApi(initialSession?: object) {
  const store = new Map<string, string>();
  if (initialSession) store.set('docuquery.session', JSON.stringify(initialSession));
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  vi.resetModules();
  return { api: await import('./api'), store };
}

const SESSION = {
  access_token: 'old-access',
  refresh_token: 'old-refresh',
  expires_at: null,
  user: { id: 'u1', email: 'a@example.com' },
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const NEW_SESSION = { access_token: 'new-access', refresh_token: 'new-refresh', user: SESSION.user };

beforeEach(() => {
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('errorMessage', () => {
  it('reads FastAPI string and validation errors', async () => {
    const { api } = await freshApi();
    expect(api.errorMessage({ detail: 'Nope.' }, 'fb')).toBe('Nope.');
    expect(api.errorMessage({ detail: [{ msg: 'Value error, too short' }] }, 'fb')).toBe('too short');
    expect(api.errorMessage({}, 'fb')).toBe('fb');
    expect(api.errorMessage(null, 'fb')).toBe('fb');
  });
});

describe('session handling', () => {
  it('restores a saved session', async () => {
    expect((await freshApi(SESSION)).api.getSession()?.user.email).toBe('a@example.com');
  });

  it('ignores corrupt or incomplete stored sessions', async () => {
    for (const raw of ['{not json', '{"foo": 1}', 'null']) {
      vi.stubGlobal('localStorage', { getItem: () => raw, setItem() {}, removeItem() {} });
      vi.resetModules();
      expect((await import('./api')).getSession(), raw).toBeNull();
    }
  });

  it('login stores the session and notifies listeners; signOut clears it', async () => {
    const { api, store } = await freshApi();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(NEW_SESSION)));
    const seen: Array<string | null> = [];
    api.onAuthChange((s) => seen.push(s?.access_token ?? null));

    await api.login('a@example.com', 'password123');
    expect(api.getSession()?.access_token).toBe('new-access');
    expect(JSON.parse(store.get('docuquery.session')!).refresh_token).toBe('new-refresh');

    api.signOut();
    expect(api.getSession()).toBeNull();
    expect(store.has('docuquery.session')).toBe(false);
    expect(seen).toEqual(['new-access', null]);
  });

  it('signup that needs email confirmation does not create a session', async () => {
    const { api } = await freshApi();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ needs_confirmation: true, email: 'a@example.com' })));
    expect(await api.signup('a@example.com', 'password123')).toBe(true);
    expect(api.getSession()).toBeNull();
  });

  it('surfaces server error messages on failed login', async () => {
    const { api } = await freshApi();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Incorrect email or password.' }, 401)));
    await expect(api.login('a@example.com', 'wrong-password')).rejects.toThrow('Incorrect email or password.');
  });
});

describe('authFetch', () => {
  it('sends the bearer token', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await api.authFetch('/documents');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer old-access');
  });

  it('refreshes the token once on a 401 and retries the request', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/auth/refresh')) return json(NEW_SESSION);
      const auth = new Headers(init?.headers).get('Authorization');
      return auth === 'Bearer new-access' ? json({ documents: [] }) : json({ detail: 'expired' }, 401);
    });
    vi.stubGlobal('fetch', fetchMock);

    const res = await api.authFetch('/documents');
    expect(res.status).toBe(200);
    expect(api.getSession()?.access_token).toBe('new-access');
    expect(fetchMock).toHaveBeenCalledTimes(3); // request, refresh, retry
  });

  it('signs the user out when the refresh fails', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        String(url).endsWith('/auth/refresh') ? json({ detail: 'dead' }, 401) : json({ detail: 'expired' }, 401),
      ),
    );
    const res = await api.authFetch('/documents');
    expect(res.status).toBe(401);
    expect(api.getSession()).toBeNull();
  });

  it('shares ONE refresh between simultaneous 401s', async () => {
    const { api } = await freshApi(SESSION);
    let refreshCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith('/auth/refresh')) {
          refreshCalls += 1;
          await new Promise((r) => setTimeout(r, 10));
          return json(NEW_SESSION);
        }
        return new Headers(init?.headers).get('Authorization') === 'Bearer new-access'
          ? json({})
          : json({ detail: 'expired' }, 401);
      }),
    );
    await Promise.all([api.authFetch('/documents'), api.authFetch('/conversations'), api.authFetch('/usage')]);
    expect(refreshCalls).toBe(1);
  });
});

/* ── Streamed uploads ─────────────────────────────────────────────── */

class FakeXHR {
  static script: (x: FakeXHR) => void = () => {};
  static last: FakeXHR;
  upload: { onprogress: ((e: unknown) => void) | null } = { onprogress: null };
  onprogress: (() => void) | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  status = 200;
  responseText = '';
  headers: Record<string, string> = {};
  url = '';
  open(_method: string, url: string) {
    this.url = url;
    FakeXHR.last = this;
  }
  setRequestHeader(key: string, value: string) {
    this.headers[key] = value;
  }
  send() {
    FakeXHR.script(this);
  }
  emit(line: object) {
    this.responseText += JSON.stringify(line) + '\n';
    this.onprogress?.();
  }
}

const DOC = { id: 'd1', filename: 'a.txt', file_type: 'txt', chunks_count: 7 };

describe('uploadFile (streamed progress)', () => {
  beforeEach(() => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    vi.stubGlobal('FormData', class { append() {} });
  });

  it('reports transfer then server progress, monotonically, and resolves with the document', async () => {
    const { api } = await freshApi(SESSION);
    FakeXHR.script = (x) => {
      x.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
      x.emit({ type: 'progress', percent: 0, message: 'Starting…' });
      x.emit({ type: 'progress', percent: 50, message: 'Embedding passages 16/32…' });
      x.emit({ type: 'progress', percent: 100, message: 'Done' });
      x.emit({ type: 'done', document: DOC });
      x.onload?.();
    };

    const seen: Array<[number, string]> = [];
    const doc = await api.uploadFile(new File(['x'], 'a.txt'), (p) => seen.push([p.percent, p.message]));

    expect(doc).toEqual(DOC);
    expect(seen[0]).toEqual([5, 'Uploading…']);
    expect(seen.map(([p]) => p)).toEqual([5, 10, 55, 100]);
    expect(FakeXHR.last.headers['Authorization']).toBe('Bearer old-access');
    expect(FakeXHR.last.url).toMatch(/\/api\/upload$/);
  });

  it('handles progress lines split across network chunks', async () => {
    const { api } = await freshApi(SESSION);
    FakeXHR.script = (x) => {
      const line = JSON.stringify({ type: 'progress', percent: 40, message: 'Halfway' }) + '\n';
      x.responseText = line.slice(0, 20); // incomplete line: must wait
      x.onprogress?.();
      x.responseText = line + JSON.stringify({ type: 'done', document: DOC }) + '\n';
      x.onprogress?.();
      x.onload?.();
    };
    const messages: string[] = [];
    await api.uploadFile(new File(['x'], 'a.txt'), (p) => messages.push(p.message));
    expect(messages).toEqual(['Halfway']);
  });

  it('rejects with the pipeline error sent in the stream', async () => {
    const { api } = await freshApi(SESSION);
    FakeXHR.script = (x) => {
      x.emit({ type: 'progress', percent: 10, message: 'Reading' });
      x.emit({ type: 'error', detail: 'No readable text found in this file.' });
      x.onload?.();
    };
    await expect(api.uploadFile(new File(['x'], 'a.pdf'), () => {})).rejects.toThrow('No readable text found');
  });

  it('rejects with the JSON error for HTTP failures (e.g. quota)', async () => {
    const { api } = await freshApi(SESSION);
    FakeXHR.script = (x) => {
      x.status = 403;
      x.responseText = JSON.stringify({ detail: 'Your library is full (25 sources).' });
      x.onload?.();
    };
    await expect(api.uploadFile(new File(['x'], 'a.txt'), () => {})).rejects.toThrow('library is full');
  });

  it('signs out on 401', async () => {
    const { api } = await freshApi(SESSION);
    FakeXHR.script = (x) => {
      x.status = 401;
      x.onload?.();
    };
    await expect(api.uploadFile(new File(['x'], 'a.txt'), () => {})).rejects.toThrow('expired');
    expect(api.getSession()).toBeNull();
  });

  it('fails clearly when the stream ends without a result', async () => {
    const { api } = await freshApi(SESSION);
    FakeXHR.script = (x) => {
      x.emit({ type: 'progress', percent: 30, message: 'Embedding' });
      x.onload?.();
    };
    await expect(api.uploadFile(new File(['x'], 'a.txt'), () => {})).rejects.toThrow('ended unexpectedly');
  });

  it('reports network failures', async () => {
    const { api } = await freshApi(SESSION);
    FakeXHR.script = (x) => x.onerror?.();
    await expect(api.uploadFile(new File(['x'], 'a.txt'), () => {})).rejects.toThrow('Network error');
  });
});

/* ── Password reset, sharing, tags, search ────────────────────────── */

describe('password reset', () => {
  it('asks for the reset email and tells the server which site to link back to', async () => {
    const { api } = await freshApi();
    vi.stubGlobal('window', { location: { origin: 'https://docuquery.example.com' } });
    const fetchMock = vi.fn().mockResolvedValue(json({ status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);

    await api.forgotPassword('a@example.com');
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/auth\/forgot-password$/);
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      email: 'a@example.com',
      redirect_to: 'https://docuquery.example.com/',
    });
  });

  it('surfaces the server message when the new password is refused', async () => {
    const { api } = await freshApi();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Password should contain a number' }, 400)));
    await expect(api.resetPassword('token-value-123', 'alllowercase')).rejects.toThrow('contain a number');
  });

  it('sends the emailed token in the body, not as a session', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ status: 'success' }));
    vi.stubGlobal('fetch', fetchMock);
    await api.resetPassword('emailed-token-123', 'a-new-password');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ access_token: 'emailed-token-123', password: 'a-new-password' });
    expect(new Headers(init.headers).get('Authorization')).toBeNull();
  });
});

describe('sharing', () => {
  it('opening a share link never sends the login token (it is a public page)', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ kind: 'conversation', title: 'T', messages: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await api.getShared('some-token-value-abcdefghij');
    const init = (fetchMock.mock.calls[0][1] ?? {}) as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBeNull();
  });

  it('a dead link is reported with the server message and does NOT sign the user out', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: "This link doesn't exist or has been turned off." }, 404)));
    await expect(api.getShared('x'.repeat(30))).rejects.toThrow("doesn't exist");
    expect(api.getSession()).not.toBeNull();
  });

  it('creates and revokes links with the signed-in token', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'DELETE' ? json({ status: 'success' }) : json({ id: 's1', token: 'tok', kind: 'document', ref: 'a.pdf', created_at: null }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const share = await api.createShare('document', 'a.pdf');
    expect(share.token).toBe('tok');
    await api.revokeShare('s1');
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers((init as RequestInit).headers).get('Authorization')).toBe('Bearer old-access');
    }
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/shares\/s1$/);
  });

  it('adding a shared source returns the new library entry', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ status: 'success', document: { filename: 'report (2).pdf' } })));
    expect((await api.acceptShared('t'.repeat(30))).filename).toBe('report (2).pdf');
  });
});

describe('tags, search and pasted text', () => {
  it('saves tags for a file name that needs URL encoding', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ tags: ['legal'] }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await api.setTags('Q3 report #2.pdf', ['legal'])).toEqual(['legal']);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/documents/Q3%20report%20%232.pdf/tags');
  });

  it('URL-encodes the chat search so special characters stay literal', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ results: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await api.searchConversations('100% & more');
    expect(String(fetchMock.mock.calls[0][0])).toContain('q=100%25%20%26%20more');
  });

  it('pasted text goes up as JSON and reports progress like any upload', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    let sent = '';
    FakeXHR.script = (x) => {
      sent = (x as unknown as { body: string }).body;
      x.emit({ type: 'progress', percent: 50, message: 'Embedding' });
      x.emit({ type: 'done', document: DOC });
      x.onload?.();
    };
    const send = FakeXHR.prototype.send;
    FakeXHR.prototype.send = function (this: FakeXHR, body?: unknown) {
      (this as unknown as { body: unknown }).body = body;
      return send.call(this);
    };
    const messages: string[] = [];
    const doc = await api.uploadText({ title: 'Article', text: 'Some pasted words.' }, (p) => messages.push(p.message));
    FakeXHR.prototype.send = send;

    expect(doc).toEqual(DOC);
    expect(JSON.parse(sent)).toEqual({ title: 'Article', text: 'Some pasted words.', url: null });
    expect(FakeXHR.last.url).toMatch(/\/api\/upload-text$/);
    expect(FakeXHR.last.headers['Content-Type']).toBe('application/json');
    expect(messages).toContain('Embedding');
  });
});

describe('plan limits and errors', () => {
  it('reads the message and the upgrade flag out of a plan-limit error', async () => {
    const { api } = await freshApi();
    const body = { detail: { message: 'Over 10 MB.', code: 'file_too_large', upgrade: true, plan: 'free' } };
    expect(api.errorMessage(body, 'fb')).toBe('Over 10 MB.');
    const err = api.apiError(body, 'fb', 413);
    expect(err).toBeInstanceOf(Error);
    expect(err).toMatchObject({ message: 'Over 10 MB.', status: 413, code: 'file_too_large', upgrade: true });
  });

  it('plain string errors are not upgrade prompts', async () => {
    const { api } = await freshApi();
    const err = api.apiError({ detail: 'Nope.' }, 'fb', 403);
    expect(err).toMatchObject({ message: 'Nope.', status: 403, upgrade: false });
    expect(err.code).toBeUndefined();
  });

  it('a server error about a full library is an ApiError an upgrade dialog can act on', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(json({ detail: { message: 'Library full', code: 'library_full', upgrade: true } }, 403)),
    );
    const err = await api.assignFolder(['a.pdf'], 'F').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(api.ApiError);
    expect(err).toMatchObject({ upgrade: true, code: 'library_full', status: 403 });
  });
});

describe('folders', () => {
  it('moves sources into a folder with a PUT and returns the final name', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ folder: 'Contracts', moved: 2 }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await api.assignFolder(['a.pdf', 'b.pdf'], 'contracts')).toBe('Contracts');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/folders\/assign$/);
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ filenames: ['a.pdf', 'b.pdf'], folder: 'contracts' });
  });

  it('renames and deletes folders, encoding the name in the address', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValueOnce(json({ folder: 'New' })).mockResolvedValueOnce(json({ status: 'success' }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await api.renameFolder('Old', 'New')).toBe('New');
    await api.deleteFolder('R&D / 2026');
    expect(fetchMock.mock.calls[0][1].method).toBe('PATCH');
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/api\/folders\?name=R%26D%20%2F%202026$/);
    expect(fetchMock.mock.calls[1][1].method).toBe('DELETE');
  });
});

describe('account and billing', () => {
  it('saves a settings patch with PUT', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ settings: {} }));
    vi.stubGlobal('fetch', fetchMock);
    await api.saveSettings({ theme: 'dark', answer_language: 'fr' });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/settings$/);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ theme: 'dark', answer_language: 'fr' });
  });

  it('a wrong current password is shown to the user and does not sign them out', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Your current password is incorrect.' }, 400)));
    await expect(api.changePassword('bad', 'new-password-1')).rejects.toThrow('incorrect');
    expect(api.getSession()).not.toBeNull();
  });

  it('switches the plan with a POST and nothing else (a demo: no payment is involved)', async () => {
    const { api } = await freshApi(SESSION);
    const fetchMock = vi.fn().mockResolvedValue(json({ plan: 'pro' }));
    vi.stubGlobal('fetch', fetchMock);
    await api.switchPlan('pro');
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/billing\/demo$/);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ plan: 'pro' });
  });

  it('deleting the account signs the user out afterwards', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ status: 'success' })));
    await api.deleteAccount('pw');
    expect(api.getSession()).toBeNull();
  });

  it('a failed deletion keeps the session', async () => {
    const { api } = await freshApi(SESSION);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Your current password is incorrect.' }, 400)));
    await expect(api.deleteAccount('nope')).rejects.toThrow();
    expect(api.getSession()).not.toBeNull();
  });
});
