import { describe, expect, it } from 'vitest';
import { buildMarkdown, exportFileName } from './exportChat';
import { formatBytes, isAcceptedFile, pageCountLabel, timeAgo } from './format';
import type { Message } from '../types';

describe('formatBytes', () => {
  it('scales units', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(50 * 1024)).toBe('50 KB');
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB');
    expect(formatBytes(200 * 1024 * 1024)).toBe('200 MB');
  });
});

describe('isAcceptedFile', () => {
  it('accepts supported types case-insensitively', () => {
    for (const name of ['a.pdf', 'B.DOCX', 'c.txt', 'd.md', 'e.markdown', 'f.PNG', 'g.jpg', 'h.jpeg', 'i.webp']) {
      expect(isAcceptedFile(name), name).toBe(true);
    }
  });
  it('rejects everything else', () => {
    for (const name of ['a.exe', 'b.html', 'c.svg', 'd.zip', 'pdf', '']) {
      expect(isAcceptedFile(name), name).toBe(false);
    }
  });
});

describe('pageCountLabel', () => {
  it('uses pages for PDFs and sections for text sources', () => {
    expect(pageCountLabel('pdf', 1)).toBe('1 page');
    expect(pageCountLabel('pdf', 12)).toBe('12 pages');
    expect(pageCountLabel('docx', 3)).toBe('3 sections');
    expect(pageCountLabel('url', 1)).toBe('1 section');
  });
});

describe('timeAgo', () => {
  const now = new Date('2026-01-10T12:00:00Z').getTime();
  const ago = (ms: number) => new Date(now - ms).toISOString();
  it('formats recent activity compactly', () => {
    expect(timeAgo(ago(10_000), now)).toBe('just now');
    expect(timeAgo(ago(5 * 60_000), now)).toBe('5m');
    expect(timeAgo(ago(3 * 3_600_000), now)).toBe('3h');
    expect(timeAgo(ago(2 * 86_400_000), now)).toBe('2d');
  });
  it('never returns a negative or odd value for clock skew', () => {
    expect(timeAgo(new Date(now + 60_000).toISOString(), now)).toBe('just now');
  });
});

describe('exportFileName', () => {
  it('strips characters that are illegal in file names', () => {
    expect(exportFileName('What is: the "refund" policy? <v2>', 'md')).toBe('What is the refund policy v2.md');
  });
  it('falls back when nothing usable is left', () => {
    expect(exportFileName('///', 'md')).toBe('conversation.md');
    expect(exportFileName('', 'pdf')).toBe('conversation.pdf');
  });
  it('truncates very long titles', () => {
    expect(exportFileName('x'.repeat(300), 'md').length).toBeLessThanOrEqual(63);
  });
});

describe('buildMarkdown', () => {
  const messages: Message[] = [
    { id: '1', sender: 'user', text: 'What is the refund window?' },
    {
      id: '2',
      sender: 'assistant',
      text: 'Returns are accepted within **30 days**.',
      sources: [
        { filename: 'policy.pdf', page: 3, text: '' },
        { filename: 'policy.pdf', page: 1, text: '' },
        { filename: 'policy.pdf', page: 3, text: '' },
        { filename: 'faq.docx', page: 2, text: '' },
      ],
    },
    { id: '3', sender: 'user', text: 'And shipping?' },
    { id: '4', sender: 'assistant', text: 'Partial answ', stopped: true },
    { id: '5', sender: 'assistant', text: '   ' },
  ];
  const md = buildMarkdown('Refunds', messages, ['policy.pdf'], new Date('2026-03-05T10:00:00Z'));

  it('has a title, date and scope', () => {
    expect(md.startsWith('# Refunds\n')).toBe(true);
    expect(md).toContain('Exported from DocuQuery on 2026-03-05');
    expect(md).toContain('Sources: policy.pdf');
  });
  it('lists questions and answers in order', () => {
    expect(md.indexOf('What is the refund window?')).toBeLessThan(md.indexOf('Returns are accepted'));
    expect(md.indexOf('Returns are accepted')).toBeLessThan(md.indexOf('And shipping?'));
  });
  it('de-duplicates cited pages and sorts them', () => {
    expect(md).toContain('> **Sources:** policy.pdf (p. 1, 3); faq.docx (p. 2)');
  });
  it('notes stopped generations and skips empty messages', () => {
    expect(md).toContain('Generation was stopped');
    expect(md.match(/### DocuQuery/g)).toHaveLength(2);
  });
  it('says "all documents" when no scope is selected', () => {
    expect(buildMarkdown('T', [], [])).toContain('Sources: all documents');
  });
});

describe('plainText', () => {
  it('strips Markdown for previews', async () => {
    const { plainText } = await import('./format');
    expect(plainText('Returns within **30 days**.\n\n- Items must be _unused_\n| Item | Yes |\n|---|---|')).toBe(
      'Returns within 30 days. Items must be unused Item Yes',
    );
    expect(plainText('# Title\n> quote with `code` and [a link](https://x.y)')).toBe('Title quote with code and a link');
  });
});

describe('getSuggestions', () => {
  it('never repeats a question', async () => {
    const { getSuggestions } = await import('./suggestions');
    const doc = (filename: string) => ({
      id: filename, filename, file_type: 'txt' as const, size_bytes: 1, page_count: 1, chunks_count: 1,
      summary: null, suggested_questions: ['Same question?', 'same question? '], source_url: null, tags: [], folder: null, created_at: '',
    });
    expect(getSuggestions([doc('a'), doc('b')], [], null).questions).toEqual(['Same question?']);
  });
});

describe('plainText on server snippets (already joined into one line)', () => {
  it('drops list dashes that are no longer at the start of a line', async () => {
    const { plainText } = await import('./format');
    expect(plainText('…of purchase. - Items must be unused - Shipping costs')).toBe('…of purchase. Items must be unused Shipping costs');
    expect(plainText('a well-known - and long - text')).toBe('a well-known and long text');
  });
});

describe('plainText on joined table rows', () => {
  it('drops table separator rows even mid-line', async () => {
    const { plainText } = await import('./format');
    expect(plainText('| Topic | 2025 | 2026 | | :--- | --- | ---: | | Vacation | 20 days | 25 days |')).toBe(
      'Topic 2025 2026 Vacation 20 days 25 days',
    );
  });
});
