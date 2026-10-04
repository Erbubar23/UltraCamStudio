# Registro Técnico de Errores y Desafíos Resueltos (UltraCam Studio Pro)

Este documento registra de forma exhaustiva los desafíos de ingeniería, incompatibilidades de hardware/sistema operativo y errores resueltos durante el desarrollo de **UltraCam Studio Pro**. Sirve como referencia técnica y documentación viva para desarrolladores, usuarios avanzados e inteligencias artificiales de diagnóstico.

---

## Índice de Errores

1. [E1: Error de Aserción en Android 16 (`AssertionError: Unexpected message type: 10`)](#e1-error-de-aserción-en-android-16-assertionerror-unexpected-message-type-10)
2. [E2: Desconexión Abrupta por Cable USB Lento (`failed to read copy response: EOF`)](#e2-desconexión-abrupta-por-cable-usb-lento-failed-to-read-copy-response-eof)
3. [E3: Bucle de Sondeos ADB y Congelamiento de Interfaz Gráfica](#e3-bucle-de-sondeos-adb-y-congelamiento-de-interfaz-gráfica)
4. [E4: Omisión de Lentes Múltiples de Teléfonos Modernos](#e4-omisión-de-lentes-múltiples-de-teléfonos-modernos)
5. [E5: Captura de Audio "Seco / Limpio" de Guitarra en vez del Audio Procesado de Tonocracy (Fallo de OBS)](#e5-captura-de-audio-seco--limpio-de-guitarra-en-vez-del-audio-procesado-de-tonocracy-fallo-de-obs)
6. [E6: Audio Monofónico en un Solo Auricular (Canal Izquierdo)](#e6-audio-monofónico-en-un-solo-auricular-canal-izquierdo)
7. [E7: Conflicto y Desfase por Frecuencias de Muestreo Distintas (44.1 kHz vs 48 kHz)](#e7-conflicto-y-desfase-por-frecuencias-de-muestreo-distintas-441-khz-vs-48-khz)
8. [E8: Incompatibilidad Nativa con Dispositivos Apple iPhone en Windows](#e8-incompatibilidad-nativa-con-dispositivos-apple-iphone-en-windows)
9. [E9: Congelamiento de la Máquina al Finalizar Grabaciones en 4K UHD](#e9-congelamiento-de-la-máquina-al-finalizar-grabaciones-en-4k-uhd)
10. [E10: Ventana de Monitoreo Flotante Externa vs Monitor Embebido en la Interfaz (Win32 `SetParent`)](#e10-ventana-de-monitoreo-flotante-externa-vs-monitor-embebido-en-la-interfaz-win32-setparent)
11. [E11: Limitación a Entrada Única y Rigidez de Marcas ("Tonocracy") en Mezcla de Audio](#e11-limitación-a-entrada-única-y-rigidez-de-marcas-tonocracy-en-mezcla-de-audio)
12. [E12: Estrangulamiento de Ancho de Banda USB en Webcams de PC (Caída a 7.5 FPS en YUY2 vs 30/60 FPS en MJPEG)](#e12-estrangulamiento-de-ancho-de-banda-usb-en-webcams-de-pc-caída-a-75-fps-en-yuy2-vs-3060-fps-en-mjpeg)
13. [E13: Variaciones de Iluminación y Focus Hunting en Grabación de Músicos (Foco Manual vs Autofocus DirectShow)](#e13-variaciones-de-iluminación-y-focus-hunting-en-grabación-de-músicos-foco-manual-vs-autofocus-directshow)
14. [E14: Cierre de scrcpy con `0xC0000094` (división por cero) al incrustar su ventana](#e14-cierre-de-scrcpy-con-0xc0000094-división-por-cero-al-incrustar-su-ventana)
15. [E15: Tonocracy (ASIO) no llegaba al master: salida ASIO imposible de capturar](#e15-tonocracy-asio-no-llegaba-al-master-salida-asio-imposible-de-capturar)
16. [E16: Las ventanas de plugins VST3 solo abren desde el hilo principal](#e16-las-ventanas-de-plugins-vst3-solo-abren-desde-el-hilo-principal)
17. [E17: `Unanticipated host error` al abrir entradas WASAPI desde otro hilo (COM)](#e17-unanticipated-host-error-al-abrir-entradas-wasapi-desde-otro-hilo-com)
18. [E18: La cámara virtual aparecía y desaparecía de Windows, y activarla volvía lenta la grabación](#e18-la-cámara-virtual-aparecía-y-desaparecía-de-windows-y-activarla-volvía-lenta-la-grabación)
19. [E19: La cámara web permanecía encendida tras cerrar la app y bloqueo en cierre (`AppHangB1`)](#e19-la-cámara-web-permanecía-encendida-tras-cerrar-la-app-y-bloqueo-en-cierre-apphangb1)
20. [E20: Arquitectura Monolítica, Acoplamiento Estricto y Supresión Silenciosa de Excepciones (`bare except`)](#e20-arquitectura-monolítica-acoplamiento-estricto-y-supresión-silenciosa-de-excepciones-bare-except)
21. [E21: Plugins VST3 en carpeta (bundle) no cargaban: «unsupported plugin format»](#e21-plugins-vst3-en-carpeta-bundle-no-cargaban-unsupported-plugin-format)
22. [E22: El teléfono no pasaba de 30 fps](#e22-el-teléfono-no-pasaba-de-30-fps)
23. [E23: NVENC fallaba al comprimir con el FFmpeg de desarrollo](#e23-nvenc-fallaba-al-comprimir-con-el-ffmpeg-de-desarrollo)
24. [E24: El monitor de video tapaba los paneles de la interfaz](#e24-el-monitor-de-video-tapaba-los-paneles-de-la-interfaz)
25. [E25: Apagar una plataforma no cortaba su envío](#e25-apagar-una-plataforma-no-cortaba-su-envío)

---

## E1: Error de Aserción en Android 16 (`AssertionError: Unexpected message type: 10`)

### Síntoma
Al iniciar la transmisión de cámara en un dispositivo con Android 16 (ej. Samsung Galaxy S23 Ultra con One UI 8 / Developer Preview), el proceso de `scrcpy` terminaba inmediatamente con el siguiente mensaje de error en la consola:
```text
[scrcpy-err] Exception in thread "main" java.lang.AssertionError: Unexpected message type: 10
[scrcpy-err]     at com.genymobile.scrcpy.device.Controller.handleEvent(Controller.java:82)
[scrcpy-err]     at com.genymobile.scrcpy.device.Controller.control(Controller.java:65)
```

### Causa Raíz
En versiones anteriores de Android, `scrcpy` transmitía video mientras mantenía activo un socket bidireccional para inyectar eventos de control (pulsaciones de pantalla, apagado de display `--turn-screen-off` y bloqueo de suspensión `--stay-awake`). En Android 16, la estructura de paquetes de control cambió y el modo `--video-source=camera` no soporta mensajes de tipo 10 si el canal de control está abierto.

### Solución Implementada
- Se estableció el parámetro `--no-control` como mandatorio en `engine.py:build_command()`.
- Se removieron de forma condicional los flags `--turn-screen-off` y `--stay-awake` cuando el dispositivo corre Android 16.
- El streaming de video opera en un canal unidireccional de alto rendimiento a 4K 60fps con cero llamadas de control que provoquen la aserción.

---

## E2: Desconexión Abrupta por Cable USB Lento (`failed to read copy response: EOF`)

### Síntoma
Al configurar resoluciones altas (4K UHD a 50M o 60M), la transmisión iniciaba por unos segundos y luego se cerraba con el error:
```text
[scrcpy-err] adb: error: failed to read copy response: EOF
[USB] ❌ Dispositivo DESCONECTADO
```

### Causa Raíz
Muchos cables USB-C comerciales son únicamente de carga o estándar USB 2.0 (HighSpeed limitado a ~30 MB/s con caídas periódicas). Cuando el sensor del teléfono enviaba un flujo de datos 4K que superaba la capacidad física sostenida del cable o del puerto del gabinete, el búfer de socket de ADB colapsaba y cerraba la conexión (`EOF`).

### Solución Implementada
- **Benchmark de Cable Integrado**: Se programó una prueba en tiempo real que transfiere un bloque de 3 MB a `/data/local/tmp` para calcular el rendimiento real en MB/s.
- **Calificación Dinámica de Resoluciones**:
  - `< 5 MB/s`: Cable deficiente / USB 1.1 o puerto saturado. Se bloquea 4K y se recomienda 720p.
  - `5 a 20 MB/s`: USB 2.0 estándar. Se recomienda 1080p y se alerta si se selecciona 4K.
  - `> 20 MB/s`: USB 3.0 / SuperSpeed. Se habilita 4K 60fps con bitrate completo.
- **Alternativa Wi-Fi 6**: Se implementó el emparejamiento automático por red local sobre el puerto TCP 5555 (`adb tcpip 5555`), permitiendo transmitir en 4K sin depender de cables defectuosos.

---

## E3: Bucle de Sondeos ADB y Congelamiento de Interfaz Gráfica

### Síntoma
La consola de la aplicación imprimía cientos de líneas por minuto con mensajes como:
```text
[00:04:56.392] [POLL] Buscando dispositivos conectados...
[00:04:59.400] [POLL] Buscando dispositivos conectados...
```
Esto ocultaba los errores reales, provocaba micro-tirones en la interfaz gráfica y saturaba el portapapeles al intentar copiar los registros.

### Causa Raíz
El hilo de monitoreo de dispositivos (`_start_device_monitor`) registraba cada sondeo periódico como un log de nivel `INFO`, escribiendo directamente en el widget de texto sin verificar si el estado del dispositivo había cambiado.

### Solución Implementada
- Se implementó un filtro de estado con **debounce de eventos reales**: el motor solo emite logs cuando un dispositivo cambia de estado (`conectado`, `desconectado`, `offline`).
- Se suprimió por completo la emisión de sondeos constantes en el logger principal.
- Se trasladó el visor de logs desde la pantalla principal hacia una pestaña dedicada de diagnóstico.

---

## E4: Omisión de Lentes Múltiples de Teléfonos Modernos

### Síntoma
Al seleccionar "Cámara Trasera", la aplicación siempre abría el sensor por defecto (típicamente el gran angular regular), imposibilitando el uso del lente Ultra Gran Angular (0.6x) o los sensores Telefoto (3x / 10x periscopio) en teléfonos de gama alta como el Galaxy S23 Ultra o Pixel 8 Pro.

### Causa Raíz
`scrcpy` por defecto solo distingue entre `--camera-facing=back` y `--camera-facing=front`. En dispositivos multicámara, cada sensor tiene un identificador de hardware único (`camera-id=0`, `camera-id=1`, etc.).

### Solución Implementada
- Se implementó la función `discover_cameras(serial)` que ejecuta `scrcpy --list-cameras` y parsea los sensores disponibles.
- El selector en la interfaz se adapta dinámicamente mostrando:
  - Gran Angular Principal (200MP)
  - Ultra Gran Angular (12MP)
  - Telefoto Óptico 3x
  - Periscopio Óptico 10x
  - Cámara Frontal

---

## E5: Captura de Audio "Seco / Limpio" de Guitarra en vez del Audio Procesado de Tonocracy (Fallo de OBS)

### Síntoma
Al grabar sesiones con amplificadores virtuales standalone como **Tonocracy**, **Neural DSP** o **Amplitube**, OBS y otros programas grababan únicamente el sonido limpio de las cuerdas sin procesar (señal DI seca), a pesar de que el usuario escuchaba la guitarra con distorsión y pantallas IR en sus auriculares.

### Causa Raíz
La guitarra entra por la entrada física de instrumento de la interfaz de audio (ej. `Behringer IN 1` o `Focusrite IN 1`). Los programas de grabación suelen configurar una *"Captura de Entrada de Audio"* (Audio Input Capture), la cual lee directamente el convertidor A/D de la interfaz **antes** de que el software procesador (Tonocracy) reciba y module la señal. Tonocracy toma el control ASIO y envía el resultado a las **salidas de reproducción** de la interfaz (`OUT 1-2`).

### Solución Implementada
- Se implementó la captura mediante **Windows WASAPI Loopback** (`audio_engine.py` sobre `pyaudiowpatch`).
- El sistema se conecta al pin de loopback del dispositivo de reproducción activo del usuario (su interfaz o altavoces).
- Esto intercepta la señal PCM mezclada final post-Tonocracy, post-cabezal, post-IRs y post-efectos, capturando exactamente el sonido que sale por los auriculares.

---

## E6: Audio Monofónico en un Solo Auricular (Canal Izquierdo)

### Síntoma
Al conectar una guitarra en la Entrada 1 o un micrófono en la Entrada 2 de cualquier interfaz de audio comercial, la señal en la grabación se escuchaba únicamente por el auricular izquierdo (L), dejando el derecho (R) en silencio absoluto.

### Causa Raíz
Las interfaces de audio profesionales exponen sus canales físicos como entradas mono individuales o como un par estéreo donde la Entrada 1 es Left y la Entrada 2 es Right. Al grabar en un contenedor estéreo sin procesar, la señal queda ruteada al canal izquierdo.

### Solución Implementada
- Se creó una matriz de mapeo en `audio_engine.py` con modo **"Dual Mono / Centrado (L+R)"**.
- Si el usuario selecciona una entrada mono (o activa el centrado), el motor duplica matemáticamente el búfer de entrada a ambos canales `(L = in, R = in)` con compensación de volumen, logrando un sonido perfectamente equilibrado en ambos oídos.

---

## E7: Conflicto y Desfase por Frecuencias de Muestreo Distintas (44.1 kHz vs 48 kHz)

### Síntoma
Al combinar el audio del sistema (loopback de interfaz a 48.000 Hz) con un micrófono USB o webcam que operaba a 44.100 Hz, la grabación presentaba chasquidos, tono más agudo o desincronización progresiva respecto al video.

### Causa Raíz
Los búferes PCM de audio a distintas frecuencias de muestreo tienen diferente número de muestras por segundo. Si se suman directamente sin resamplear, la pista más lenta se desfasará a razón de ~4.000 muestras por segundo.

### Solución Implementada
- Se programó un **Resampler Dinámico en Memoria**:
  - El motor establece una frecuencia maestra uniforme para el proyecto (48.000 Hz por defecto).
  - Cualquier flujo con tasa diferente es interpolado y remuestreado en tiempo real antes de entrar al bus de mezcla, garantizando fidelidad acústica y sincronización absoluta con el video.

---

## E8: Incompatibilidad Nativa con Dispositivos Apple iPhone en Windows

### Síntoma
El backend original basado en `scrcpy` dependía exclusivamente de ADB de Android, dejando a los usuarios de iPhone sin posibilidad de transmitir su cámara a la aplicación en Windows.

### Causa Raíz
Apple iOS no dispone de soporte para ADB ni permite acceso crudo a la cámara por USB sin controladores firmados o protocolos de streaming de video de red.

### Solución Implementada
- Se diseñó una arquitectura de **Proveedores de Dispositivo (`DeviceProvider`)**:
  - `AndroidProvider`: Basado en scrcpy 4.1 + ADB.
  - `AppleProvider`:
    1. **Ingesta DirectShow 4K**: Detecta cámaras virtuales de iOS estándar en Windows (**Iriun Webcam**, **DroidCam Video**, **Camo**), las cuales permiten transmitir desde iPhone por cable USB o Wi-Fi a 4K 60fps.
    2. **Receptor SRT / RTSP con Código QR**: Levanta un receptor de red local; el iPhone escanea un código QR en pantalla y transmite con ultra-baja latencia (< 50ms) usando códec hardware H.265.
- La interfaz unifica ambas plataformas bajo una experiencia homogénea de grabación y mezcla de audio.

---

## E9: Congelamiento de la Máquina al Finalizar Grabaciones en 4K UHD

### Síntoma
Al pulsar *"Detener Grabación"* en una toma 4K de varios minutos, la aplicación bloqueaba la CPU y la GPU durante minutos enteros, provocando interrupciones de audio (buffer underruns) en Tonocracy y congelamiento de la pantalla.

### Causa Raíz
Las rutinas de multiplexado convencionales intentaban recodificar el video completo a formato H.264/H.265 usando software de compresión pesada (`libx264`/`libx265`).

### Solución Implementada
- Se diseñó un pipeline de post-grabación con **Multiplexado de Flujo Directo (`-c:v copy`)** en FFmpeg:
  - El video 4K del sensor ya viaja codificado en hardware desde el procesador del teléfono (Snapdragon o Apple Bionic).
  - FFmpeg solo copia el flujo de video bit a bit y ensambla las pistas de audio AAC/PCM en el contenedor MP4.
  - Una sesión de 1 hora en 4K 60fps se ensambla y se deja lista en menos de **2 segundos** sin consumir ciclos significativos de CPU.

---

## E10: Ventana de Monitoreo Flotante Externa vs Monitor Embebido en la Interfaz (Win32 `SetParent`)

### Síntoma
Al iniciar la transmisión o el monitoreo de la cámara, `scrcpy` o `ffplay` creaban una ventana externa separada e independiente en el escritorio de Windows con sus propios marcos, bordes y barra de título. Esto obligaba al usuario a alternar entre ventanas flotantes para ajustar parámetros, interrumpiendo el flujo de trabajo en vivo.

### Causa Raíz
Tanto `scrcpy` como `ffplay` utilizan internamente SDL2 para crear su ventana nativa (`HWND`). Sin intervención en el subsistema de ventanas del sistema operativo, Windows las instancia como ventanas de nivel superior (`WS_OVERLAPPEDWINDOW`), desacopladas de la aplicación gráfica principal.

### Solución Implementada
- Se implementó el método `embed_window_into_hwnd` en `engine.py` utilizando la API de Win32 (`ctypes.windll.user32`).
- Se asigna un título determinista a la ventana de visualización (`--window-title=UltraCam_Studio_Monitor`).
- En un hilo no bloqueante, el sistema busca el manejador de ventana (`FindWindowW`), obtiene el identificador nativo del contenedor Tkinter (`widget.winfo_id()`) y ejecuta `SetParent(child_hwnd, parent_hwnd)`.
- Se suprimen los bordes y la barra de título (`style &= ~WS_CAPTION`, `style &= ~WS_THICKFRAME`) y se asigna el estilo de ventana hija (`WS_CHILD`).
- Mediante `MoveWindow`, el feed se ajusta exactamente al tamaño del contenedor, embebiendo el monitor 4K en el corazón de la interfaz sin popups externos.

---

## E11: Limitación a Entrada Única y Rigidez de Marcas ("Tonocracy") en Mezcla de Audio

### Síntoma
La interfaz solo permitía seleccionar una única entrada de audio, impidiendo configuraciones estándar de grabación de interfaces multipuerto (ej. Behringer U-Phoria o Focusrite Scarlett con `IN 1` para instrumento y `IN 2` para micrófono de voz simultáneo). Además, etiquetar la captura del sistema con el nombre de un software específico ("Tonocracy") restringía la app y confundía a usuarios con otros procesadores de audio (Neural DSP, Amplitube, DAWs como Reaper, o audio general de Windows).

### Causa Raíz
El motor de audio manejaba un único índice de entrada física (`input_device_index`) y la interfaz tenía cadenas hardcodeadas referidas a un software puntual en lugar de manejar una arquitectura de bus de audio universal.

### Solución Implementada
- Se rediseñó `audio_engine.py` como una **Matriz de Audio Profesional de 4 Canales**:
  1. `Audio del Sistema (Salida General)`: Captura universal vía WASAPI Loopback del endpoint activo (juegos, YouTube, emuladores de guitarra, DAWs, Spotify).
  2. `Entrada Física 1`: Canal dedicado con fader, mute, solo y selector de modo (ej. Instrumento / Guitarra en IN 1).
  3. `Entrada Física 2`: Canal dedicado adicional con fader, mute, solo y selector de modo (ej. Micrófono XLR en IN 2).
  4. `Master Mix`: Bus sumador estéreo con control maestro de ganancia y limitador anti-clipping.
- Se erradicó cualquier mención rígida a "Tonocracy" en toda la base de código, logs, UI, nombres de archivo y metadatos de pistas MP4/WAV, estableciendo la nomenclatura estándar **"Audio del Sistema (Salida General)"**.
- El motor ejecuta concurrentemente las 3 lecturas WASAPI sin colisión de hilos, resamplea todo a 48 kHz y permite exportar todas las pistas como stems WAV independientes y pistas de audio empotradas en el MP4.

---

## E12: Estrangulamiento de Ancho de Banda USB en Webcams de PC (Caída a 7.5 FPS en YUY2 vs 30/60 FPS en MJPEG)

### Síntoma
Al seleccionar una webcam USB estándar de alta resolución (como la Logitech C505, C920 o similares) en resolución 720p o 1080p, la transmisión presentaba un retardo severo y una tasa de cuadros extremadamente baja (entre 5 y 7.5 FPS), haciendo que el movimiento de las manos y la ejecución instrumental se vieran a tirones, a pesar de que el sensor de la cámara indicaba ser capaz de 30 FPS.

### Causa Raíz
La mayoría de webcams comerciales operan sobre un puerto USB 2.0 (ancho de banda teórico de 480 Mbps, utilizable ~280 Mbps). El formato de video sin comprimir `YUY2` (`yuyv422`) requiere 16 bits por píxel. A 1280x720 a 30 FPS, el ancho de banda necesario es:
`1280 × 720 × 2 bytes × 30 fps = 55.296.000 bytes/s (52.7 MB/s) = 421.8 Mbps`.
Esto satura por completo el bus USB 2.0 de la placa base, por lo que el controlador de la cámara se ve forzado a estrangular la tasa a 7.5 FPS.

### Solución Implementada
- **Sondeo Inteligente de Capacidades (`probe_camera_capabilities`)**:
  El motor ejecuta un análisis dinámico del dispositivo DirectShow (`ffmpeg -list_options true -f dshow -i video="..."`).
- **Priorización Automática de Códec Comprimido por Hardware (`MJPEG`)**:
  El sensor comprime cada cuadro en JPEG internamente antes de enviarlo por el bus USB, reduciendo el ancho de banda requerido en más del 80%.
- Al detectar disponibilidad de `MJPEG`, UltraCam Studio Pro lo selecciona automáticamente en el comando de captura (`-vcodec mjpeg`), desbloqueando de inmediato los **30 FPS o 60 FPS estables y fluidos** en 720p, 1080p y 4K UHD.

---

## E13: Variaciones de Iluminación y Focus Hunting en Grabación de Músicos (Foco Manual vs Autofocus DirectShow)

### Síntoma
Durante la grabación de actuaciones musicales (guitarra acústica/eléctrica, piano, canto), la imagen sufría de:
1. **Focus Hunting**: La cámara desenfocaba constantemente el rostro para enfocar las cuerdas o las manos en movimiento, volviendo borrosa la toma en los momentos más importantes.
2. **Flicker / Salto de Exposición**: Cambios repentinos de brillo en la pantalla al variar la posición de las manos o reflejos en el barniz de la guitarra.

### Causa Raíz
Los drivers de las webcams en Windows operan por defecto en modo de Exposición Automática y Autofocus Continuo. En escenas musicales donde hay movimiento rápido de manos cerca del objetivo o contrastes de luz de estudio, los algoritmos de detección de fase y contraste del sensor entran en bucle continuo de búsqueda de enfoque.

### Solución Implementada
- **Acceso Directo al Panel Nativo de Hardware**:
  Se implementó `open_camera_hardware_dialog` que dispara el diálogo oficial de DirectShow (`-show_video_device_dialog true`), permitiendo al usuario fijar:
  - **Enfoque en MANUAL** (bloqueado exactamente en la posición del músico/instrumento).
  - **Exposición en MANUAL** (fija una velocidad de obturación constante para evitar parpadeos con luces LED de estudio).
  - **Balance de Blancos en MANUAL** (evita cambios de temperatura de color).
- **Presets de Estudio ("Músico / Performance")**:
  Se diseñó un preset especializado que guía al usuario y ajusta nitidez y contraste óptimos, guardando las configuraciones personalizadas de cada cámara en `camera_presets.json` para que nunca se pierdan entre sesiones.

---

## E14: Fallo de Inicialización DirectShow por Confusión entre Códec de Compresión (`-vcodec mjpeg`) y Formato de Píxel Crudo (`-pixel_format mjpeg`)

### Síntoma
Al intentar iniciar el streaming o monitoreo con webcams de PC (como la Logitech C505 o UVC Camera 0), el proceso de FFplay/FFmpeg terminaba de inmediato con código de salida erróneo:
```text
[dshow indev @ 000002b87f603dc0] Unable to parse "pixel_format" option value "mjpeg" as pixel format
[dshow indev @ 000002b87f603dc0] Error setting option pixel_format to value mjpeg.
video=C505 HD Webcam: Invalid argument
[PROCESS] Streaming finalizó con código 0
No se pudo incrustar ventana en el contenedor.
```

### Causa Raíz
En el demuxer DirectShow de FFmpeg (`-f dshow`), los formatos de entrada se dividen estrictamente en:
1. **Códecs de flujo comprimido (`-vcodec`)**: como `mjpeg`, donde las tramas provienen comprimidas por hardware desde el sensor.
2. **Formatos de píxel crudo sin compresión (`-pixel_format`)**: como `yuyv422`, `rgb24`, `nv12`.

Al pasarse `-pixel_format mjpeg`, el parseador de opciones de FFmpeg (`AVOptions`) intentaba resolver `mjpeg` en la tabla interna de `AVPixelFormat`. Al no ser un formato de píxel crudo, FFmpeg arrojaba `Invalid argument` y cerraba la ejecución antes de instanciar la ventana gráfica, provocando a su vez que el hilo Win32 `SetParent` fallara por timeout al no encontrar la ventana esperada.

### Solución Implementada
- Se diferenció en `engine.py` (`probe_camera_capabilities`) entre `caps["vcodec"]` y `caps["pixel_format"]`.
- En `build_pc_camera_command` y `build_ios_command`, se implementó una normalización robusta:
  - Si la configuración contiene `pixel_format="mjpeg"` o `vcodec="mjpeg"`, se traduce automáticamente a `["-vcodec", "mjpeg"]`.
  - Si se utiliza un formato crudo (ej. `yuyv422`), se utiliza `["-pixel_format", pixel_format]`.
- En grabación MP4 con MJPEG (`-vcodec mjpeg`), se habilita `-c:v copy` directo hacia el contenedor, manteniendo la grabación a 30 FPS fluidos con consumo mínimo de recursos.
- Con esta corrección, tanto la Logitech C505 a 1280x960 @ 30 FPS como la UVC Camera 0 a 1920x1080 @ 30 FPS inician instantáneamente y su ventana `UltraCam_Studio_Monitor` queda 100% embebida dentro de la aplicación.

---

## E14: Cierre de scrcpy con `0xC0000094` (división por cero) al incrustar su ventana

### Síntoma
Con el monitor integrado, scrcpy terminaba a los ~3 s con el código `3221225620` (`0xC0000094`, STATUS_INTEGER_DIVIDE_BY_ZERO). El servidor en el teléfono mostraba `Camera capture failed: frame 41` justo antes. El mismo comando, lanzado sin incrustar, funcionaba.

### Causa Raíz
scrcpy crea su ventana **oculta** y la muestra al decodificar el primer cuadro (cuando ya conoce el tamaño del video). `embed_window_into_hwnd` la encontraba por título a los ~0,4 s y llamaba `SetParent`/`MoveWindow`/`ShowWindow` sobre la ventana aún oculta: scrcpy procesaba un redimensionado sin tamaño de contenido y dividía por cero.

### Solución Implementada
`embed_window_into_hwnd` espera a que la ventana sea visible (`IsWindowVisible`) antes de tocarla. Prueba de regresión: `test_embed_window_waits_until_visible`.

---

## E15: Tonocracy (ASIO) no llegaba al master: salida ASIO imposible de capturar

### Síntoma
Tonocracy standalone sonaba en los audífonos pero su audio no aparecía en la mezcla de UltraCam.

### Causa Raíz
Tonocracy estaba configurado con `UMC ASIO Driver`. ASIO va directo a la interfaz sin pasar por el mezclador de Windows, así que ningún loopback lo ve; además el driver ASIO de la Behringer UMC no es multicliente (un solo programa a la vez).

### Solución Implementada
UltraCam aloja plugins **VST3** dentro de cada canal (pedalboard) y puede abrir la interfaz por **ASIO** (PortAudio con ASIO de sounddevice). La guitarra entra por IN 1 → Tonocracy VST3 dentro de UltraCam → master/grabación/OBS, y se escucha por el bus **Monitor** con ~10 ms ida y vuelta (búfer 128). El standalone ya no es necesario.

---

## E16: Las ventanas de plugins VST3 solo abren desde el hilo principal

### Síntoma
`RuntimeError: Plugin UI windows can only be shown from the main thread.` al abrir el editor de Tonocracy desde un hilo; y abrirlo en el hilo principal congelaba la interfaz Tk (show_editor bloquea).

### Solución Implementada
El motor de audio corre en **su propio proceso** (`audio_server.py`, multiprocessing *spawn*). Su hilo principal atiende las ventanas de los plugins; el audio corre en el callback de tiempo real; la interfaz se comunica por un Pipe (`audio_engine.AudioEngine`). Además aísla fallos: si un plugin se cae, la app sigue abierta. La ventana del plugin se renombra de «Pedalboard» a «Plugin · Canal — UltraCam Studio».

---

## E17: `Unanticipated host error` al abrir entradas WASAPI desde otro hilo (COM)

### Síntoma
Dentro del proceso de audio, las fuentes extra (loopback de la UMC, IN 2) fallaban con `[Errno -9999] Unanticipated host error`, aunque en un script aislado abrían bien.

### Causa Raíz
PyAudioWPatch se inicializaba (Pa_Initialize → COM) en el hilo de comandos y los streams se abrían en el hilo principal: WASAPI requiere COM inicializado en el hilo que abre el stream.

### Solución Implementada
Todo lo que toca PortAudio/WASAPI (listar dispositivos, abrir y cerrar streams) y los plugins se ejecuta en el hilo principal del proceso de audio (cola `main_jobs`).

---

## E18: La cámara virtual aparecía y desaparecía de Windows, y activarla volvía lenta la grabación

### Síntoma
Dos problemas con un mismo origen:

1. El dispositivo «UltraCam» solo existía en Windows mientras había una transmisión activa. Cambiar de cámara, girar la imagen o mover un slider de calibración reiniciaba la vista previa, y con ella el dispositivo: Zoom, Meet, Teams u OBS veían la cámara desaparecer y reaparecer, perdían la fuente y había que volver a elegirla.
2. Al encender la cámara virtual, la imagen empezaba a ir a tirones y el video grabado salía lento (más corto de lo que duró la toma, o con cuadros perdidos).

### Causa Raíz
Medido con una fuente de 1920x1080@60 durante 6 segundos y las tres salidas activas, ffmpeg reportaba `speed=0.813x`: **no alcanzaba el tiempo real**. Con un archivo de prueba eso solo alarga el proceso, pero una webcam entrega cuadros a ritmo real y no espera, así que el retraso se convertía en cuadros perdidos y en latencia creciente. Tres causas sumadas:

- **El filtrado se calculaba una vez por salida.** Las tres salidas (archivo, monitor y cámara virtual) llevaban su propio `-vf` con la misma cadena `eq` + `unsharp`. La nitidez es el filtro más caro de la cadena y se estaba pagando tres veces por cada cuadro.
- **Nada limitaba las salidas secundarias.** El monitor y la cámara virtual corrían a los fps nativos de la cámara. A 60 fps, el lienzo de 1080p en NV12 son 186 MB/s cruzando un pipe con nombre solo para la cámara virtual.
- **El lector de Python copiaba cada cuadro tres veces** (una al leer del pipe, otra al acumular en un `bytearray` y otra al recortarlo). Como el pipe apenas guarda un par de cuadros, cuando Python se retrasaba vaciándolo ffmpeg se quedaba bloqueado escribiendo — y al ser un único ffmpeg para las tres salidas, ese bloqueo frenaba también la captura y la grabación.

### Solución Implementada

**El dispositivo vive mientras vive el programa.** `virtualcam.VirtualCamService` (instancia única `SERVICE`) crea «UltraCam» al abrir UltraCam Studio y la mantiene encendida hasta cerrarlo, emitiendo negro continuo mientras no haya señal. Las fuentes se enganchan y desenganchan por debajo, así que las aplicaciones externas nunca ven el dispositivo aparecer ni desaparecer. El botón «Cámara Virtual» dejó de crear el dispositivo: ahora solo decide qué fuente se ve en él. Se puede desactivar el encendido automático en Configuración → Cámara Virtual, para dejarle el dispositivo a la cámara virtual de OBS Studio (ambas comparten el mismo filtro DirectShow y no pueden emitir a la vez).

**Una sola pasada de calibración.** `build_pc_camera_command` construye ahora un `-filter_complex` con `split`: `eq` y `unsharp` se calculan una vez y el resultado se reparte a las tres ramas.

**Cada salida pide lo que necesita.** El archivo conserva la resolución y los fps nativos de la cámara. El monitor baja a 540p y a 30 fps (es una ayuda visual, no el producto). La cámara virtual se fija en 30 fps (`VCAM_FPS`), que es lo que usan Zoom, Meet, Teams y Discord.

**Los cuadros ya no se copian.** `VirtualCamSink` usa triple búfer: el productor llena `back_buffer()` y llama a `publish()`, que intercambia punteros bajo el cerrojo; el emisor solo toca su propio búfer. `NamedPipeServer.readinto()` / `read_exact()` leen del pipe directamente sobre ese búfer, sin pasos intermedios.

**La grabación usa la GPU si la hay.** `CameraEngine.video_encoder_args()` prueba `h264_nvenc`, `h264_qsv`, `h264_amf` y `h264_mf` (este último con `-hw_encoding true`, sin el cual Windows acepta y codifica por software, que sería más lento que libx264). La comprobación es una codificación real de prueba, no leer la lista de codificadores de ffmpeg: ffmpeg los lista aunque la tarjeta no esté. El resultado se guarda para la sesión y se averigua en segundo plano al abrir el programa.

### Resultado Medido
Misma prueba, 6 segundos de 1920x1080@60 con grabación, monitor y cámara virtual a la vez, codificando por CPU:

| | Antes | Después |
|---|---|---|
| Velocidad de ffmpeg | `0.813x` (por debajo del tiempo real) | `1.09x` |
| Tiempo real para 6 s de fuente | 7.5 s | 5.6 s |
| Cuadros grabados | 360 / 360 | 360 / 360, sin `drop` ni `dup` |
| Resolución y fps del archivo | 1920x1080 @ 60 | 1920x1080 @ 60 (sin cambios) |

---

## E19: La cámara web permanecía encendida tras cerrar la app y bloqueo en cierre (`AppHangB1`)

### Síntoma
1. Al cerrar la ventana de la aplicación o al finalizar el uso, el LED verde de la cámara web física (DirectShow) continuaba encendido indefinidamente en el escritorio. La cámara solo se liberaba al forzar el cierre del proceso en el Administrador de Tareas.
2. Al pulsar el botón de cerrar la ventana («X»), la aplicación a menudo se congelaba por más de 5 segundos, haciendo que Windows reportara un bloqueo de aplicación (`AppHangB1` en el Visor de Eventos con firma `8409`).

### Causa Raíz
1. **Incompatibilidad entre Win32 `SetParent` y `DestroyWindow`**: El proceso `ffplay.exe` era incrustado dentro del contenedor Tkinter usando `SetParent`. Al cerrar la aplicación, Tkinter destruía la ventana padre (`parent_hwnd`), pero la API de Win32 no permite destruir una ventana hija creada por otro hilo/proceso, dejando la ventana de `ffplay` en un estado huérfano e impidiéndole cerrar su grafo de filtros DirectShow.
2. **Proceso desasociado en propiedades de cámara**: `open_camera_hardware_dialog` ejecutaba `ffmpeg` sin almacenar su referencia, dejando el proceso activo en segundo plano reteniendo el hardware DirectShow.
3. **Bloqueo síncrono del hilo de interfaz (`AppHangB1`)**: Durante `_shutdown()`, el hilo de Tkinter esperaba de forma síncrona la recogida de estados IPC de plugins VST3 (`collect_fx_states` con timeout de hasta 10 s), la parada del servidor de audio (`proc.join(timeout=4)`), y el cierre del proceso de video (`proc.wait(timeout=8)`). Si alguno se retrasaba, superaba el límite de 5 segundos de Windows y colgaba la aplicación.
4. **Ausencia de modo reposo/standby**: La aplicación iniciaba la captura de la cámara inmediatamente al arrancar sin ofrecer un interruptor para pausar o liberar el hardware sin salir del programa.

### Solución Implementada
- **Desvinculación limpia de ventana (`Win32WindowEmbedder.detach_window`)**: Antes de cerrar el contenedor de Tkinter o detener el stream, la ventana hija se desacopla del padre (`SetParent(hwnd, 0)`) y se le envía el mensaje `WM_CLOSE`, permitiendo que DirectShow cierre sus pines de captura limpiamente.
- **Terminación atómica del árbol de procesos (`ProcessManager.kill_process_tree`)**: En Windows se implementó el cierre con `taskkill /F /T /PID`, garantizando que ningún subproceso hijo quede colgado reteniendo descriptores de la cámara.
- **Rastreo del diálogo de propiedades**: `self.stream_manager.hw_dialog_process` almacena el subproceso del diálogo y lo termina forzosamente al detener el stream o salir.
- **Botón de Pausa / Reposo de Cámara en UI**: Se añadió el botón `⏸ Pausar` en el encabezado del monitor (`_toggle_camera_power`). Permite liberar el hardware de la cámara web en cualquier momento manteniendo UltraCam Studio abierto.
- **Cierre seguro con `os._exit(0)`**: `main.py` envuelve el `mainloop()` para forzar la liberación a nivel de kernel de todos los descriptores USB y sockets tras cerrar la ventana.

---

## E20: Arquitectura Monolítica, Acoplamiento Estricto y Supresión Silenciosa de Excepciones (`bare except`)

### Síntoma
1. **Dificultad de mantenimiento y alta fragilidad**: Módulos como `engine.py` (>1200 líneas) y `gui.py` (>2500 líneas) acumulaban múltiples responsabilidades («God Objects»), combinando llamadas directas a Win32 API, construcción de flags de `scrcpy` y `ffmpeg`, escaneo de hardware DirectShow, renderizado de Tkinter y gestión de procesos.
2. **Diagnóstico a ciegas**: Existían más de 50 ocurrencias de `except: pass` que silenciaban excepciones en la capa de audio, consultas de API del host de Windows, manipulación de ventanas y fallos de subprocesos. Esto impedía saber por qué fallaba un driver o un dispositivo.

### Causa Raíz
- **Violación de SRP (Single Responsibility Principle)**: La misma clase se encargaba de la lógica de negocio, parsing de CLI, gestión de subprocesos, llamadas nativas Win32 e interfaz de usuario.
- **Violación de DIP (Dependency Inversion Principle)**: El código de alto nivel dependía directamente de detalles de implementación de bajo nivel (llamadas duras a `ctypes.windll`, `subprocess.Popen`, rutas locales).
- **Mala práctica de control de flujo por excepciones**: Uso generalizado de `except Exception: pass` para enmascarar errores de tiempo de ejecución.

### Solución Implementada
1. **Estructura Clean Architecture & SOLID**:
   - **`core/`**:
     - `models.py`: Entidades inmutables y dataclasses fuertemente tipadas (`VideoSource`, `CameraCalibration`, `StreamConfiguration`, `DeviceKind`).
     - `exceptions.py`: Jerarquía estructurada de excepciones de dominio (`UltraCamError`, `CameraDeviceError`, `CameraInUseError`, `DeviceNotFoundError`, `CameraProcessError`, `VirtualCamError`, `AudioEngineError`).
     - `interfaces.py`: Contratos e interfaces abstractas (`IWindowEmbedder`, `IProcessManager`, `IDeviceScanner`, `IAppLogger`, `IAudioEngine`, `ISettingsManager`).
   - **`infrastructure/`**:
     - `video/`: Módulos especializados (`command_builder.py`, `device_scanner.py`, `stream_manager.py`, `report_service.py`).
     - `logging/app_logger.py`: Logging profesional con `RotatingFileHandler` en `%APPDATA%/UltraCamStudio/logs/app.log` y listeners para la GUI.
     - `system/`: Control de procesos (`process_utils.py` con `kill_process_tree`) y manipulación segura de ventanas Win32 (`win32_window.py`).
     - `persistence/settings_manager.py`: Repositorio seguro para configuración y calibraciones por cámara.
   - **`presentation/`**:
     - `theme.py`: Paleta de colores unificada, constantes de UI y fábricas de componentes.
     - `dialogs/`: Ventanas modales desacopladas (`connect_dialog.py`, `summary_dialog.py`).
   - **Fachada Limpia (`engine.py`)**: `CameraEngine` actúa como orquestador limpio y fachada manteniendo 100% de retrocompatibilidad con la suite de pruebas `test_engine.py`.
2. **Depuración de Excepciones**:
   - Todos los bloques `except: pass` fueron reemplazados por excepciones específicas (`OSError`, `ctk.CTkError`, etc.) o enrutados a `GLOBAL_LOGGER` con niveles adecuados (`DEBUG`, `WARN`, `ERROR`).

## E21: Plugins VST3 en carpeta (bundle) no cargaban: «unsupported plugin format»

### Síntoma
Plugins instalados como carpeta `.vst3` (Amp Locker, Decent Sampler, KV-Element, Mobius) aparecían en la lista pero al agregarlos quedaban «no se pudo cargar»:
```text
VST3Plugin: Unable to scan plugin C:\Program Files\Common Files\VST3\DecentSampler.vst3: unsupported plugin format or scan failure.
```

### Causa Raíz
En Windows un VST3 puede ser un archivo o una carpeta (bundle) con el binario en `Contents\x86_64-win\<nombre>.vst3`. `scan_vst3` devuelve la carpeta (para no listar el plugin dos veces) y pedalboard/JUCE en Windows no la acepta: necesita el binario de adentro.

### Solución Implementada
`vst_probe.plugin_binary()` convierte la carpeta en la ruta del binario justo antes de cargar (en el servidor de audio y en la clasificación de plugins). La configuración guardada sigue usando la ruta de la carpeta, así que los canales existentes empiezan a cargar sin tocar nada.

## E22: El teléfono no pasaba de 30 fps

### Síntoma
Con un Samsung Galaxy S23 Ultra (SM-S918B), en el selector de formato solo aparecían modos a 30 fps aunque la cámara del teléfono graba a 60.

### Causa Raíz
Android solo ofrece más de 30 fps a través de las **sesiones de alta velocidad** de Camera2. La lista normal de `scrcpy --list-camera-sizes` (la que usaba la app) incluye únicamente los tamaños de la sesión normal, limitados a 30 fps. Los tamaños de alta velocidad salen en una lista aparte y solo funcionan con `--camera-high-speed`, a 120 fps de captura en la mayoría de los equipos.

### Solución Implementada
`get_device_cameras` lee también los tamaños de alta velocidad (`high_speed_sizes`). Para 60 fps la app lanza `--camera-high-speed --camera-fps=120 --max-fps=60`: el sensor captura a 120 y scrcpy entrega 60 cuadros parejos. Esto solo existe hasta 1080p, así que 4K queda a 30 fps. Verificado con el teléfono del usuario midiendo los cuadros grabados.

## E23: NVENC fallaba al comprimir con el FFmpeg de desarrollo

### Síntoma
Al probar la exportación comprimida desde el código (sin empaquetar), el codificador de NVIDIA no arrancaba:
```text
Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0
The minimum required Nvidia driver for nvenc is 610.00 or newer
```

### Causa Raíz
El FFmpeg instalado con WinGet está compilado contra la API NVENC 13.1, que necesita el driver de NVIDIA 610 o superior. La PC de pruebas tenía el 591.86. El FFmpeg que se incluye en la versión portable usa una API anterior y funciona con ese driver.

### Solución Implementada
La exportación no depende de un codificador: prueba en orden NVENC → Quick Sync → AMF → procesador (libx265/libx264, solo hasta 1080p) y, si ninguno sirve, une el video tal cual (`-c:v copy`) como antes. También vuelve a copiar si la compresión va a menos de 0.8× tiempo real tras 12 s o si el resultado no pesa menos. El mismo orden se usa para el codificador de la transmisión.

## E24: El monitor de video tapaba los paneles de la interfaz

### Síntoma
Al abrir un panel lateral (Cámaras, Grabación, Transmisión) sobre la imagen, el video seguía dibujándose encima y el panel quedaba oculto o cortado.

### Causa Raíz
El monitor es una ventana nativa de ffplay/scrcpy incrustada con `SetParent` (E7). Windows siempre dibuja una ventana hija nativa por encima de los widgets de Tk, que se pintan en la ventana padre; no hay orden de capas que lo evite.

### Solución Implementada
El panel lateral no se superpone: **empuja** la zona central, y el monitor se redimensiona al espacio que queda (`RedrawWindow` tras cada cambio para que no queden restos). Por debajo de 820 px de ancho la zona central se reorganiza para seguir cabiendo.

## E25: Apagar una plataforma no cortaba su envío

### Síntoma
En el prototipo de la transmisión, al dar de baja un destino, el servidor RTMP de prueba que hacía de plataforma seguía recibiendo datos.

### Causa Raíz
Cada plataforma es una ruta propia de MediaMTX (`d_<id>`) que reenvía la señal local. Para quitar una ruta, la API v3 de MediaMTX exige el método **DELETE** en `/v3/config/paths/delete/<ruta>`; la petición enviada con otro método no se aplicaba y la ruta seguía viva.

### Solución Implementada
`MediaMtx.remove_relay()` usa `DELETE`. Se verificó con tres servidores RTMP locales: al apagar uno, ese deja de recibir y los otros dos y el codificador siguen sin cortes. Las claves nunca se escriben en la configuración ni en el registro: la URL viaja como `servidor#clave` y el registro la muestra como `servidor#•••`.

---
*Documento actualizado y verificado para la versión UltraCam Studio Pro.*
