const [, , plugin, text] = process.argv;
let r = null;
try {
  const m = await import("file://" + plugin);
  if (typeof m.handleRapido === "function") r = await m.handleRapido(text);
} catch (e) { r = null; }
console.log("JXR " + JSON.stringify(typeof r === "string" ? r : null));
process.exit(0);
