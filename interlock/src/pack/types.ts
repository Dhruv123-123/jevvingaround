import type { QuestionType, VerdictLevel } from "../core/types.js";

/** A Question Pack as written on disk. See docs/packs.md and schema/pack.schema.json. */
export interface PackFile {
  pack: string;
  version: number;
  surface: string;
  description?: string;
  extends?: string[];
  l0?: Array<{ flag: string; level: "confirm" | "block" }>;
  questions: PackQuestion[];
  thresholds?: Record<string, Partial<Record<"nudge" | "hold" | "confirm" | "block", number>>>;
  tests?: PackTest[];
}

export interface PackQuestion {
  id: string;
  type: QuestionType;
  instructions: string;
  criteria: Record<string, string | null> | string[];
  thresholds?: Partial<Record<"nudge" | "hold" | "confirm" | "block", number>>;
  reason?: string;
  weight?: number;
}

export interface PackTest {
  name: string;
  /** inline state or a path relative to the pack file */
  state: unknown;
  expect: {
    level: VerdictLevel | VerdictLevel[];
    fires?: string[];
    not_fires?: string[];
  };
  /** true when the expectation depends on the model; skipped under the `none` sensor */
  requires_sensor?: boolean;
}
