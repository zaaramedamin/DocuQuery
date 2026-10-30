/**
 * Starter tasks and questions for the current scope (one source, a
 * comparison, a tag, a folder, or the whole library).
 */

import { translate } from '../i18n';
import type { Translator } from '../i18n';
import type { DocInfo } from '../types';

const ENGLISH: Translator = (key, vars) => translate('en', key, vars);

export interface Suggestions {
  tasks: string[];
  questions: string[];
}

export function tagMembers(documents: DocInfo[], tag: string): DocInfo[] {
  const wanted = tag.toLowerCase();
  return documents.filter((d) => (d.tags ?? []).some((t) => t.toLowerCase() === wanted));
}

export function folderMembers(documents: DocInfo[], folder: string): DocInfo[] {
  const wanted = folder.toLowerCase();
  return documents.filter((d) => (d.folder ?? '').toLowerCase() === wanted);
}

/** Drop repeats (ignoring case and surrounding spaces), keeping the first wording. */
function unique(items: string[]): string[] {
  const seen = new Map<string, string>();
  for (const item of items) {
    const key = item.trim().toLowerCase();
    if (key && !seen.has(key)) seen.set(key, item.trim());
  }
  return [...seen.values()];
}

export function getSuggestions(
  documents: DocInfo[],
  selected: string[],
  activeTag: string | null,
  activeFolder: string | null = null,
  t: Translator = ENGLISH,
): Suggestions {
  const result = pick(documents, selected, activeTag, activeFolder, t);
  return { tasks: unique(result.tasks), questions: unique(result.questions).slice(0, 4) };
}

function pick(
  documents: DocInfo[],
  selected: string[],
  activeTag: string | null,
  activeFolder: string | null,
  t: Translator,
): Suggestions {
  if (documents.length === 0) return { tasks: [], questions: [] };

  if (selected.length >= 2) {
    return {
      tasks: [t('Compare them side by side'), t('Where do they disagree?'), t('Summarize each one in a paragraph')],
      questions: [t('What do these sources have in common?'), t('Which one is more recent or more detailed?')],
    };
  }

  if (selected.length === 1) {
    const doc = documents.find((d) => d.filename === selected[0]);
    return {
      tasks: [t('Summarize this source'), t('List the key numbers and dates'), t('Explain it to a beginner')],
      questions: doc?.suggested_questions ?? [],
    };
  }

  if (activeFolder) {
    const members = folderMembers(documents, activeFolder);
    return {
      tasks: [
        t('Give me an overview of the folder {name}', { name: activeFolder }),
        t('What are the key points across these sources?'),
      ],
      questions: members.flatMap((d) => d.suggested_questions.slice(0, 2)),
    };
  }

  if (activeTag) {
    const members = tagMembers(documents, activeTag);
    return {
      tasks: [t('Give me an overview of #{name}', { name: activeTag }), t('What are the key points across these sources?')],
      questions: members.flatMap((d) => d.suggested_questions.slice(0, 2)),
    };
  }

  return {
    tasks: [t('What topics do my sources cover?'), t('Summarize my most recent source')],
    questions: documents.flatMap((d) => d.suggested_questions.slice(0, 2)),
  };
}
