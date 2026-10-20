/**
 * Model-written markdown often names Python dunders without backticks, and markdown then reads
 * `AppContext.__init__` as "AppContext.**init**". Wrap such identifiers in backticks, leaving
 * code spans and fenced blocks alone.
 */
const DUNDER = /(?<![\w`])([A-Za-z_][\w.]*__\w+__[\w.]*|__\w+__)(?![\w`])/g

export function protectIdentifiers(text: string): string {
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/)
    .map((part, i) => (i % 2 === 1 ? part : part.replace(DUNDER, '`$1`')))
    .join('')
}
