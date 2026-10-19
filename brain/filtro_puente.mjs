import { readFileSync } from "node:fs";
const plugin = process.argv[2];
let out = { kind: "undefined", v: null };
try {
  const inp = JSON.parse(readFileSync(0, "utf8") || "{}");
  const m = await import("file://" + plugin);
  if (typeof m.claimControl !== "function") throw new Error("sin claimControl");
  const r = await m.claimControl(inp.text, { chatId: inp.chatId, messageId: inp.messageId });
  out = { kind: r === null ? "null" : typeof r, v: typeof r === "string" || (r && typeof r === "object") ? r : null };
} catch (e) { out = { kind: "error", v: String((e && e.message) || e).slice(0, 200) }; }
console.log("JXR " + JSON.stringify(out));
process.exit(0);
