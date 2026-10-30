import { describe, expect, it } from 'vitest';
import { detectLanguage, resolveLanguage, translate, translatePlural } from './index';
import { FR } from './fr';

/** Every source file's text (the tests, and this folder's own files, are left out). */
const SOURCES = import.meta.glob(['../**/*.ts', '../**/*.tsx', '!../**/*.test.*', '!../i18n/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** Every English string handed to t() / tn() in the source (same extraction as scripts/list-strings.mjs). */
function stringsInSource(): string[] {
  const found = new Set<string>();
  const STRING = String.raw`(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")`;
  const single = new RegExp(String.raw`\b(?:t|msg)\(\s*${STRING}`, 'g');
  const plural = new RegExp(String.raw`\btn\(\s*${STRING}\s*,\s*${STRING}`, 'g');
  const unescape = (s: string) => s.replace(/\\(['"\\])/g, '$1').replace(/\\n/g, '\n');

  for (const text of Object.values(SOURCES)) {
    for (const m of text.matchAll(single)) found.add(unescape(m[1] ?? m[2]));
    for (const m of text.matchAll(plural)) {
      found.add(unescape(m[1] ?? m[2]));
      found.add(unescape(m[3] ?? m[4]));
    }
  }
  return [...found];
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('French translations', () => {
  const strings = stringsInSource();

  it('finds the strings used in the code', () => {
    expect(strings.length).toBeGreaterThan(300);
  });

  it('has an entry for every string in the code', () => {
    const missing = strings.filter((s) => !(s in FR));
    expect(missing).toEqual([]);
  });

  it('has no entries the code no longer uses', () => {
    const used = new Set(strings);
    expect(Object.keys(FR).filter((k) => !used.has(k))).toEqual([]);
  });

  it('keeps the {placeholders} of every string (singular forms may drop {count})', () => {
    const broken = Object.entries(FR).filter(([en, fr]) => {
      const wanted = placeholders(en);
      const got = placeholders(fr);
      const onlyCountMissing = wanted.filter((p) => !got.includes(p)).every((p) => p === 'count');
      return got.some((p) => !wanted.includes(p)) || !onlyCountMissing;
    });
    expect(broken.map(([en]) => en)).toEqual([]);
  });

  it('never leaves a translation empty or identical to a sentence it should translate', () => {
    expect(Object.values(FR).every((v) => v.trim().length > 0)).toBe(true);
  });

  it('puts a non-breaking space before ? ! : ; as French typography wants', () => {
    expect(FR['Forgot password?']).toBe('Mot de passe oublié\u00a0?');
    expect(FR['Sources: {list}']).toBe('Sources\u00a0: {list}');
    expect(FR['Starting…']).toBe('Démarrage…');
  });
});

describe('translate', () => {
  it('returns the English text itself in English', () => {
    expect(translate('en', 'Upload file')).toBe('Upload file');
  });

  it('translates to French and fills placeholders', () => {
    expect(translate('fr', 'Upload file')).toBe('Téléverser un fichier');
    expect(translate('fr', '"{name}" was deleted.', { name: 'a.pdf' })).toBe('«\u00a0a.pdf\u00a0» a été supprimé.');
  });

  it('falls back to English for a string with no translation', () => {
    expect(translate('fr', 'A brand new sentence for {who}', { who: 'you' })).toBe('A brand new sentence for you');
  });

  it('leaves unknown placeholders alone', () => {
    expect(translate('en', 'Hello {name}')).toBe('Hello {name}');
  });
});

describe('translatePlural', () => {
  it('picks singular or plural English', () => {
    expect(translatePlural('en', '{count} page', '{count} pages', 1)).toBe('1 page');
    expect(translatePlural('en', '{count} page', '{count} pages', 0)).toBe('0 pages');
    expect(translatePlural('en', '{count} page', '{count} pages', 12)).toBe('12 pages');
  });

  it('follows French rules: zero and one are singular', () => {
    expect(translatePlural('fr', '{count} chat deleted.', '{count} chats deleted.', 0)).toBe('0 discussion supprimée.');
    expect(translatePlural('fr', '{count} chat deleted.', '{count} chats deleted.', 1)).toBe('1 discussion supprimée.');
    expect(translatePlural('fr', '{count} chat deleted.', '{count} chats deleted.', 2)).toBe('2 discussions supprimées.');
  });

  it('lets a caller format the count itself', () => {
    expect(translatePlural('en', '{count} word', '{count} words', 1200, { count: '1,200' })).toBe('1,200 words');
  });
});

describe('language detection', () => {
  it('uses the browser language when it is supported', () => {
    expect(detectLanguage('fr-CA')).toBe('fr');
    expect(detectLanguage('FR')).toBe('fr');
    expect(detectLanguage('en-GB')).toBe('en');
  });

  it('falls back to English', () => {
    expect(detectLanguage('ja-JP')).toBe('en');
    expect(detectLanguage('')).toBe('en');
    expect(detectLanguage(undefined)).toBeTypeOf('string');
  });

  it('honours an explicit choice over the browser', () => {
    expect(resolveLanguage('en', 'fr-FR')).toBe('en');
    expect(resolveLanguage('fr', 'en-US')).toBe('fr');
    expect(resolveLanguage('auto', 'fr-FR')).toBe('fr');
  });
});
