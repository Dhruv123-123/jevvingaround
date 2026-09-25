import type { Settings } from "../core/types.js";
import { jevSensor } from "./jev.js";
import { llmSensor } from "./llm.js";
import { noneSensor } from "./none.js";
import type { Sensor } from "./types.js";

export type { Sensor, SensorResult } from "./types.js";
export { jevSensor, llmSensor, noneSensor };

/** `--sensor none|jev|llm`, else INTERLOCK_SENSOR, else jev when a key exists, else none. `llm` reads LLM_BASE_URL, LLM_API_KEY, LLM_MODEL. */
export function sensorFor(settings: Settings, name?: string): Sensor {
  const pick = name ?? process.env.INTERLOCK_SENSOR ?? (settings.apiKey ? "jev" : "none");
  if (pick === "none") return noneSensor;
  if (pick === "jev") {
    if (!settings.apiKey) throw new Error("sensor jev needs an API key (JEV_API_KEY or `interlock config --key`)");
    return jevSensor({ apiKey: settings.apiKey, baseUrl: settings.baseUrl, model: settings.model });
  }
  if (pick === "llm") {
    const apiKey = process.env.LLM_API_KEY ?? "";
    const model = process.env.LLM_MODEL;
    if (!model) throw new Error("sensor llm needs LLM_MODEL (and LLM_BASE_URL, LLM_API_KEY for a hosted endpoint)");
    return llmSensor({ apiKey, baseUrl: process.env.LLM_BASE_URL ?? "https://api.openai.com/v1", model });
  }
  throw new Error(`unknown sensor "${pick}" (jev | llm | none)`);
}
