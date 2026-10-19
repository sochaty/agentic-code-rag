import { useEffect, useMemo, useRef, useState } from 'react'

import type { Event } from '@/api/model'
import { replay, type RunState } from '@/state/run'

export interface Track {
  events: Event[] // empty for the naive baseline, which emits no events
  duration: number // seconds the run took
}

const FRAME_MS = 100

/** Each track as it stood `clock` seconds in; `null` = finished. Exported for tests. */
export function statesAt(tracks: Track[], clock: number | null): RunState[] {
  return tracks.map((t) => replay(clock === null ? t.events : t.events.filter((e) => (e.at ?? 0) <= clock)))
}

/**
 * Plays several runs back on one shared clock, so the reader sees which answer arrives first.
 * Every event carries `at` (seconds since its run started); a track's state at clock t is the
 * replay of the events with at <= t. While stopped, every track shows its finished state.
 */
export function usePlayback(tracks: Track[], speed = 4) {
  const [clock, setClock] = useState<number | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const end = Math.max(0, ...tracks.map((t) => t.duration))

  function stop() {
    window.clearInterval(timer.current)
    setClock(null)
  }

  function play() {
    window.clearInterval(timer.current)
    const started = performance.now()
    setClock(0)
    timer.current = window.setInterval(() => {
      const now = ((performance.now() - started) / 1000) * speed
      if (now >= end) stop()
      else setClock(now)
    }, FRAME_MS)
  }

  useEffect(() => () => window.clearInterval(timer.current), [])

  const states = useMemo(() => statesAt(tracks, clock), [tracks, clock])
  const done = tracks.map((t) => clock === null || clock >= t.duration)
  return { states, done, clock, end, playing: clock !== null, play, stop }
}
