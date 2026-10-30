/**
 * Conversation export: Markdown download and print-to-PDF.
 */

import { translate } from '../i18n';
import type { Translator } from '../i18n';
import type { Message, Source } from '../types';

const ENGLISH: Translator = (key, vars) => translate('en', key, vars);

function citedSources(sources: Source[] = [], t: Translator): string {
  const byFile = new Map<string, number[]>();
  for (const s of sources) {
    const pages = byFile.get(s.filename) ?? [];
    if (!pages.includes(s.page)) pages.push(s.page);
    byFile.set(s.filename, pages);
  }
  return [...byFile.entries()]
    .map(([file, pages]) => t('{file} (p. {pages})', { file, pages: pages.sort((a, b) => a - b).join(', ') }))
    .join('; ');
}

/** Render a conversation as a Markdown document. */
export function buildMarkdown(
  title: string,
  messages: Message[],
  scope: string[],
  exportedAt: Date = new Date(),
  t: Translator = ENGLISH,
): string {
  const lines: string[] = [`# ${title}`, ''];
  const meta = [t('Exported from DocuQuery on {date}', { date: exportedAt.toISOString().slice(0, 10) })];
  meta.push(scope.length ? t('Sources: {list}', { list: scope.join(', ') }) : t('Sources: all documents'));
  lines.push(`_${meta.join(' · ')}_`, '', '---', '');

  for (const message of messages) {
    if (!message.text.trim()) continue;
    if (message.sender === 'user') {
      lines.push(`### ${t('You')}`, '', message.text.trim(), '');
    } else {
      lines.push('### DocuQuery', '', message.text.trim(), '');
      const cited = citedSources(message.sources, t);
      if (cited) lines.push(`> **${t('Sources')}:** ${cited}`, '');
      if (message.stopped) lines.push(`> _${t('Generation was stopped before it finished.')}_`, '');
    }
  }
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
}

/** A safe file name derived from a chat title. */
export function exportFileName(title: string, extension: string): string {
  const base = title
    .replace(/[\\/:*?"<>|\p{Cc}]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60)
    .trim();
  return `${base || 'conversation'}.${extension}`;
}

export function downloadTextFile(fileName: string, content: string, mime = 'text/markdown;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Open the browser's print dialog (choose "Save as PDF"). The page title
 * becomes the suggested file name; print styles hide everything but the chat.
 */
export function printConversation(title: string) {
  const previous = document.title;
  document.title = exportFileName(title, 'pdf').replace(/\.pdf$/, '');
  const restore = () => {
    document.title = previous;
    window.removeEventListener('afterprint', restore);
  };
  window.addEventListener('afterprint', restore);
  window.print();
}
