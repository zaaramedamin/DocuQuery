import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_PREFERENCES,
  MAX_INSTRUCTIONS,
  loadPreferences,
  mergePreferences,
  sanitizePreferences,
} from './preferences';
import { checkUploadSizes } from './utils/uploadLimits';

const MB = 1024 * 1024;

describe('sanitizePreferences', () => {
  it('returns the defaults for nothing or for junk', () => {
    expect(sanitizePreferences(undefined)).toEqual(DEFAULT_PREFERENCES);
    expect(sanitizePreferences('nope')).toEqual(DEFAULT_PREFERENCES);
    expect(sanitizePreferences(null)).toEqual(DEFAULT_PREFERENCES);
  });

  it('keeps valid values', () => {
    const prefs = sanitizePreferences({ theme: 'dark', ui_language: 'fr', answer_length: 'concise', send_with_enter: false });
    expect(prefs).toMatchObject({ theme: 'dark', ui_language: 'fr', answer_length: 'concise', send_with_enter: false });
  });

  it('drops invalid values and unknown keys', () => {
    const prefs = sanitizePreferences({ theme: 'neon', answer_language: 'klingon', send_with_enter: 'yes', plan: 'pro' });
    expect(prefs).toEqual(DEFAULT_PREFERENCES);
    expect(prefs).not.toHaveProperty('plan');
  });

  it('caps the custom instructions', () => {
    const prefs = sanitizePreferences({ custom_instructions: 'x'.repeat(5000) });
    expect(prefs.custom_instructions).toHaveLength(MAX_INSTRUCTIONS);
  });
});

describe('loadPreferences', () => {
  // The test environment has no browser storage: provide a small one.
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('reads what was saved', () => {
    localStorage.setItem('docuquery.preferences', JSON.stringify({ theme: 'dark', answer_language: 'fr' }));
    expect(loadPreferences()).toMatchObject({ theme: 'dark', answer_language: 'fr' });
  });

  it('survives corrupt storage', () => {
    localStorage.setItem('docuquery.preferences', '{not json');
    expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES);
  });

  it('migrates the response style saved by older versions', () => {
    localStorage.setItem('docuquery.responseStyle', 'formal');
    expect(loadPreferences().response_style).toBe('formal');
  });
});

describe('mergePreferences', () => {
  it('lets the account win', () => {
    const local = { ...DEFAULT_PREFERENCES, theme: 'light' as const };
    const server = { ...DEFAULT_PREFERENCES, theme: 'dark' as const };
    const { merged, push } = mergePreferences(local, server);
    expect(merged.theme).toBe('dark');
    expect(push).toEqual({});
  });

  it("keeps this browser's choice where the account still has the default, and sends it up", () => {
    const local = { ...DEFAULT_PREFERENCES, ui_language: 'fr' as const, theme: 'dark' as const };
    const server = { ...DEFAULT_PREFERENCES, theme: 'light' as const };
    const { merged, push } = mergePreferences(local, server);
    expect(merged.ui_language).toBe('fr');
    expect(merged.theme).toBe('light');
    expect(push).toEqual({ ui_language: 'fr' });
  });
});

describe('checkUploadSizes', () => {
  const file = (name: string, mb: number) => ({ name, size: mb * MB });

  it('accepts files within the plan limit (10 MB on Free, inclusive)', () => {
    const r = checkUploadSizes([file('a', 1), file('b', 10)], 10 * MB, 'free', 50 * MB);
    expect(r.accepted.map((f) => f.name)).toEqual(['a', 'b']);
    expect(r.needsPro).toEqual([]);
    expect(r.tooLarge).toEqual([]);
  });

  it('offers Pro for a Free user whose file is over 10 MB but within the Pro limit', () => {
    const r = checkUploadSizes([file('ok', 2), file('big', 11)], 10 * MB, 'free', 50 * MB);
    expect(r.accepted.map((f) => f.name)).toEqual(['ok']);
    expect(r.needsPro.map((f) => f.name)).toEqual(['big']);
  });

  it('refuses outright what even Pro cannot take', () => {
    const r = checkUploadSizes([file('huge', 80)], 10 * MB, 'free', 50 * MB);
    expect(r.tooLarge.map((f) => f.name)).toEqual(['huge']);
    expect(r.needsPro).toEqual([]);
  });

  it('does not offer Pro to someone who already has it', () => {
    const r = checkUploadSizes([file('huge', 60)], 50 * MB, 'pro', 50 * MB);
    expect(r.tooLarge.map((f) => f.name)).toEqual(['huge']);
    expect(r.needsPro).toEqual([]);
  });

  it('lets the server decide until the plan has loaded', () => {
    const r = checkUploadSizes([file('any', 99)], undefined, 'free', undefined);
    expect(r.accepted).toHaveLength(1);
  });
});
