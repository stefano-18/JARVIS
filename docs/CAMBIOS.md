# Cambios

## 24/10/2026 - JARVIS vuelve a obedecer

**Síntoma:** por Telegram, «apaga el PC» contestaba «ya está apagado» y «abre …» no abría nada, aunque el PC estaba encendido.

**Causas reales** (tres a la vez):

| Fallo | Por qué | Arreglo |
|---|---|---|
| «El PC ya está apagado» con el PC encendido | El cerebro miraba si el PC estaba encendido con los puertos y el `ping` del PC Windows de antes; en el PC Linux esa comprobación falla siempre | Encendido = el agente del PC está conectado al hub (18765); si no, `ping` de Linux o SSH. Si de verdad no llega, dice «No llego al PC… no he ejecutado nada» |
| «Abre X» decía «abierto» pero no abría nada | El agente del PC arrancaba antes que la sesión gráfica y no tenía `WAYLAND_DISPLAY`: las apps morían al momento y el agente daba un «ok» falso | El agente busca la sesión de Wayland/Hyprland viva antes de lanzar nada y comprueba que el lanzamiento no falla |
| El portátil desapareció de la red | Un fallo puntual del router al reconectar la wifi y NetworkManager se rindió («no-secrets") hasta reiniciar | `tools/vigilante-wifi-portatil.sh`: cada minuto, si no hay wifi, la vuelve a levantar |

**Además:**
- **Cerrar comprueba** - «cierra X» solo dice «cerrado» si la ventana se ha ido; si pide guardar, lo dice.
- **Ventanas por app y lado** - «pon Spotify en la otra pantalla», «mueve X a la pantalla de la izquierda/derecha».
- **«Abre el juego X»** y **«bloquea el PC»** por la vía rápida, sin IA.
- **«Dime tu IP y a qué wifi estás»** - el portátil contesta su red y si el PC está conectado.
- **Suspender contesta antes de dormirse**, para que el cerebro no lo dé por fallido.
- **Repositorio unificado** - el PC, el portátil y GitHub vuelven a tener una sola historia.
- Apagar, reiniciar y suspender **siguen pidiendo la palabra clave**.

**Probado en vivo** (por el mismo camino que un mensaje de Telegram, comprobando el efecto en el PC): abrir y cerrar apps, abrir juegos, mover ventanas entre pantallas, volumen, silencio, música (poner, pausar, siguiente), «busca … y dime», hora, bloquear el PC, IP y wifi. Apagar y suspender llegan hasta el candado de la palabra clave.

> **Lección:** el cerebro que contesta es la copia viva del portátil (`~/jarvis2/scripts`, `~/jarvis-control/plugin-silencio`, `~/.hermes/plugins/jarvis-filtro`), no el repositorio. Un arreglo no está hecho hasta que está ahí y se ha probado con una orden real.
