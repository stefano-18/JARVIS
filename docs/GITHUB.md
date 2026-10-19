# Ficha para GitHub

- **Nombre:** `jarvis-asistente`
- **Visibilidad:** privado (al menos hasta revisar que no quede nada personal; el código ya usa marcadores `{{...}}`).
- **Descripción corta:** Asistente personal tipo JARVIS: controla tu PC por voz y Telegram, con memoria, recordatorios,
  correo, tareas largas y departamentos de IA. Cerebro en Linux + agente en Windows. Claude Haiku.
- **Temas (topics):** `assistant` `voice-assistant` `telegram-bot` `claude` `anthropic` `hermes-agent` `home-automation`
  `windows-automation` `python` `spanish`
- **Licencia:** MIT (provisional; la decide {{NOMBRE}}. MIT = cualquiera puede usarlo; GPL = quien lo cambie debe compartirlo).

## Subirlo (cuando {{NOMBRE}} cree el repositorio vacío en github.com)
```bash
cd ~/jarvis-repo
git remote add origin git@github.com:<usuario>/jarvis-asistente.git
git push -u origin main
```
GitHub Actions (`.github/workflows/ci.yml`) buscará claves y pasará las pruebas en cada subida.
