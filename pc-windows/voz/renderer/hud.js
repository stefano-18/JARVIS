// logo3d.js (script clasico anterior) expone window.setReactorState; sin imports.
let ws;
const WS_URL = 'ws://{{PORTATIL_IP}}:8765';
// Fase1b: micro del HUD desactivado. La voz vive solo en jarvis-v2-fijo
// (mic_bridge.py, respeta mic_bridge.lock). Nada de este archivo debe
// pedir getUserMedia ni enviar audio.
const HUD_MIC_ENABLED = false;

// Fase3: panel de sistema (solo lectura). Estado que pinta updateSysPanel().
let sysConn = '…';
let sysLast = '—';
let sysModel = '—';
let sysOllama = '…';
let sysVram = '';

function sysEl(id) {
  try { return document.getElementById(id); } catch (e) { return null; }
}

function updateSysPanel() {
  const c = sysEl('sys-conn');
  const l = sysEl('sys-last');
  const m = sysEl('sys-model');
  const o = sysEl('sys-ollama');
  if (c) c.textContent = sysConn;
  if (l) l.textContent = String(sysLast || '—').slice(0, 140);
  if (m) m.textContent = sysModel;
  if (o) o.textContent = sysVram ? (sysOllama + ' | ' + sysVram) : sysOllama;
}

// Fase3: estado de Ollama local via API (el renderer puede leer localhost,
// Ollama permite CORS *). Sin shell, sin nvidia-smi desde aqui: la VRAM
// la aporta la laptop con mensajes gpu_info (ver SPEC abajo).
// Fase5: fallback local — si la laptop no manda gpu_info (>30 s sin ver
// uno), el panel lee la VRAM via jarvisAPI.getGpu() (main: nvidia-smi).
// No depende de la laptop; el dato de la laptop siempre manda si llega.
let lastGpuInfoAt = 0;
function pollLocalGpu() {
  try {
    if (Date.now() - lastGpuInfoAt < 30000) return; // laptop al dia: no molestar
    const api = window.jarvisAPI;
    if (!api || typeof api.getGpu !== 'function') return;
    api.getGpu().then((g) => {
      if (g && g.ok) {
        // Solo pinta local si la laptop sigue sin mandar (evita parpadeo).
        if (Date.now() - lastGpuInfoAt >= 30000) {
          sysVram = 'VRAM ' + g.used_mib + '/' + g.total_mib + ' MiB (local)';
          updateSysPanel();
        }
      }
    }).catch(() => {});
  } catch (e) { /* solo lectura, nunca tumba el HUD */ }
}
function pollOllama() {
  try {
    fetch('http://127.0.0.1:11434/api/ps').then((r) => r.json()).then((j) => {
      const ms = (j && j.models) || [];
      sysOllama = ms.length ? ('cargado: ' + ms.map((x) => x.name).join(', ')) : 'descargado';
      updateSysPanel();
    }).catch(() => {
      sysOllama = 'no responde';
      updateSysPanel();
    });
  } catch (e) {
    sysOllama = 'no responde';
    updateSysPanel();
  }
}
let mapInstance = null;
let mediaRecorder = null;
let audioChunks = [];

// --- Propiedad del sonido (fijo): el agente YA habla (playsound cine + SAPI).
// --- HUD por defecto MUDO (solo subtitulos/transcript/mapa). Opt-in: localStorage jarvis_hud_sound="1".
try {
  window.JARVIS_HUD_SOUND = localStorage.getItem('jarvis_hud_sound') || "0";
} catch (e) { window.JARVIS_HUD_SOUND = "0"; }
function hudSoundEnabled() {
  try {
    const v = (typeof window.JARVIS_HUD_SOUND !== 'undefined' && window.JARVIS_HUD_SOUND !== null)
      ? window.JARVIS_HUD_SOUND
      : localStorage.getItem('jarvis_hud_sound') || "0";
    return String(v) === "1";
  } catch (e) { return String(window.JARVIS_HUD_SOUND) === "1"; }
}
// Dedup interno: voice_result.audio UNA vez; tts_chunk 10 s siguientes ignorado (misma voz).
let lastVoiceAudioAt = 0;
let lastVoiceName = "";
let lastVoiceTs = null;

// Clock & Date Update
function updateClock() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString('es-ES', { hour12: false });
  const dateStr = now.toLocaleDateString('es-ES', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }).toUpperCase();

  const clockEl = document.getElementById('clock');
  const dateEl = document.getElementById('date');

  if (clockEl) clockEl.textContent = timeStr;
  if (dateEl) dateEl.textContent = dateStr;
}

// --- Audio nativo MediaRecorder -> WS (voice_in.py) -> brain (pc_exec fijo) ---
function sendAudioToServer() {
  if (!HUD_MIC_ENABLED) {
    console.warn('Mic del HUD desactivado (Fase1b): la voz vive en jarvis-v2-fijo.');
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    console.warn('Mic no disponible');
    return;
  }
  navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    audioChunks = [];
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = () => {
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      const reader = new FileReader();
      reader.onloadend = () => {
        const b64 = String(reader.result).split(',')[1] || '';
        if (ws && ws.readyState === WebSocket.OPEN && b64) {
          ws.send(JSON.stringify({ type: 'audio', data: b64, mime: 'audio/webm', timestamp: new Date().toISOString() }));
          setReactorState('thinking');
        }
      };
      reader.readAsDataURL(blob);
    };
    mediaRecorder.start();
    setReactorState('listening');
    setTimeout(() => { if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop(); }, 6000);
  }).catch((e) => console.warn('Mic error:', e));
}

// WebSocket Connection
function connectWebSocket() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log('WS Conectado a la Laptop');
    sysConn = '● laptop :8765';
    updateSysPanel();
    const subtitle = document.getElementById('subtitle');
    if (subtitle) subtitle.textContent = 'JARVIS conectado. Escuchando ("Hey JARVIS")...';
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerMessage(data);
    } catch (e) {
      console.log('Mensaje recibido:', event.data);
    }
  };

  ws.onclose = () => {
    console.log('WS Desconectado, reintentando en 3s...');
    sysConn = '○ reconectando…';
    updateSysPanel();
    setTimeout(connectWebSocket, 3000);
  };
}

function handleServerMessage(data) {
  if (data.type === 'state') {
    setReactorState(data.state);
  }

  if (data.type === 'mic_level') {
    updateMicBar(data.level);
  }

  if (data.type === 'transcript') {
    const sub = document.getElementById('subtitle');
    if (sub) sub.textContent = 'Tú: ' + (data.text || '');
    sysLast = 'Tú: ' + (data.text || '');
    if (data.model) sysModel = data.model;
    updateSysPanel();
    return;
  }

  if (data.type === 'voice_result') {
    const sub = document.getElementById('subtitle');
    if (sub) sub.textContent = data.reply || data.text || '';
    sysLast = data.reply || data.text || '';
    if (data.model) sysModel = data.model;
    updateSysPanel();
    // TTS británica fijada en-GB-RyanNeural: mp3 base64 en voice_result.
    // El texto se mantiene intacto para SAPI de respaldo (fijo).
    // REGLA dueno-unico: HUD mudo por defecto; solo suena si JARVIS_HUD_SOUND==="1".
    // Si suena: voice_result.audio UNA vez + marca timestamp; tts_chunk 10 s siguientes se ignora.
    if (data.audio) {
      lastVoiceAudioAt = Date.now();
      lastVoiceName = data.voice || 'en-GB-RyanNeural';
      lastVoiceTs = data.timestamp || null;
      if (hudSoundEnabled()) {
        playTTSAudio('data:' + (data.audio_mime || 'audio/mp3') + ';base64,' + data.audio, lastVoiceName);
      }
    } else if (data.reply) {
      if (hudSoundEnabled()) {
        try {
          const u = new SpeechSynthesisUtterance(stripTag(data.reply));
          u.lang = 'es-ES';
          speechSynthesis.speak(u);
        } catch (e) { /* sin SAPI */ }
      }
    }
    return;
  }

  if (data.type === 'tts_chunk' && data.data) {
    // tts_chunk separado por compatibilidad (mismo mp3 que voice_result.audio).
    // DEDUP: si llega en los 10 s siguientes a voice_result.audio con misma voz -> ignorar.
    // (Protocolo actual no trae timestamp en voice_result/tts_chunk; se compara voz +
    // ventana temporal. Si en el futuro traen data.timestamp, solo se permite si difiere.)
    if (!hudSoundEnabled()) return;
    const voice = data.voice || 'en-GB-RyanNeural';
    if (Date.now() - lastVoiceAudioAt < 10000) {
      const sameVoice = (!data.voice || !lastVoiceName || voice === lastVoiceName);
      const sameTs = (data.timestamp && lastVoiceTs && data.timestamp === lastVoiceTs);
      // Regla pedida: mismo voice/timestamp en 10 s -> ignorar (mismos bytes que voice_result.audio).
      // Sin voice/timestamp explicito se asume duplicado (protocolo actual no los trae).
      if (sameVoice || sameTs) return;
    }
    playTTSAudio('data:' + (data.mime || 'audio/mp3') + ';base64,' + data.data, voice);
    return;
  }

  if (data.type === 'subtitle' || data.text) {
    const sub = document.getElementById('subtitle');
    if (sub) sub.textContent = data.text || data.subtitle;
    if (data.text || data.subtitle) sysLast = data.text || data.subtitle;
    if (data.model) sysModel = data.model;
    updateSysPanel();
  }

  // Fase3 SPEC laptop: la laptop debe mandar estos mensajes para el panel.
  // {"type":"model_info","model":"qwen3:14b","provider":"ollama-pc"}
  // {"type":"gpu_info","vram_used_mib":8423,"vram_total_mib":12288,"model":"qwen3:14b"}
  if (data.type === 'model_info' && data.model) {
    sysModel = data.provider ? (data.model + ' (' + data.provider + ')') : data.model;
    updateSysPanel();
    return;
  }

  if (data.type === 'gpu_info') {
    if (data.vram_used_mib != null && data.vram_total_mib != null) {
      sysVram = 'VRAM ' + data.vram_used_mib + '/' + data.vram_total_mib + ' MiB';
      lastGpuInfoAt = Date.now();
    }
    if (data.model && sysModel === '—') sysModel = data.model;
    updateSysPanel();
    return;
  }

  if (data.type === 'map') {
    showHolographicMap(data.city, data.lat, data.lng);
  }

  if (data.audioUrl || (data.audio && !data.reply)) {
    if (hudSoundEnabled()) playTTSAudio(data.audioUrl || data.audio);
  }
}

function stripTag(t) {
  return String(t || '').replace(/\s*\([^()]*\/[^()]*\)\s*$/, '').trim();
}

function updateMicBar(level) {
  const fill = document.getElementById('micLevelFill');
  const db = document.getElementById('micDb');
  if (fill) fill.style.width = Math.min(100, level) + '%';
  if (db) db.textContent = level.toFixed(0) + (level > 10 ? ' ●' : '');
}

function playTTSAudio(src, voice) {
  // Cortafuegos final: por defecto el HUD no suena (dueno = agente playsound/SAPI).
  if (!hudSoundEnabled()) return;
  setReactorState('speaking');
  try {
    const audio = new Audio(src);
    audio.play().catch(() => setReactorState('idle'));
    audio.onended = () => {
      setReactorState('idle');
    };
  } catch (e) {
    setReactorState('idle');
  }
}

// Map Handler
function showHolographicMap(city, lat, lng) {
  const overlay = document.getElementById('mapOverlay');
  const title = document.getElementById('mapTitle');
  if (!overlay) return;

  title.textContent = `MAPA HOLOGRÁFICO EN TIEMPO REAL — ${String(city || '').toUpperCase()}`;
  overlay.classList.remove('hidden');

  if (!mapInstance) {
    mapInstance = L.map('map').setView([lat, lng], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19
    }).addTo(mapInstance);
  } else {
    mapInstance.setView([lat, lng], 12);
  }

  L.marker([lat, lng]).addTo(mapInstance).bindPopup(`<b>${city}</b>`).openPopup();
}

window.addEventListener('DOMContentLoaded', () => {
  setInterval(updateClock, 1000);
  updateClock();
  connectWebSocket();
  updateSysPanel();
  pollOllama();
  setInterval(pollOllama, 15000);
  pollLocalGpu();
  setInterval(pollLocalGpu, 15000);
  // Fase1b: sin listeners de micro (ni clic en subtitulo ni ESPACIO).
  // El HUD solo muestra: reloj, subtitulos, mapa y estado del reactor.
});

// Export para consola / botones
window.sendAudioToServer = sendAudioToServer;
