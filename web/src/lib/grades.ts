/** How the judge's grades look everywhere in the eval views. */
export const GRADES = [
  { grade: 'correct', label: 'Correct', swatch: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400' },
  { grade: 'partial', label: 'Partial', swatch: 'bg-amber-400', text: 'text-amber-600 dark:text-amber-400' },
  { grade: 'incorrect', label: 'Incorrect', swatch: 'bg-rose-500', text: 'text-rose-600 dark:text-rose-400' },
  { grade: 'abstained', label: 'Abstained', swatch: 'bg-zinc-400', text: 'text-zinc-500' },
  { grade: 'error', label: 'Error', swatch: 'bg-fuchsia-500', text: 'text-fuchsia-600' },
] as const

export function gradeStyle(grade: string) {
  return GRADES.find((g) => g.grade === grade) ?? GRADES[GRADES.length - 1]
}

export const CATEGORY_LABELS: Record<string, string> = {
  lookup: 'Lookup',
  conceptual: 'Conceptual',
  identifier: 'Identifier',
  call_graph: 'Call graph',
  history: 'History',
  existence: 'Existence',
  multi_part: 'Multi-part',
}

export const SPLIT_LABELS: Record<string, string> = {
  fresh: 'Fresh',
  heldout: 'Held-out',
  dev: 'Dev',
  all: 'All',
}
