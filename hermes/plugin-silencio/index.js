import { execFile as _jxExecFile, spawn as _jxSpawn } from "node:child_process";
import _jxNet from "node:net";
import _jxFs from "node:fs";
import _jxCrypto from "node:crypto";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { connect } from "node:net";

// Rutas fijas. NUNCA se envian al chat (solo uso interno + logs del servidor).
const GATE = "{{HOME}}/jarvis-control/jarvis_gate.py";
const TOKEN_FILE = "{{HOME}}/.openclaw/telegram-token";
const CONFIG_FILE = "{{HOME}}/.openclaw/openclaw.json";
const PC_HOST = "{{PC_IP}}";
const PC_PORT = 11434;

const MSG_UNLOCKED = "Modo seguro activado, señor";
const MSG_LOCKED = "Sistema bloqueado. Contacta al administrador.";
const MSG_CLOSED = "Modo seguro desactivado, señor.";
const MSG_NEUTRAL = "Recibido, señor. Lo gestiono en silencio.";
const MSG_WRONG = "Palabra incorrecta, señor.";
const MSG_LONG = "Disculpe, señor, esta conversación se ha hecho demasiado larga para mí. Toque /new y seguimos desde cero.";
const MSG_BUSY = "Ahora mismo estoy saturado, señor. Inténtelo de nuevo en un minuto.";

function isProviderError(text) {
  return /API error|RESOURCE_EXHAUSTED|exceeded your current quota|rate.?limit|quota exceeded|\(4\d\d\)|\(5\d\d\)|status=4\d\d|billing details|ai\.google\.dev|console\.groq|openrouter\.ai|Too Many Requests/i.test(text);
}

function runGate(args, timeoutMs = 25000) {
  return new Promise((resolve) => {
    execFile("python3", [GATE, ...args], { timeout: timeoutMs }, (err, stdout) => {
      if (err && !String(stdout || "").trim()) {
        resolve({ ok: false, error: String(err).slice(0, 200) });
        return;
      }
      try {
        resolve({ ok: true, data: JSON.parse(String(stdout)) });
      } catch (e) {
        resolve({ ok: false, error: "bad-json" });
      }
    });
  });
}

// Respuesta natural a partir del resultado del gate. Nunca incluye la
// palabra candidata, rutas, comandos ni JSON.
function replyForGateResult(r) {
  if (!r.ok) return null; // fallo interno: ceder al flujo normal
  const d = r.data || {};
  if (d.status === "unlocked") return MSG_UNLOCKED;
  if (d.status === "locked") return MSG_LOCKED;
  if (d.status === "wrong") return MSG_WRONG;
  return null;
}

async function tgDeleteMessage(chatId, messageId) {
  try {
    if (!/^\d+$/.test(String(chatId)) || !/^\d+$/.test(String(messageId))) return false;
    const token = (await readFile(TOKEN_FILE, "utf8")).trim();
    if (!token) return false;
    const res = await fetch(`https://api.telegram.org/bot${token}/deleteMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, message_id: Number(messageId) }),
      signal: AbortSignal.timeout(10000),
    });
    const j = await res.json().catch(() => ({}));
    return j.ok === true;
  } catch {
    return false;
  }
}

function cleanText(raw) {
  return String(raw ?? "").trim();
}

function normalizarChatId(rawId) {
  const id = String(rawId ?? "");
  return id.replace(/^telegram:/i, "");
}

function parseControl(raw) {
  const t = cleanText(raw);
  if (!t) return null;
  // "jarvis <palabra>" — exige espacio tras jarvis.
  let m = t.match(/^jarvis\s+(\S[\s\S]*?)\s*$/i);
  if (m) {
    let cand = m[1].trim().replace(/^["'«»“”]+|["'«»“”]+$/g, "").trim();
    if (cand) return { kind: "jarvis", candidate: cand };
    return null; // "jarvis" solo: flujo normal
  }
  if (/^cerrar jarvis\s*[.!]?$/i.test(t)) return { kind: "cerrar" };
  if (/^estado\s*[.!]?$/i.test(t)) return { kind: "estado" };
  return null;
}

async function borrarSiSePuede(chatId, messageId) {
  if (chatId && messageId && /^\d+$/.test(String(chatId)) && /^\d+$/.test(String(messageId))) {
    await tgDeleteMessage(chatId, messageId).catch(() => {});
  }
}

async function handleJarvis(candidate, chatId, messageId) {
  const r = await runGate(["test-flow", String(chatId), String(messageId), candidate]);
  const reply = replyForGateResult(r);
  if (reply === null) return undefined; // error interno: no reclamar, dejar pasar
  // Borrar siempre el mensaje del usuario (comando de control). Silencioso.
  await borrarSiSePuede(chatId, messageId);
  _auditLocal("JARVIS_CMD", `status=${r.data?.status} deleted`);
  return reply;
}

async function handleCerrar(chatId, messageId) {
  await runGate(["close", String(chatId || "")]);
  await borrarSiSePuede(chatId, messageId);
  _auditLocal("CERRAR", `chat=${chatId}`);
  return MSG_CLOSED;
}

function fmtUptime(secs) {
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d} día${d === 1 ? "" : "s"} y ${h} hora${h === 1 ? "" : "s"}`;
  if (h > 0) return `${h} hora${h === 1 ? "" : "s"} y ${m} minuto${m === 1 ? "" : "s"}`;
  return `${m} minuto${m === 1 ? "" : "s"}`;
}

function readFirst(path) {
  return readFile(path, "utf8").then((s) => s.trim()).catch(() => "");
}

function pcAwake(timeoutMs = 3000) {
  return new Promise((resolve) => {
    const s = connect({ host: PC_HOST, port: PC_PORT });
    const done = (v) => {
      try { s.destroy(); } catch {}
      resolve(v);
    };
    s.setTimeout(timeoutMs);
    s.on("connect", () => done(true));
    s.on("timeout", () => done(false));
    s.on("error", () => done(false));
  });
}

function execQuick(cmd, args, timeoutMs = 8000) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout: timeoutMs }, (err, stdout) => {
      resolve(err ? "" : String(stdout || "").trim());
    });
  });
}

async function handleEstado(chatId, messageId) {
  await borrarSiSePuede(chatId, messageId);
  try {
    const [upRaw, memRaw, tempRaw] = await Promise.all([
      readFirst("/proc/uptime"),
      readFirst("/proc/meminfo"),
      readFirst("/sys/class/thermal/thermal_zone0/temp"),
    ]);
    const upSecs = parseInt((upRaw.split(/\s+/)[0] || "0"), 10) || 0;
    const memMatch = memRaw.match(/MemAvailable:\s+(\d+)\s+kB/);
    const gbFree = memMatch ? (parseInt(memMatch[1], 10) / 1024 / 1024).toFixed(1).replace(".", ",") : null;
    const tempC = /^\d+$/.test(tempRaw) ? Math.round(parseInt(tempRaw, 10) / 1000) : null;

    const svcs = ["jarvis-oj", "jarvis2", "jarvis-v2", "hermes-gateway", "ollama"];
    const states = await Promise.all(
      svcs.map((s) => execQuick("systemctl", s === "hermes-gateway" ? ["--user", "is-active", `${s}.service`] : ["is-active", `${s}.service`])),
    );
    const down = svcs.filter((_, i) => states[i] !== "active");
    const pc = await pcAwake();

    let cfgModel = "";
    try {
      const hy = await readFile("{{HOME}}/.hermes/config.yaml", "utf8");
      const mm = hy.match(/^model:\s*\n(?:[ \t]+.*\n)*?[ \t]+default:\s*["']?([^\s"'#]+)/m);
      cfgModel = mm ? mm[1] : "";
    } catch {}
    const modelId = cfgModel.includes("/") ? cfgModel.split("/").pop() : cfgModel;
    const mh = modelId.match(/^claude-(haiku|sonnet|opus|fable)-(\d+)-(\d+)/i);
    const modelShort = mh ? `Claude ${mh[1][0].toUpperCase()}${mh[1].slice(1)} ${mh[2]}.${mh[3]}` : modelId;

    const partes = [];
    partes.push(`Todo en orden, señor. Llevo ${fmtUptime(upSecs)} encendida`);
    if (gbFree) partes.push(`con ${gbFree} GB libres`);
    if (tempC !== null) partes.push(`y ${tempC} grados`);
    let frase = partes.join(" ") + ".";
    frase += down.length === 0
      ? " Los cinco servicios están activos."
      : ` Atención: ${down.length} servicio${down.length === 1 ? "" : "s"} caído${down.length === 1 ? "" : "s"}.`;
    frase += pc ? " El PC responde." : " El PC está apagado o sin respuesta.";
    if (modelShort) frase += ` Le atiende ${modelShort}.`;
    _auditLocal("ESTADO", `down=${down.length}`);
    return frase;
  } catch {
    return "Todo en orden, señor. No he podido leer el detalle esta vez.";
  }
}

// Log local silencioso (nunca al chat).
function _auditLocal(action, detail) {
  try {
    const fs = require("node:fs");
    const line = `${new Date().toISOString()} ${action} ${detail}\n`;
    fs.appendFileSync("{{HOME}}/jarvis-control/audit.log", line);
  } catch {}
}

// ---- Filtro global de salida ----

const RESUME_RES = [
  /continuing your interrupted request/i,
  /gateway has just restarted/i,
  /interrupted request/i,
  /resuming/i,
  /system.*(restart|reiniciad)/i,
  /gateway.*(back|online|ready|vuelve|listo)/i,
  /i.?m.?back/i,
  /estoy de vuelta/i,
  /servicio.*reiniciado/i,
  /se ha reiniciado/i,
];

function isResumeNoise(text) {
  return RESUME_RES.some((re) => re.test(text));
}

// Fuga = comando crudo, ejecutor, script interno, ruta de archivo, JSON o comando jarvis.
function isLeak(text) {
  const t = text.trimStart();
  if (t.startsWith("!")) return true;
  if (/^\s*[\{\[]/.test(text) && /"(status|locked|unlocked|fails|message_deleted|attempts_remaining|result|stdout|stderr)"/.test(text)) return true;
  if (/python3|jarvis_gate\.py|pc_do\.py|test-flow|verify |activate |cerrar jarvis|\.py\b/.test(t)) return true;
  if (/\/home\/|\/root\/|[A-Za-z]:\\|\/[A-Za-z]:/.test(t)) return true;
  if (/jarvis\s+\S/i.test(t)) return true; // "jarvis <cosa>" nunca debe salir al chat
  return false;
}

// Devuelve: "pass" | "cancel" | { replace: string }
function sanitizeOutbound(text) {
  const t = String(text ?? "");
  if (!t.trim()) return "pass";
  if (isResumeNoise(t)) return "cancel";
  if (/auto-compaction|context overflow|prompt too large|request too large|\/compact\b/i.test(t)) return { replace: MSG_LONG };
  if (isProviderError(t)) return { replace: MSG_BUSY };
  if (isLeak(t)) return { replace: MSG_NEUTRAL };
  return "pass";
}

// --- Ordenes rapidas sin IA (arreglo 7) ---
const JX_PY = "{{HOME}}/jarvis2/scripts";
const JX_GATE = ["{{HOME}}/jarvis-control/jarvis_gate.py", "{{HOME}}/jarvis2/scripts/jarvis_gate.py"].find((p) => _jxFs.existsSync(p));
const JX_ASLEEP = "El PC está apagado, señor. Dígame «enciende el PC» y lo despierto.";
const JX_EXCLUDE = /(ojo de dios|gods?.?eye|maigret|harvester|herramienta|yt.?dlp|gallery|juego|jarvis|conversacion|sesion|modo seguro|archivo|carpeta|http|www\.|pagina|web|enlace|\?)/;
const JX_PC = "(?:\\s+(?:en|del)\\s+(?:el\\s+)?(?:pc|ordenador|computador|computadora))?";
const JX_BAD = /traceback|"ok"\s*:\s*false/i;

function parseRapido(raw) {
  let t = String(cleanText(raw) || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  t = t.replace(/[¡!¿.,;:]+$/g, "").replace(/\s+por favor$/, "").trim();
  const conJarvis = /^(?:oye\s+|hey\s+)?jarvis[\s,:.!]+/.test(t);
  t = t.replace(/^(?:oye\s+|hey\s+)?jarvis[\s,:.!]+/, "").replace(/^por favor\s+/, "").replace(/[¡!¿.,;:]+$/g, "").trim();
  if (!t || t.length > 60) return null;
  if (conJarvis && !/\s/.test(t)) return null; // "jarvis <una palabra>" es siempre la palabra clave
  let m;
  if (/^(?:enciende|prende|despierta|arranca)\s+(?:el\s+|mi\s+)?(?:pc|ordenador|computador|computadora)$/.test(t)) return { op: "wake" };
  if ((m = t.match(/^(apaga|reinicia|suspende)\s+(?:el\s+|mi\s+)?(?:pc|ordenador|computador|computadora)$/))) return { op: "power", act: { apaga: "shutdown", reinicia: "restart", suspende: "suspend" }[m[1]] };
  if ((m = t.match(new RegExp("^(?:pon\\s+|sube\\s+|baja\\s+)?(?:el\\s+)?volumen\\s+(?:al?\\s+|en\\s+)?(\\d{1,3})\\s*(?:%|por ciento)?" + JX_PC + "$")))) {
    const n = Math.min(100, parseInt(m[1], 10));
    return { op: "pc", args: ["volume", String(n)], ok: `Volumen al ${n} %, señor.`, fail: "No he podido cambiar el volumen, señor." };
  }
  if (/^(?:silencia(?:\s+el\s+(?:pc|ordenador))?|silencio|mute|quita el sonido)$/.test(t)) return { op: "pc", args: ["volume", "mute"], ok: "PC silenciado, señor.", fail: "No he podido silenciar el PC, señor." };
  if (/^(?:quita el silencio|unmute|activa el sonido|pon el sonido)$/.test(t)) return { op: "pc", args: ["volume", "unmute"], ok: "Sonido activado, señor.", fail: "No he podido activar el sonido, señor." };
  if (/^(?:abre|abreme|ejecuta|inicia|lanza)\s+(?:el\s+)?(?:ojo de dios|gods?.?eye(?:.?view)?)(?:\s+(?:en|del)\s+(?:el\s+)?(?:pc|ordenador))?$/.test(t)) return { op: "pc", args: ["open", "{{WIN_HOME_ESC}}\\herramientas\\gods-eye-view\\abrir-gods-eye.bat"], ok: "Abriendo el Ojo de Dios en el PC, señor.", fail: "No he podido abrir el Ojo de Dios, señor." };
  if ((m = t.match(new RegExp("^(abre|abreme|ejecuta|inicia|cierra|cierrame)\\s+(?:el\\s+|la\\s+|los\\s+|las\\s+)?(.+?)" + JX_PC + "$")))) {
    const name = m[2].trim();
    if (!name || JX_EXCLUDE.test(name) || name.split(/\s+/).length > 4) return null;
    const open = !m[1].startsWith("cierra");
    return { op: "pc", args: [open ? "open" : "close", name],
      ok: open ? `Listo, señor. He abierto ${name}.` : `Listo, señor. He cerrado ${name}.`,
      fail: open ? `No he podido abrir ${name}, señor.` : `No he podido cerrar ${name}, señor.` };
  }
  return null;
}

function _jxRun(file, args, timeoutMs) {
  return new Promise((res) => {
    _jxExecFile("python3", [file, ...args], { timeout: timeoutMs, env: process.env }, (err, stdout, stderr) => {
      res({ code: err ? (typeof err.code === "number" ? err.code : 1) : 0, out: String(stdout || "") + String(stderr || "") });
    });
  });
}

function _jxAwake(timeoutMs = 1500) {
  const tryPort = (port) => new Promise((res) => {
    const s = _jxNet.createConnection({ host: "{{PC_IP}}", port });
    const done = (v) => { s.destroy(); res(v); };
    s.setTimeout(timeoutMs, () => done(false));
    s.once("connect", () => done(true));
    s.once("error", () => done(false));
  });
  return Promise.all([tryPort(8765), tryPort(11434)]).then((r) => r.some(Boolean));
}

async function handleRapido(raw) {
  const r = parseRapido(raw);
  if (!r) return undefined;
  try { _auditLocal("rapido", `${r.op} ${(r.args || [r.act || ""]).join(" ")}`); } catch {}
  const awake = await _jxAwake();
  if (r.op === "wake") {
    if (awake) return "El PC ya está encendido, señor.";
    const c = _jxSpawn("python3", [`${JX_PY}/wake_pc.py`], { detached: true, stdio: "ignore", env: process.env });
    c.on("error", () => {});
    c.unref();
    return "Encendiendo el PC, señor. En un minuto lo tiene listo.";
  }
  if (r.op === "power") {
    if (!awake) return r.act === "shutdown" ? "El PC ya está apagado, señor." : JX_ASLEEP;
    if (!JX_GATE) return undefined;
    const g = await _jxRun(JX_GATE, ["check-high"], 10000);
    if (!/^\s*OK\b/m.test(g.out)) return "Esto necesita su palabra clave, señor.";
    const p = await _jxRun(`${JX_PY}/pc_do.py`, [r.act, "--yes"], 25000);
    if (p.code !== 0 || JX_BAD.test(p.out)) return "No he podido hacerlo, señor. El PC no ha respondido.";
    return { shutdown: "Apagando el PC, señor.", restart: "Reiniciando el PC, señor.", suspend: "Suspendiendo el PC, señor." }[r.act];
  }
  if (!awake) return JX_ASLEEP;
  const p = await _jxRun(`${JX_PY}/pc_do.py`, r.args, 25000);
  if (p.code !== 0 || JX_BAD.test(p.out)) return r.fail;
  return r.ok;
}
function cleanChatId(chatId) {
  if (!chatId) return "";
  const m = String(chatId).match(/(\d+)/);
  return m ? m[1] : "";
}

function _jxFirmaVB(ms) {
  // arreglo 86: visto bueno firmado (HMAC-SHA256 con ~/.config/jarvis/firma.key)
  const k = _jxFs.readFileSync("{{HOME}}/.config/jarvis/firma.key", "utf8").trim();
  return _jxCrypto.createHmac("sha256", k).update(ms).digest("hex");
}

function jxMarcarVistoBueno(raw) {
  const t = String(cleanText(raw) || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
  if (/^(si|vale|ok|okay|dale|adelante|de acuerdo|confirmo|confirmado|envialo|mandalo|hazlo|publicalo)\b/.test(t) && t.length < 60) {
    try { const ms = String(Date.now()); _jxFs.writeFileSync("{{HOME}}/jarvis-control/.visto-bueno", ms + ":" + _jxFirmaVB(ms)); } catch {}
  }
}

async function claimControl(raw, ids) {
  jxMarcarVistoBueno(raw);
  const jxT = cleanText(raw);
  const jxChat = cleanChatId(ids.chatId);
  const jxMsg = cleanChatId(ids.messageId);
  // Palabra clave escrita sola: no debe llegar nunca a la IA.
  if (JX_GATE && /^\S{4,64}$/.test(jxT) && !jxT.startsWith("/")) {
    const v = await _jxRun(JX_GATE, ["verify", jxT], 15000);
    if (/^\s*OK\b/m.test(v.out)) return handleJarvis(jxT, jxChat, jxMsg);
  }
  const rap = await handleRapido(raw);
  if (rap !== undefined) return rap;
  // "jarvis <orden> <palabra>": abre el modo seguro y hace la orden de una vez.
  const jxM = jxT.match(/^jarvis[\s,:]+(\S[\s\S]*?)\s*$/i);
  if (JX_GATE && jxM && /\s/.test(jxM[1])) {
    const words = jxM[1].split(/\s+/);
    const cand = words[words.length - 1].replace(/^[("'«»“”]+|[)"'«»“”.,;:!?]+$/g, "");
    const rest = words.slice(0, -1).join(" ");
    const cmd = parseRapido(rest);
    if (cmd && cmd.op === "power" && cand) {
      const r = await runGate(["test-flow", String(jxChat), String(jxMsg), cand]);
      await borrarSiSePuede(jxChat, jxMsg);
      if (r.ok && r.data?.status === "unlocked") return (await handleRapido(rest)) ?? MSG_UNLOCKED;
      return replyForGateResult(r) ?? MSG_WRONG;
    }
    // Una frase normal con "jarvis" delante no es un intento de palabra clave.
    const v = await _jxRun(JX_GATE, ["verify", jxM[1]], 15000);
    if (!/^\s*OK\b/m.test(v.out)) return undefined;
  }
  const ctl = parseControl(raw);
  if (!ctl) return undefined;
  const chatId = cleanChatId(ids.chatId);
  const messageId = cleanChatId(ids.messageId);
  if (ctl.kind === "jarvis") return handleJarvis(ctl.candidate, chatId, messageId);
  if (ctl.kind === "cerrar") return handleCerrar(chatId, messageId);
  if (ctl.kind === "estado") return handleEstado(chatId, messageId);
  return undefined;
}

export { parseRapido, isProviderError, parseControl, sanitizeOutbound, replyForGateResult, isLeak, isResumeNoise };

export default definePluginEntry({
  id: "jarvis-silencio",
  name: "JARVIS Silencio",
  description: "Control silencioso + filtro anti-fuga.",
  register(api) {
    // 1. Intercepcion determinista ANTES del LLM.
    api.on("before_dispatch", async (event) => {
      try {
        const raw = event.body ?? event.content ?? "";
        const reply = await claimControl(raw, {
          chatId: normalizarChatId(event.senderId ?? ""),
          messageId: event.messageId ?? "",
        });
        if (reply !== undefined) return { handled: true, text: reply };
      } catch (e) {
        console.error("[jarvis-silencio] before_dispatch:", String(e).slice(0, 200));
      }
    }, { timeoutMs: 40000 });

    // Respaldo por si alguna via omite before_dispatch.
    api.on("before_agent_reply", async (event) => {
      try {
        const reply = await claimControl(event.cleanedBody ?? "", { chatId: normalizarChatId(event.senderId ?? ""), messageId: "0" });
        if (reply !== undefined) return { handled: true, reply: { text: reply } };
      } catch (e) {
        console.error("[jarvis-silencio] before_agent_reply:", String(e).slice(0, 200));
      }
    }, { eligibleTriggers: ["user"], timeoutMs: 40000 });

    // 2. Filtro global de salida (cinturon y tirantes).
    api.on("message_sending", async (event) => {
      try {
        const r = sanitizeOutbound(event.content ?? "");
        if (r === "cancel") return { cancel: true, cancelReason: "jarvis-silencio: aviso interno suprimido" };
        if (typeof r === "object") return { content: r.replace };
      } catch (e) {
        console.error("[jarvis-silencio] message_sending:", String(e).slice(0, 200));
      }
    }, { timeoutMs: 15000 });

    api.on("reply_payload_sending", async (event) => {
      try {
        const text = event.payload?.text ?? "";
        const r = sanitizeOutbound(text);
        if (r === "cancel") return { cancel: true, reason: "jarvis-silencio: aviso interno suprimido" };
        if (typeof r === "object") {
          return { payload: { ...event.payload, text: r.replace } };
        }
      } catch (e) {
        console.error("[jarvis-silencio] reply_payload_sending:", String(e).slice(0, 200));
      }
    }, { timeoutMs: 15000 });
  },
});
export { handleRapido }; // arreglo 17: la voz usa las mismas ordenes rapidas
export { claimControl }; // arreglo 27: Hermes usa el mismo filtro
