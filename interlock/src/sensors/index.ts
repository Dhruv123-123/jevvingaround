import type { Settings } from "../core/types.js";
import { jevSensor } from "./jev.js";
import { noneSensor } from "./none.js";
import type { Sensor } from "./types.js";

export type { Sensor, SensorResult } from "./types.js";
export { jevSensor, noneSensor };

/** `--sensor none|jev`, else INTERLOCK_SENSOR, else jev when a key exists, else none. */
export function sensorFor(settings: Settings, name?: string): Sensor {
  const pick = name ?? process.env.INTERLOCK_SENSOR ?? (settings.apiKey ? "jev" : "none");
  if (pick === "none") return noneSensor;
  if (pick === "jev") {
    if (!settings.apiKey) throw new Error("sensor jev needs an API key (JEV_API_KEY or `interlock config --key`)");
    return jevSensor({ apiKey: settings.apiKey, baseUrl: settings.baseUrl, model: settings.model });
  }
  throw new Error(`unknown sensor "${pick}" (jev | none)`);
}
