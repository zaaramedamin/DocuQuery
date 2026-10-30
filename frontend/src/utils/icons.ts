/** Icon for each kind of source. */

import { FileText, Globe, Image as ImageIcon, Presentation, Sheet } from 'lucide-react';
import type { FileType } from '../types';

export const TYPE_ICONS: Record<FileType, typeof FileText> = {
  pdf: FileText,
  docx: FileText,
  pptx: Presentation,
  xlsx: Sheet,
  csv: Sheet,
  txt: FileText,
  md: FileText,
  image: ImageIcon,
  url: Globe,
};
