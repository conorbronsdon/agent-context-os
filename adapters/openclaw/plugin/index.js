import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { registerContextOsSurfaces } from "./lib.js";

export default definePluginEntry({
  id: "context-os",
  name: "Agent Context OS",
  description: "Runs Context OS lifecycle work in an operator-configured repository cwd.",
  register(api) {
    registerContextOsSurfaces(api);
  }
});
