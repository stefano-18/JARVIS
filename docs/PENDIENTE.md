# Pendiente (lo tiene que hacer {{NOMBRE}} o un agente con permisos)

Estas cosas no se pudieron hacer automáticamente porque necesitan contraseña de administrador o tocan el candado.

**Atajo:** en el portátil `bash ~/jarvis-repo/tools/con-contrasena-portatil.sh` (puntos 1, 4 y 5) y en el PC clic derecho en `pc-windows/con-contrasena-pc.ps1` → Ejecutar con PowerShell (punto 2). Piden la contraseña una sola vez. Ojo: el del portátil deja el cortafuegos en «denegar entradas» salvo lo de JARVIS y SSH desde casa.

## 1. Cortafuegos del portátil (necesita `sudo`)
Ahora mismo el servidor de voz (puerto 8765) acepta conexiones de cualquier aparato de la red de casa. Solo debería
aceptar al PC:
```bash
sudo ufw allow from <IP-del-PC> to any port 8765 proto tcp
sudo ufw status numbered        # y borrar con "sudo ufw delete N" cualquier regla general de 8765
```

## 2. Cortafuegos del PC (necesita administrador)
Windows creó reglas "python.exe" y "pythonw.exe" que dejan entrar por **cualquier puerto desde cualquier sitio**.
Desactivarlas en *Windows Defender Firewall → Reglas de entrada* (las de JARVIS-8765 y Ollama-LAN-JARVIS están bien,
solo aceptan al portátil).

## 3. Firma también para el desbloqueo (UNLOCKED)
La señal de visto bueno ya va firmada (HMAC). El archivo de desbloqueo de la palabra clave lo gestiona `jarvis_gate.py`
(el candado), que no se ha tocado a propósito. Que un agente de código añada la misma firma allí y lo pruebe con la
palabra clave real, comprobando que sigue bloqueando a los 3 fallos.

## 4. Límite del registro del sistema (necesita `sudo`)
En `/etc/systemd/journald.conf` poner `SystemMaxUse=300M` y `sudo systemctl restart systemd-journald`.

## 5. Recargar los servicios una vez
```bash
sudo systemctl daemon-reload
```
