const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
const path = require('path');
const { execFile } = require('child_process');

// Fase5: VRAM local sin depender de la laptop. El renderer pide
// jarvisAPI.getGpu() cada 15 s solo como fallback (si no hay gpu_info
// reciente). Solo lectura: nvidia-smi, timeout 10 s.
ipcMain.handle('get-gpu', async () => {
  return new Promise((resolve) => {
    execFile('nvidia-smi',
      ['--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
      { timeout: 10000, windowsHide: true },
      (err, stdout) => {
        if (err) return resolve({ ok: false });
        try {
          const line = String(stdout || '').trim().split('\n')[0] || '';
          const parts = line.split(',').map((x) => parseInt(String(x).trim(), 10));
          if (parts.length >= 2 && Number.isFinite(parts[0]) && Number.isFinite(parts[1])) {
            return resolve({ ok: true, used_mib: parts[0], total_mib: parts[1] });
          }
        } catch (e) { /* cae a ok:false */ }
        resolve({ ok: false });
      });
  });
});

app.commandLine.appendSwitch('enable-speech-dispatcher');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');

function createWindow() {
  const win = new BrowserWindow({
    fullscreen: true,
    kiosk: true,
    frame: false,
    type: 'desktop',
    skipTaskbar: true,
    transparent: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.setAlwaysOnTop(false, 'desktop');

  // Fase1b: click-through (los clics pasan a las ventanas de debajo).
  // Ctrl+Alt+J = mostrar/ocultar HUD, Ctrl+Alt+Q = cerrar HUD.
  win.setIgnoreMouseEvents(true, { forward: true });

  win.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === 'media') {
      callback(true);
    } else {
      callback(false);
    }
  });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(() => {
  createWindow();

  globalShortcut.register('CommandOrControl+Alt+J', () => {
    const w = BrowserWindow.getAllWindows()[0];
    if (!w) return;
    if (w.isVisible()) { w.hide(); console.log('HUD oculto (Ctrl+Alt+J)'); }
    else { w.show(); console.log('HUD mostrado (Ctrl+Alt+J)'); }
  });
  globalShortcut.register('CommandOrControl+Alt+Q', () => {
    console.log('HUD cerrado por atajo (Ctrl+Alt+Q)');
    app.quit();
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
