/** Hand-written companions to the generated types. */
import type { ApiTypes } from './types'

export type * from './types'
/** Every event the agent can emit, discriminated by `type`. */
export type Event = ApiTypes['event']
