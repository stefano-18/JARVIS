# Kill-switch del remote_agent (PC fijo)

Bloqueado = se deniega TODA accion MEDIUM y HIGH; las LOW de solo lectura
siguen funcionando. NO mata procesos ni apaga nada: solo bloquea la puerta
de `execute_action` y persiste el estado en `killswitch.json` para sobrevivir
a un reinicio. Fichero ausente o corrupto = desbloqueado.

El agente lee `killswitch.json` en CADA decision MEDIUM/HIGH
(`agent._is_locked` -> `killswitch.is_locked`, sin cache): cualquier cambio
del fichero surte efecto inmediato SIN reiniciar.

## Fichero de estado `killswitch.json`

```json
{"locked": true, "ts": 1791628689, "trace_id": "t-lock"}
```

- `locked`: bool. `ts`: epoch segundos. `trace_id`: origen del cambio
  (`"local-unlock"` en desbloqueos locales).

## Sobre firmado (todos los mensajes tras el handshake)

```json
{"msg_id": "<hex>", "ts": 1791628689, "ctr": 7, "type": "jr_killswitch",
 "payload": {...},
 "hmac": "HMAC_SHA256(secret, \"msg_id.ts.ctr.type.json_canonico(payload)\")"}
```

Valida `ChannelGuard`: firma, ventana `ts` ±30 s, `ctr` creciente,
anti-replay por `msg_id`. Todo va por el canal ya autenticado (HMAC);
no hay secreto nuevo.

## `jr_killswitch` (bloquear, via red firmada)

Payload:

```json
{"trace_id": "abc-123"}
```

Efecto: `killswitch.json` -> `{"locked": true, ...}`. Invalida grants
pendientes en la practica (bloqueado, toda MEDIUM/HIGH se deniega aunque
el grant sea valido; `used` se conserva, jamas se reutiliza). LOW sigue.
Respuesta `jr_res`:

```json
{"ok": true,
 "result": {"status": "ok", "locked": true,
            "message": "kill-switch activado: MEDIUM/HIGH bloqueados"},
 "trace_id": "abc-123"}
```

Audita `agent.killswitch/high/ok` en `audit.jsonl`.

## `jr_unlock` (desbloquear, via red firmada + grant HIGH de un solo uso)

Payload:

```json
{"trace_id": "abc-124",
 "grant": {"grant_id": "<hex>", "action": "agent.unlock",
           "params_hash": "<sha256 de {}>",
           "expires": 1791628749,
           "hmac": "HMAC_SHA256(secret, \"grant_id.agent.unlock.params_hash.expires\")"}}
```

El grant es el de HIGH normal (`protocol.mint_grant`, TTL 60 s, un solo
uso, ligado a accion `agent.unlock` + params `{}`): sin grant valido se
deniega y se audita. Respuesta `jr_res` con exito:

```json
{"ok": true,
 "result": {"status": "ok", "locked": false,
            "message": "kill-switch desactivado: operativa restaurada"},
 "trace_id": "abc-124"}
```

Denegado (sin grant, caducado, reutilizado o firma mala):

```json
{"ok": false,
 "result": {"status": "error", "executed": false, "locked": true,
            "code": "unlock_denied",
            "error": "unlock denegado: <motivo>"},
 "trace_id": "abc-124"}
```

Audita `agent.unlock/high/ok|error` en `audit.jsonl`.

## Denegacion por bloqueo dentro de `execute_action`

Toda MEDIUM/HIGH bloqueada retorna (envuelta en `jr_res` con `ok: false`):

```json
{"status": "error", "executed": false, "code": "killswitch_locked",
 "error": "BLOQUEADO por kill-switch (<accion>): agente en modo bloqueado. NO SE EJECUTO NADA. Se requiere jr_unlock con grant HIGH valido.",
 "_risk": "medium|high"}
```

(`_risk` es el riesgo efectivo y se retira del `jr_res`; queda auditado.)

## Error de limite HIGH (formato exacto)

Limitador local deslizante: `HIGH_MAX_PER_MINUTE` (defecto 10) y
`HIGH_MAX_PER_HOUR` (defecto 60). La denegacion NO consume cuota. Retorna:

```json
{"status": "error", "executed": false, "code": "high_rate_limited",
 "error": "limite de acciones HIGH superado; espera 42 s",
 "_risk": "high"}
```

`espera N s`: segundos hasta que la ventana vuelve a permitir
(minuto: `max(1, int(60 - (now - oldest) + 1))`; hora: analogo con 3600).
Envuelto en `jr_res` con `ok: false` y auditado como `error`.

## Desbloqueo LOCAL de emergencia (sin red, sin reinicio)

Para cuando la laptop no puede mandar `jr_unlock` (red caida, grants
perdidos, etc.). Lo ejecuta el usuario FISICO en este PC:

1. Doble clic en `scripts\unlock_local.bat`, o
   `python scripts\unlock_local.py` desde esta carpeta.
2. Muestra el estado actual y pide escribir `DESBLOQUEAR` en consola.
3. Restablece `killswitch.json` a `{"locked": false, ...}`.
4. El agente lo aplica SIN reiniciar (lee el fichero en cada decision).
5. El desbloqueo queda en `killswitch_local.log` (linea con fecha,
   `locked_before` y `ts`). NUNCA toca `audit.jsonl` (prohibido con el
   agente vivo: falsearia la hash-chain).

Comprobado con `tests/test_unlock_local.py`: bloqueado -> `unlock_local`
-> una accion MEDIUM vuelve a funcionar con el MISMO `ctx` (sin reinicio).
