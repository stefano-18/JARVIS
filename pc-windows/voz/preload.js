const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvisAPI', {
  platform: process.platform,
  // Fase5: VRAM local (fallback si la laptop no manda gpu_info).
  getGpu: () => ipcRenderer.invoke('get-gpu')
});
