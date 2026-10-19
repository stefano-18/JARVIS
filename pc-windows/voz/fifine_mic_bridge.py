"""
FIFINE Mic Bridge para Wallpaper Engine — FIX DEFINITIVO DE GANANCIA
Ajusta la ganancia del micrófono FIFINE para que el nivel (0-100) sea muy visible
y el umbral de voz (VAD) active la grabación al hablar normalmente.
"""

import asyncio
import base64
import json
import math
import os
import sys
import numpy as np
import pyaudio
import websockets

WS_URL = os.getenv("JARVIS_WS_URL", "ws://{{PORTATIL_IP}}:8765")
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
VAD_THRESHOLD = 25 # Umbral ultra-sensible ajustado para FIFINE RMS (25-30)

async def mic_bridge():
    p = pyaudio.PyAudio()
    
    target_idx = None
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev.get("maxInputChannels", 0) > 0:
            name = dev.get("name", "")
            if "fifine" in name.lower():
                target_idx = i
                print(f"-> Micrófono FIFINE detectado [ID {i}]: {name}")
                break

    try:
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=target_idx,
            frames_per_buffer=CHUNK
        )
    except Exception as e:
        print(f"Error abriendo mic especifico: {e}, usando default...")
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

    print(f"-> Conectando con servidor JARVIS en {WS_URL}...")
    
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                print("-> ¡Puente FIFINE conectado a JARVIS por WebSocket!")
                
                recording = False
                frames = []
                silence_count = 0
                
                while True:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    rms = np.sqrt(np.mean(audio_data.astype(np.float32)**2))
                    if math.isnan(rms): rms = 0
                    
                    # Ganancia amplificada para FIFINE: escala 0 a 100 visualmente evidente
                    level = min(100, int((rms / 150.0) * 100))
                    
                    # Transmitir nivel de volumen en tiempo real al HUD (Wallpaper Engine)
                    await ws.send(json.dumps({"type": "mic_level", "level": level}))
                    
                    # Detección de voz / Grabación
                    if rms > VAD_THRESHOLD and not recording:
                        recording = True
                        frames = [data]
                        silence_count = 0
                        await ws.send(json.dumps({"type": "state", "state": "listening"}))
                    elif recording:
                        frames.append(data)
                        if rms < VAD_THRESHOLD:
                            silence_count += 1
                        else:
                            silence_count = 0
                            
                        if silence_count > 15 or len(frames) > 75: # ~3.5s o silencio
                            recording = False
                            wav_data = b"".join(frames)
                            b64_str = base64.b64encode(wav_data).decode("utf-8")
                            
                            # Enviar audio base64 al servidor
                            await ws.send(json.dumps({
                                "type": "audio",
                                "data": f"data:audio/wav;base64,{b64_str}"
                            }))
                            print("-> ¡Audio grabado enviado a JARVIS!")
                            frames = []
                    
                    await asyncio.sleep(0.02)

        except Exception as e:
            print(f"Conexión perdida ({e}), reintentando en 3s...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(mic_bridge())
