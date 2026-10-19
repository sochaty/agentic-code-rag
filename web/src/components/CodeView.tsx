import { useEffect, useState } from 'react'
import type { HighlighterCore } from 'shiki/core'

import { Skeleton } from '@/components/ui/skeleton'

// One highlighter for the whole app, created on first use. The core build plus per-language
// loaders keeps the other ~200 grammars out of the bundle, and each grammar is fetched only
// when a citation in that language is first opened (rst alone is 1.5 MB).
let highlighter: Promise<HighlighterCore> | null = null
const LANGS: Record<string, () => Promise<unknown>> = {
  python: () => import('shiki/langs/python.mjs'),
  rst: () => import('shiki/langs/rst.mjs'),
  markdown: () => import('shiki/langs/markdown.mjs'),
  toml: () => import('shiki/langs/toml.mjs'),
  json: () => import('shiki/langs/json.mjs'),
  html: () => import('shiki/langs/html.mjs'),
  yaml: () => import('shiki/langs/yaml.mjs'),
  ini: () => import('shiki/langs/ini.mjs'),
  shellscript: () => import('shiki/langs/shellscript.mjs'),
}

async function getHighlighter(language: string): Promise<[HighlighterCore, string]> {
  highlighter ??= Promise.all([import('shiki/core'), import('shiki/engine/javascript')]).then(
    ([{ createHighlighterCore }, { createJavaScriptRegexEngine }]) =>
      createHighlighterCore({
        themes: [import('shiki/themes/github-light.mjs'), import('shiki/themes/github-dark.mjs')],
        engine: createJavaScriptRegexEngine(),
      }),
  )
  const h = await highlighter
  const load = LANGS[language]
  if (!load) return [h, 'text']
  if (!h.getLoadedLanguages().includes(language)) {
    await h.loadLanguage((await load()) as Parameters<HighlighterCore['loadLanguage']>[0])
  }
  return [h, language]
}

interface Props {
  code: string
  language: string
  firstLine: number
  highlight?: [number, number] // inclusive line range to mark as cited
}

/** Syntax-highlighted source with real line numbers and the cited lines marked. */
export function CodeView({ code, language, firstLine, highlight }: Props) {
  const [html, setHtml] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getHighlighter(language).then(([h, lang]) => {
      if (cancelled) return
      setHtml(
        h.codeToHtml(code, {
          lang,
          themes: { light: 'github-light', dark: 'github-dark' },
          defaultColor: false,
          transformers: [
            {
              line(node, index) {
                const number = firstLine + index - 1
                node.properties['data-line'] = number
                if (highlight && number >= highlight[0] && number <= highlight[1]) {
                  this.addClassToHast(node, 'cited')
                }
              },
            },
          ],
        }),
      )
    })
    return () => {
      cancelled = true
    }
  }, [code, language, firstLine, highlight])

  if (html === null) return <Skeleton className="h-64 w-full" />
  // Shiki output is generated from repository text it escapes itself; nothing here is user HTML.
  return <div className="code-view text-xs" dangerouslySetInnerHTML={{ __html: html }} />
}
