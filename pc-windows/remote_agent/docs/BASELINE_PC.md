# BASELINE_PC — hechos verificados (solo lectura, sin secretos)
Fecha: 2026-10-13T13:50+02:00 (UTC+2). Equipo: {{NOMBRE_PC}}.
Origen: C:\jarvis_agent\remote_agent (agente), ROOTS=C:\JARVIS-PC.
Regla aplicada: solo lectura salvo este fichero; sin cambios de codigo ni .env; sin reinicios; sin tocar procesos.

## 1. Suite
- Colectados: 121 tests (`pytest --collect-only -q`: "121 tests collected").
- Resultado: `121 passed in 3.14s` (ejecucion 2026-10-13 ~13:50).
- Ficheros de test: 17 en tests/ (test_apps_close, test_apps_owned, test_audit_direct, test_desktop, test_errors_never_empty, test_fase_b, test_fase_c, test_killswitch, test_killswitch_wire, test_limits, test_power_manifests, test_presence_tts, test_process, test_unlock_local, test_voice_runtime_fix, test_voice_shadow, test_wake_gated).
- No crea ficheros en produccion: tests/conftest.py redirige `agent.LOG_FILE` a `tmp_path` (fixture autouse `_aislar_log_local`); todos los tests usan `tmp_path` para audit.jsonl/killswitch.json/shadow.jsonl (grep tmp_path en test_audit_direct, test_errors_never_empty, test_fase_b, test_fase_c, test_killswitch, test_killswitch_wire, etc.).
- Evidencia: tras la ejecucion, `audit.jsonl` sigue con 119 lineas y LastWriteTime 2026-10-13 00:12:53; `killswitch.json` intacto (`locked=false`); `voice_shadow.jsonl` ausente (`Test-Path=False`); `logs/remote_agent.log` LastWriteTime 13:49:15 (previo a la suite, por el agente vivo, no por la suite).

## 2. Microfono (mic_bridge NO borrado)
- Fichero existe: `{{WIN_HOME}}\jarvis-v2-fijo\agent\mic_bridge.py` (10727 bytes, 2026-10-01).
- Tarea `\JarvisV2MicBridge`: `Estado de tarea programada: Habilitado`, `Estado: En ejecucion`, `Ultimo resultado: 267009`, comando `pythonw.exe "...\agent\mic_bridge.py"`, `Iniciar en: {{WIN_HOME}}\jarvis-v2-fijo`, comentario "Jarvis v2 fijo mic bridge (unico, con lock)".
- Otras tareas: `\JarvisRemoteAgent` (Habilitado, Listo, `wscript.exe C:\jarvis_agent\remote_agent\Start-RemoteAgent.vbs`); `\JarvisV2Agent` (Habilitado, En ejecucion, `main.py --ws ws://{{PORTATIL_IP}}:8765`); `\JARVIS-PC-Bridge` / `\JARVIS-PC-Heal` (`wscript.exe .../watchdog_hidden.vbs`).
- Lanzadores: `C:\JARVIS-PC\watchdog_hidden.vbs`, `C:\jarvis_agent\remote_agent\Start-RemoteAgent.vbs` (938 bytes). `pc_bridge.py` existe en `C:\JARVIS-PC\pc_bridge.py` (61629 bytes).
- check_boot 2026-10-13T13:51:05: `mic_bridge x1 PASS (n=1, pid=15544)`, `mic_bridge.lock verificado pid=15544`, `main.py x1 pid=5080`, `agent.py x1 pid=4224`, VEREDICTO OK.
- .env produccion (valores, sin secretos): `VOICE_SHADOW=0`, `VOICE_IN=1`, `VOICE_WAKE=1`.
- Unico proceso capturando audio: NO. Hay dos aspirantes: mic_bridge.py pid=15544 (tarea habilitada y en ejecucion) + hilo `VoiceIn` del agent.py pid=4224 (`logs/remote_agent.log`: "VOICE_IN vivo wake-gated ... dev=1 VAD>=25.0 STT=medium" el 2026-10-12T23:58:42, 2026-10-13T00:06:21, 00:08:42, 00:17:27 y 13:49:00; "modelo wake onnx OK (silencio score=0.0)").
- Reversion exacta (NO ejecutada, solo documentada):
  1. `schtasks /Query /TN "\JarvisV2MicBridge" /V /FO LIST` (confirmar Estado).
  2. Para devolver microfono al pipeline viejo: en `C:\jarvis_agent\remote_agent\.env` poner `VOICE_IN=0` y reiniciar SOLO el agente cuando lo autorice el usuario (no reiniciado aqui); el hilo VoiceIn no arranca y el log dira "Voz: solo salida TTS + outbox manual (VOICE_IN=0, microfono intacto)".
  3. Para re-habilitar mic_bridge si se hubiese deshabilitado: `schtasks /Change /TN "\JarvisV2MicBridge" /ENABLE` y `schtasks /Run /TN "\JarvisV2MicBridge"` (no ejecutado). Para pausarlo sin borrar: `schtasks /Change /TN "\JarvisV2MicBridge" /DISABLE` + `taskkill /PID <pid-mic> /F` solo con autorizacion (no ejecutado). La tarea existe y esta Habilitada: volver atras es re-habilitar, no reinstalar.

## 3. Metricas de logs (sin audio ni texto transcrito mas alla de conteos)
- Umbral wake: `thr=0.5` (5 lineas "thr=0.5"; .env `VOICE_WAKE_THRESHOLD` por defecto 0.5 en config.py).
- VAD: `VAD>=25.0` (VOICE_VAD=25).
- Modelos: `STT=medium` (faster-whisper medium, CPU/int8 segun voice.py `transcribe_wav_bytes`); wake `hey_jarvis`.
  - `voice.wake_onnx_path()` = `.../site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx`, existe, 1271370 bytes.
  - `describe_downloads()`: `openWakeWord/hey_jarvis size_bytes=1278912 present=True`; `faster-whisper/medium size_bytes=1530571775 present=True`.
- Activaciones (log `logs/remote_agent.log`, 1223 lineas): 2 lineas identicas "VOICE_IN: 'Hey Jarvis' detectado, escuchando frase completa" el 2026-10-13T00:12:15 (mismo segundo, posible doble registro de 1 evento); 1 `jr_voice_text enviado (13 chars, stt)` el 2026-10-13T00:12:42 (27 s despues).
- Activaciones por hora (wake): `2026-10-13T00: 2 lineas (1 evento deduplicado)`.
- STT por hora: `2026-10-13T00: 1`.
- Activaciones sin frase posterior: 1 si se cuentan lineas (2 wakes - 1 stt), 0 si se deduplica el doble registro del mismo segundo. Sin suficiente resolucion para distinguir falsa vs doble-log.
- Latencia p50/p95 produccion: sin datos (VOICE_SHADOW=0, `voice_shadow.jsonl` ausente, el camino vivo `start_mic_stt` no registra latencias; solo hay 1 frase stt). `shadow_metrics()` actual en memoria: `n=0, lat_p50=0.0, lat_p95=0.0`.
- No se guarda audio: codigo `shadow_append` solo escribe `{ts,text,latency_s,wake,stt}` (sin audio/base64); `transcribe_wav_bytes` usa `NamedTemporaryFile(delete=False)` + `unlink`; `play_audio_bytes` usa temporal + `unlink`; test `test_shadow_append_no_audio_only_text` exige `"audio" not in entry` y sin "base64" en el jsonl.

## 4. Mocks: wake cancela reproduccion y priority se respeta
- `test_stop_for_wake_stops_playback` y `test_stop_for_wake_marks_not_playing` (test_voice_shadow.py, test_wake_gated.py): mockean `_stop_current_tts`, `set_playing(True)` -> `stop_for_wake()` -> `is_playing()==False` y stop llamado. PASS.
- `test_tts_priority_parse`: P0/P2/P1-defecto. PASS.
- `test_tts_enqueue_p0_front_and_fifo`: P1,P1,P0 -> dequeue devuelve P0 primero. PASS.
- `test_live_arm_logic`, `test_wake_gated_sends_only_after_wake`, `test_no_wake_no_send`, `test_disarm_after_phrase`, `test_start_mic_stt_wake_log_path`: sin wake no hay envio; tras frase se desarma (exige nuevo wake); wake durante reproduccion cuenta stop. PASS.

## 5. Sesiones
- Excluidas rechazadas: `session.EXCLUDED_EXACT={clipboard.read, shell.exec, files.delete}`, `EXCLUDED_PREFIX=(system.,)`; `test_session_rejects_not_in_list_and_excluded` cubre clipboard.read/shell.exec/system.shutdown/system.lock/files.delete -> "EXCLUIDA". `agent.execute_action` con sesion exige `SESSION_GRANTS=1` si no `feature_disabled`.
- TTL: `SESSION_TTL_MAX_S=600`; `test_session_mint_ttl_max_600` (ttl 9999 recortado a <=600); `check_session` rechaza `TTL>600`, `caduca`, `incompleta`.
- Contador: `max_actions` con `check_session`/`consume_session`; `test_session_rejects_missing_expired_counter` (1 uso -> agotada); `test_session_response_format_never_empty_error` (`session_remaining==1` tras 1 de 2).
- Un solo ID: `test_session_single_active_id` ("otra sesion activa").
- Revocacion por kill switch: `agent._handle_killswitch` llama `session.revoke_session(ctx)`; `execute_action` con sesion y `_is_locked` revoca y deniega `killswitch_locked`; `test_session_killswitch_revokes` (revoke limpia `_session_id`).

## 6. Estado
- `killswitch.json`: `{"locked": false, ...}` (desbloqueado). `killswitch.is_locked`/`set_locked` verificados por tests.
- `audit.verify()`: `(True, "ok")`, 119 entradas (`audit.AuditLog(...).verify()` ejecutado 2026-10-13).
- `check_boot`: ejecutado 2026-10-13T13:51:05, VEREDICTO OK: agent.py x1 (4224), main.py x1 (5080), mic_bridge x1 (15544), ESTABLISHED 18765 (agent.py) n=1, conexion 8765 (main.py) n=1, locks verificados, killswitch desbloqueado, audit ok. Reporte en `scripts/boot_report.txt`.
- Unico agent.py: PASS n=1 (pid 4224, `pythonw.exe C:\jarvis_agent\remote_agent\agent.py`, sin consola).
- ESTABLISHED: `{{PC_IP}}:59637 -> {{PORTATIL_IP}}:18765 ESTABLISHED 4224` (netstat); check_boot confirma 1 ESTABLISHED 18765 de agent.py. Adicional: `...:59642 -> ...:8765 ESTABLISHED 5080` (main.py).
- `agent.lock`: contiene `4224`, verificado por check_boot.

## 7. Entrega
- Este fichero es la unica escritura permitida realizada.
- `agent_pc.zip` en ROOTS NO regenerado (bloqueado por regla solo-lectura): estado existente `C:\JARVIS-PC\agent_pc.zip` (84597 bytes, 2026-10-12 22:44:03), `.sha256` = `C8430AC92B8F53E8B834B9EA0A1B72222B2B470E2518D2577A49CA75BDD9CF0E`, partes `part01.txt` (49152), `part02.txt` (49152), `part03.txt` (14492). Regeneracion pendiente via `scripts\make_agent_release.ps1` (pasos 1-6, incluye venv temporal + verificacion SHA/reconstruccion base64) cuando se levante la restriccion de escritura.

## NO VERIFICADO
- Latencia de transcripcion p50/p95 en produccion (sombra apagada, sin muestras; solo logica mockeada en `test_shadow_metrics_p50_p95`).
- Tasa de falsas activaciones con significacion estadistica (n=1 evento, doble-log sin resolver).
- Que dos capturadores simultaneos (mic_bridge + VoiceIn) no compitan por el dispositivo (ambos arrancados; Windows permitio abrir; no se midio contencion ni perdida).
- Contenido de las frases (no se transcribe ni reproduce audio/texto por privacidad; solo conteos).
- `agent_pc.zip` regenerado + partes base64 + SHA256 nuevos (no ejecutado por regla solo-lectura).
- Supervivencia a reinicio real y apagados reales (prohibidos por reglas).
