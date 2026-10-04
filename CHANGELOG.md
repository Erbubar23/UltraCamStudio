# Historial de versiones

Las versiones siguen el formato `0.MENOR.PARCHE-beta`: la versión **menor** sube cuando hay funciones nuevas y la de **parche** cuando solo hay correcciones. La fuente de la versión es `APP_VERSION` en `gui.py`.

## 0.21.0-beta — 2026-10-04

### Nuevo
- **Transmisión a varias plataformas** (módulo opcional): YouTube, Twitch, Facebook, Kick, TikTok, Instagram o un servidor RTMP/RTMPS propio, a la vez.
  - Cada plataforma es un recuadro con su símbolo. Se enciende y apaga con su botón sin cortar a las demás, y al tocarla se actualizan sus accesos.
  - La señal se codifica una sola vez por orientación (GPU si la hay) y MediaMTX la reparte. TikTok e Instagram salen en 9:16.
  - **Prueba de velocidad**: dice cuántas plataformas puedes tener al aire en 1080p, 720p o vertical.
  - **Centro de cuentas**: las claves se guardan cifradas con DPAPI y no aparecen en el registro. Las que cambian en cada directo se piden al encender.
  - Ajuste de sincronía de audio en Transmisión › Avanzado.
- **Interfaz por módulos**: la barra lateral tiene Cámaras, Grabación y General, más los módulos opcionales, que se activan con un botón.
  - Cada módulo abre su panel con «Básico» y «Avanzado».
  - El mezclador de audio queda siempre visible.
  - El engrane de ajustes indica dónde quedó cada opción y lleva directo a ella.
- **Videos finales más ligeros**: al guardar, el video se recomprime en HEVC/H.264 con la GPU (NVIDIA, Intel o AMD) o con el procesador hasta 1080p. Pesa unas 3 veces menos con la misma calidad. Si no conviene, se une tal cual como antes. Se puede desactivar en Grabación.
- **Guardado seguro**:
  - Una barra muestra el progreso y bloquea la app mientras se guarda.
  - Los originales se borran solo después de comprobar que el archivo quedó completo.
  - Si cierras la app a medio guardar, pregunta antes, y la toma se puede terminar de guardar al volver.
- **Instrumentos VST3 con MIDI**: un canal puede ser un sintetizador o sampler (Vital, Decent Sampler, Kontakt…) que se toca con un teclado MIDI, con elección de entrada y canal MIDI.
- **Explorador de plugins** al estilo Reaper: favoritos, recientes, categorías, fabricante, carpetas propias y búsqueda.
- **60 fps reales con el teléfono** (hasta 1080p) usando el modo de alta velocidad de la cámara de Android.
- **Panel Cámaras rediseñado**:
  - La lista de cámaras queda más visible.
  - Al elegir una se abren sus ajustes en tarjetas (Formato, Orientación, Cámara), con botón para volver.
- **iPhone por cable**: la app detecta el iPhone conectado por USB y explica qué instalar (DroidCam o Camo, y «Dispositivos Apple»).

### Mejoras
- **Monitor en vivo con menos retraso**: el reproductor ya no acumula memoria intermedia y descarta cuadros atrasados.
- La cabecera dice «Cámara virtual: activa / en pausa» en vez del nombre del dispositivo.
- Textos en blanco y morado más oscuro en Transmisión para que se lean bien.
- La interfaz se adapta a ventanas angostas sin que los controles se encimen.

### Correcciones
- Los plugins VST3 instalados como carpeta (Amp Locker, Decent Sampler, KV-Element, Mobius) ya cargan (E21).
- El panel Cámaras ya no encima el control de orientación con el botón de pausa.

### Técnico
- Código dividido en `app/` (marco) y `modules/` (cámaras, audio, grabación, general, transmisión). Los módulos no se importan entre sí.
- `settings_window.py` se repartió en el `ui/settings.py` de cada módulo.
- Nuevas pruebas en `tests/` (marco, exportación, transmisión). `run_tests.bat` corre las dos suites.
- `packaging/build.ps1` incluye MediaMTX (MIT) en `bin\mediamtx`.

## 0.20.4-beta — 2026-09-28
*No se publicó por separado: sus cambios van incluidos en la 0.21.0-beta.*
- Los procesos de video (scrcpy, ffmpeg, ffplay) se cierran con la app aunque se cierre a la fuerza (Job Object con `KILL_ON_JOB_CLOSE`).

## 0.20.3-beta — 2026-09-28
- Al grabar en vertical con el teléfono ya no aparece una ventana de video suelta en el escritorio.
- La grabación en vertical ya no se da por fallida si el teléfono tarda en mandar la primera imagen.

## 0.20.2-beta — 2026-09-28
- Monitor sin retraso en 4K y 2K: la vista previa se decodifica por GPU y se muestra a Full HD, y la toma se graba a resolución completa.
- La vista previa de webcams y capturadoras 4K también se limita a Full HD.
- Ya no se pierde el primer segundo de video al empezar a grabar con el teléfono.
- Etiqueta del modo junto al nombre de la cámara («4K · 30 fps», «Full HD · 60 fps · 9:16»).
- Botón «Donate» en la barra inferior.
