/**
 * Small display helpers shared by components.
 */

import { translate, translatePlural } from '../i18n';
import type { PluralTranslator, Translator } from '../i18n';
import type { FileType } from '../types';

const ENGLISH: Translator = (key, vars) => translate('en', key, vars);
const ENGLISH_PLURAL: PluralTranslator = (one, other, count, vars) => translatePlural('en', one, other, count, vars);

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  if (bytes >= 1024 ** 3) return `${Number((bytes / 1024 ** 3).toFixed(1))} GB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

/** "$10" for 1000 cents (no needless ".00"). */
export function formatPrice(cents: number, currency: string, lang: string): string {
  return new Intl.NumberFormat(lang, {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

const TYPE_LABELS: Record<FileType, string> = {
  pdf: 'PDF',
  docx: 'Word',
  pptx: 'PowerPoint',
  xlsx: 'Excel',
  csv: 'CSV',
  txt: 'Text',
  md: 'Markdown',
  image: 'Image',
  url: 'Web page',
};

export function fileTypeLabel(type: FileType): string {
  return TYPE_LABELS[type] ?? type.toUpperCase();
}

/** Word for one page of a source: real pages, slides, or sections for text-like sources. */
export function pageUnit(type: FileType): 'page' | 'slide' | 'section' {
  if (type === 'pdf' || type === 'image') return 'page';
  if (type === 'pptx') return 'slide';
  return 'section';
}

/** "12 pages", "1 slide", or "3 sections". */
export function pageCountLabel(type: FileType, count: number, tn: PluralTranslator = ENGLISH_PLURAL): string {
  const unit = pageUnit(type);
  if (unit === 'page') return tn('{count} page', '{count} pages', count);
  if (unit === 'slide') return tn('{count} slide', '{count} slides', count);
  return tn('{count} section', '{count} sections', count);
}

/** File extensions the upload box accepts (kept in sync with the backend). */
export const ACCEPTED_EXTENSIONS = [
  '.pdf', '.docx', '.pptx', '.xlsx', '.csv', '.tsv', '.txt', '.md', '.markdown', '.png', '.jpg', '.jpeg', '.webp',
];

export function isAcceptedFile(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/** Compact relative time for the chat list: "just now", "5m", "3h", "2d", or a date. */
export function timeAgo(iso: string, now: number = Date.now(), t: Translator = ENGLISH): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return t('just now');
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return t('{count}m', { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t('{count}h', { count: hours });
  const days = Math.round(hours / 24);
  if (days < 7) return t('{count}d', { count: days });
  return new Date(iso).toLocaleDateString();
}

/**
 * Split *text* into pieces so that matches of *query* (case-insensitive) can be
 * highlighted. Pieces with `match: true` are the matches.
 */
export function splitHighlight(text: string, query: string): { text: string; match: boolean }[] {
  const needle = query.trim();
  if (!needle) return [{ text, match: false }];
  const lower = text.toLowerCase();
  const target = needle.toLowerCase();
  const parts: { text: string; match: boolean }[] = [];
  let from = 0;
  for (;;) {
    const at = lower.indexOf(target, from);
    if (at < 0) break;
    if (at > from) parts.push({ text: text.slice(from, at), match: false });
    parts.push({ text: text.slice(at, at + target.length), match: true });
    from = at + target.length;
  }
  if (from < text.length) parts.push({ text: text.slice(from), match: false });
  return parts.length ? parts : [{ text, match: false }];
}

/** Rough Markdown → plain text, for one-line previews (search snippets). */
export function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/(\*\*|__|\*|_|~~)(?=\S)([^*_~]+?)\1/g, '$2')
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, '')
    .replace(/(^|\s)[-*+](?=\s)/g, '$1')
    .replace(/^[\s|:-]+$/gm, ' ')
    .replace(/:?-{3,}:?/g, ' ')
    .replace(/\|/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
