# JARVIS en el PC con Omarchy: pendiente de confirmar (22/10/2026)

Ya funciona sin hacer nada más:
- Cerebro en el portátil: Haiku 5.5, Groq, Telegram, Gmail, Calendar y copias diarias (todo intacto).
- Voz en el PC: «Hey Jarvis», micrófono Fifine, voz de Álvaro y atajo Ctrl+Alt+J. Arranca sola con el PC.
- Vigilante del portátil: ya no avisa de que el agente del PC está caído (ajuste `vigilar_agente_pc = false`).

Pendiente de que el señor lo confirme o lo haga:
1. [ ] **Probar la voz en persona**: decir «Hey Jarvis», esperar el «¿Sí, señor?» y pedir la hora. Comprobar si oye bien y si el volumen está bien.
2. [x] **Agente del PC fijo** (24/10: arranca solo, abre apps de verdad, probado en vivo desde Telegram) (control de apps, ventanas, teclado, volumen y capturas): ya está adaptado a Linux y probado contra el cerebro. Falta su «sí» para dejarlo arrancando solo con el PC.
3. [ ] **Clics del ratón**: instalar `ydotool` (necesita su contraseña de administrador; le abro una ventana para escribirla).
4. [ ] **Volver a activar el aviso del vigilante** cuando el agente esté fijo (`vigilar_agente_pc = true` en el portátil).
5. [x] **Guardar los cambios en GitHub** (24/10: https://github.com/stefano-18/JARVIS, PC + portátil unificados) (voz y agente para Linux). Solo el código; las claves nunca se suben.
7. [ ] **Activar en el portátil la memoria de Obsidian y los límites de tokens por tarea**. Ya están hechos y probados en una copia (30 pruebas nuevas, todas bien). Falta su «sí» para aplicarlos a JARVIS en vivo; se hace de una vez con `~/jarvis-pc/pendiente-contexto/aplicar.sh`, que deja copia de seguridad, pasa las pruebas, guarda el cambio y reinicia la voz y Telegram.
10. [ ] **Encender el PC por red**: el PC ya está preparado y el portátil tiene su dirección correcta. Falta comprobar en la BIOS que «Wake on LAN» esté activado (y «ErP» desactivado), y reiniciar el PC una vez para que se aplique.
8. [x] **Mandar al portátil la lista de juegos y apps de Linux** (sustituye la de Windows): `python3 ~/jarvis-repo/pc-windows/exportar_nombres_linux.py --enviar`. Hoy solo hay un juego instalado (Rocket League, en Heroic).
9. [ ] **Wi-Fi del portátil** (24/10: preparado `sudo bash ~/jarvis-repo/tools/vigilante-wifi-portatil.sh` en el portátil, falta ejecutarlo con su contraseña) (causa de los cortes de Telegram): lo mejor es cable. Si no, que NetworkManager no se rinda nunca al reconectar (`autoconnect-retries`) y acercar el portátil al router.
11. [x] **Habilidades que esperan al agente fijo** (punto 2): explícame la pantalla, música por voz, dictado «escribe…», mándame archivos, «guarda eso» por voz y la parte del PC de «voy a jugar». Ya están instaladas en el cerebro y en el agente.
12. [ ] **Luces / casa**: en la red no hay Philips Hue ni otros dispositivos de casa (solo el router Fritz!Box, la impresora Brother y un altavoz con Spotify Connect). Falta que confirme qué aparatos tiene.
13. [ ] **Spotify exacto**: «pon X» abre Spotify buscando X; para que ponga la canción o lista exacta hace falta crear una app gratuita en Spotify for Developers y autorizarla (5 min, con su cuenta).
14. [ ] **Actualizar Omarchy de noche**: el resumen de las 8:30 ya funciona; instalarlas solas necesita permitir `pacman` sin contraseña (decisión de seguridad suya).
6. [ ] Opcional: que el cerebro mande rutas de Linux en vez de las de Windows. Ahora mismo el agente las traduce solo, así que no corre prisa.

## Actualización 22/10/2026 (madrugada)
- [x] Agente del PC fijo y vigilado · [x] Memoria de Obsidian activa · [x] Avisos de Telegram que fallan por la red se reintentan · [x] 72 copias .bak movidas a ~/papelera-jarvis/20261022-bak (en el portátil)
- [x] Wake-on-LAN: la tarjeta de red del PC queda armada (magic packet) y el portátil tiene su dirección. Falta la prueba real al apagar.
- [ ] Wi-Fi del portátil: que nunca se rinda al reconectar necesita su contraseña: `sudo bash ~/jarvis-repo/tools/vigilante-wifi-portatil.sh` en el portátil.
- [ ] SEGURIDAD: en el portátil, `sudo` deja ejecutar `apt-get install *` sin contraseña; eso permite hacerse administrador. Recomiendo quitar esa línea (sudo visudo).
- [ ] GitHub: repositorio listo y anonimizado en el portátil (~/jarvis-repo). Para publicarlo: crear el repo vacío en GitHub y `git remote add origin git@github.com:<usuario>/jarvis-asistente.git && git push -u origin main`.

## Habilidades nuevas (22/10/2026, tarde) — todas activas, por voz y por Telegram
- Notas en Obsidian: «apunta que …», «qué apunté sobre …», «busca en mis notas …». Diario automático cada noche (JARVIS/Diario).
- Lista de la compra: «añade leche a la lista de la compra», «qué hay en la lista de la compra», «ya lo he comprado».
- «Léemelo» (lo seleccionado o copiado), «tradúceme esto» (y lo deja copiado), «qué suena».
- «Qué tiempo hace» / «va a llover mañana», «qué tengo hoy», «qué me he perdido».
- «Cómo está el PC», «cuánto he jugado hoy / esta semana»; avisos por Telegram si se calienta o se llena el disco.
- «Modo concentración 45 minutos», «graba la pantalla» / «para de grabar», «luz nocturna», «silencia el PC», «volumen al 30».
- «Mándame el último clip / la última grabación», «recuérdame … cuando encienda el PC».
- Saludo por voz la primera vez que enciende el PC cada día; resumen del día por voz a las 20:00 (los domingos, con el gasto de la semana).
- Los bordes de la ventana se iluminan en azul cuando JARVIS escucha y en dorado cuando habla.
- Para quitar el saludo o el resumen: decírselo a JARVIS o poner "saludo": false / "resumen_tarde": false en ajustes.json.

## GitHub
- Repositorio del portátil al día, anonimizado y con un historial limpio (sin datos personales). Copia del historial anterior en ~/backups/jarvis-repo-antes-squash-*.bundle.
- Publicar: crear el repositorio vacío en GitHub y, en el portátil, dentro de ~/jarvis-repo: `git remote add origin git@github.com:SU_USUARIO/jarvis-asistente.git && git push -u origin main`
- Control de la voz (en el PC, al instante): «para» / «cállate», «repite», «más despacio» / «más rápido».
- Correo y agenda SOLO lectura: «tengo correos nuevos», «léeme el último correo», «qué tengo mañana / el viernes / esta semana».
- Arreglos: ventanas y clics con la API Lua de Hyprland; clics exactos en las dos pantallas; colocación de pantallas para el control del cerebro; bordes que respetan su tema.
- Pendiente de usted: una prueba real de clic (p. ej. «Jugar» de Steam); «omarchy update» (75 pendientes); publicar en GitHub; probar el encendido por red.

## Panel de JARVIS (22/10, noche)
- En el PC: «Panel de JARVIS» en el lanzador de apps (túnel seguro al portátil, sin abrir puertos).
- En el móvil (solo wifi de casa): en el portátil, `bash ~/abrir-panel-movil.sh` (pide su contraseña una vez y le manda el enlace por Telegram).
- Habilidades nuevas: «qué me queda por hacer hoy», «repíteme el último aviso», «nota de voz: …», «pon un pomodoro», «cuánto llevo en el PC», «abre mis proyectos / la carpeta de …», «minimiza / cierra esta ventana», «cámbiame a …».
