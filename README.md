# UltraCam Studio Pro - Universal Mobile 4K, PC Cameras & Audio Studio para Windows

Suite de producción audiovisual y streaming nativa para Windows, compatible con **Cámaras de PC / Webcams USB / Capturadoras HDMI**, **Android (12+)** (Samsung Galaxy, Google Pixel, Xiaomi, Motorola, etc.) y **Apple iPhone (iOS)**, equipada con un **monitor de video 100% integrado dentro de la app (Win32 `SetParent`)**, un **panel de control y calibración de video profesional (ProcAmp y DirectShow Hardware)**, un **mezclador de audio profesional estilo DAW (OBS / REAPER)** y una suite avanzada de **post-grabación multipista sin pérdida**.

---

## 🌟 Características Principales

### 🎥 Compatibilidad Universal de Video y Cámaras de PC
- **Detección Universal (Zero Hardcoding)**: Reconoce automáticamente cualquier fuente de captura de video en Windows:
  - **Webcams USB**: Logitech (C505, C920, Brio 4K), Razer Kiyo, Elgato Facecam, Insta360 Link, cámaras UVC genéricas.
  - **Capturadoras HDMI**: Elgato Cam Link 4K, EVGA XR1, dongles USB3 para cámaras DSLR y Mirrorless (Sony, Canon, Nikon, Fujifilm).
  - **Cámaras Integradas**: Cámaras de laptops y todo-en-uno.
  - **Cámaras Virtuales**: OBS Virtual Camera, vMix, etc.
  - **Móviles**: Android 4K 60fps vía scrcpy y iPhone vía DirectShow / Red.
- **Sondeo Inteligente de Capacidades**: Consulta las resoluciones y tasas de cuadros reales de cada sensor (`probe_camera_capabilities`) y prioriza códec `MJPEG` para desbloquear 30 o 60 FPS estables sin saturar el bus USB 2.0.
- **Monitor 100% Integrado (Cero Popups)**: Cualquier cámara se visualiza incrustada dentro del marco de la aplicación mediante reparenting nativo Win32 (`SetParent`).

### 🎛️ Herramienta de Control y Calibración de Video
- **⚙️ Acceso Directo a Propiedades de Hardware**: Botón para abrir el panel de control oficial del driver DirectShow de Windows para fijar **Exposición manual** (evita parpadeos), **Balance de Blancos** y **Enfoque manual** (elimina el "focus hunting" en grabaciones musicales).
- **Calibración ProcAmp en Tiempo Real**: Sliders de Brillo, Contraste, Saturación y Nitidez (Unsharp mask).
- **Presets de Calidad de Estudio en 1 Clic**:
  - 🌟 **Studio Pro**: Máxima resolución nativa, códec optimizado y realce de nitidez.
  - ⚡ **Fluidez 60 FPS**: Prioriza 60 cuadros por segundo para transmisiones fluidas.
  - 🎸 **Músico / Performance**: Configuración recomendada para músicos e instrumentos con advertencia de bloqueo de enfoque.
  - 🌙 **Baja Luz / Anti-Ruido**: Compensación lumínica para salas oscuras.
  - 💾 **Guardado de Perfiles**: Recuerda automáticamente tus ajustes preferidos por cámara (`camera_presets.json`).

### 🎚️ Motor de Audio Estilo DAW (JUCE / Ableton / Reaper)
- **Dispositivo principal ASIO o Windows Audio**: con ASIO (p. ej. Behringer UMC) la latencia ida y vuelta baja a ~10 ms (búfer 128). Frecuencia, búfer, latencia calculada, carga de CPU y cortes a la vista; acceso al panel del driver ASIO.
- **Canales libres**: agrega los que necesites. Cada canal toma una entrada del dispositivo principal, otro dispositivo de Windows o «lo que suena» en una salida (loopback), con mono/estéreo, volumen, M, S y vúmetro.
- **Efectos VST3 por canal**: carga plugins como Tonocracy dentro de UltraCam, abre su ventana y el preset se guarda solo. El audio y los plugins corren en un proceso aparte: si un plugin falla, la app sigue abierta.
- **Bus Monitor**: te escuchas por la salida del dispositivo principal, con el tono del VST, sin el retraso de la grabación.
- **Compensación de deriva**: las fuentes extra se sincronizan con el reloj principal con remuestreo adaptativo.
- **Zero Hardcoding**: Detección dinámica de cualquier interfaz (Focusrite, Behringer UMC, MOTU, Audient, Steinberg, Realtek y micrófonos USB).

### 🎥 Cámara Virtual Universal para Windows
- **Driver propio, sin OBS**: «UltraCam» es un filtro DirectShow de este proyecto ([`vcam_driver/`](vcam_driver/README.md)). La app lo registra para tu usuario al abrirse (sin permisos de administrador) y Zoom, Discord, Google Meet, Microsoft Teams, OBS Studio y los navegadores la ven siempre en su lista. Convive con la cámara virtual de OBS.
- **Nunca negro ni desconectada**: sin imagen muestra el cartel «Sin señal»; con UltraCam Studio cerrado, «UltraCam Studio está cerrado». Los demás programas siguen conectados y la imagen vuelve sola al reabrir la app.
- **Sigue a la cámara que elijas**: al cambiar de fuente mantiene el último cuadro hasta que llega la nueva (sin parpadeo). El botón «Cámara Virtual» la pone en pausa. Si un teléfono se desconecta, la app lo espera y reanuda sola.
- **Como una webcam real**: cada programa elige su modo al abrir la cámara (1080p o 720p a 30/60 fps, 360p; NV12 o YUY2) y ese formato no cambia en toda la sesión. Una fuente vertical se ve centrada con franjas.
- **Sin robarle velocidad a la grabación**: la calibración se calcula una sola vez para todas las salidas y el archivo conserva la resolución y los fps nativos de la cámara. Si la PC tiene GPU con codificador de video (NVIDIA, Intel Quick Sync, AMD o Media Foundation), la grabación la usa automáticamente.

### 📱 Vertical 9:16 para redes
- **Teléfono**: graba en vertical a resolución completa (el teléfono captura girado).
- **Webcam**: recorte central 9:16, o «Girar» si la cámara está montada de lado (sin perder resolución). Las tomas llevan «_vertical» en el nombre.

### 🎬 Suite de Post-Grabación Avanzada
- **Multiplexado Instantáneo con FFmpeg (`-c:v copy`)**: Une video intacto con el audio en menos de 2 segundos sin consumir CPU.
- **Audio Multipista Embebido**: El archivo `.mp4` almacena la Pista 1 (Mezcla Master) y una pista por cada canal del mezclador, con su nombre.
- **Exportación de Stems WAV**: Tomas individuales sin comprimir a 24-bit / 48kHz en la subcarpeta `stems/`.
- **DSP y Normalización EBU R128**: la mezcla final a −14 LUFS o con techo de −1 dBFS; las pistas por canal quedan tal cual para editar. Calibrador de sincronización audio/video (+/- ms).
- **Audio alineado desde el clic**: el audio empieza a grabar al pulsar «Grabar» y al unir se recorta la diferencia exacta con el primer cuadro de la cámara.

---

## 📁 Registro de Ingeniería

Para consultar el análisis técnico detallado de los problemas superados durante el desarrollo (protocolo Android 16, cables USB lentos, mismatch de sample rates, ingesta de iPhone, monitor integrado con Win32 SetParent, matriz de audio multi-entrada, y estrangulamiento USB en webcams con MJPEG), revisa:
📄 **[ERRORS_RESOLVED.md](ERRORS_RESOLVED.md)**

---

## 🚀 Inicio Rápido

1. Descomprime `UltraCamStudio-Portable-<versión>.zip` donde quieras y abre `UltraCamStudio.exe` (o ejecuta `Iniciar_GalaxyCamPro.bat` desde el código). No hay que instalar nada.
2. Todas las cámaras aparecen juntas en la lista de la izquierda. Al elegir una, la imagen aparece sola.
3. En el panel derecho: resolución/fps de la cámara y el **Mezclador** (FX, 🎧 monitor, S, M, volumen). «+ Canal» agrega una fuente.
4. Todo lo demás está en **⚙ Configuración**: General · Video · Audio · Canales y efectos · Grabación · Cámara Virtual · Avanzado.
5. Pulsa **Grabar** y luego **Detener y guardar**: el MP4 multipista aparece en «Tomas recientes».

## 📦 Crear la versión portable

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1              # ZIP portable
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Installer   # además, instalador
```

Requiere **Build Tools para Visual Studio 2022** con «Desarrollo para el escritorio con C++» para compilar el driver de la cámara virtual.

## 🧪 Pruebas

```powershell
py test_engine.py                          # app: motor, interfaz, grabación, avisos
py vcam_driver\tests\test_vcam_driver.py   # driver: carteles, modos, 32/64 bits, cambios de fuente
```

## 🌍 Traducir la interfaz

Todos los textos están en [`presentation/strings.py`](presentation/strings.py): copia el diccionario `ES`, tradúcelo y regístralo en `CATALOGS`. Lo que falte se muestra en español.

Genera `dist\UltraCamStudio-Portable-<versión>.zip` con la app empaquetada (no requiere Python), FFmpeg, scrcpy y el motor de audio. La configuración se guarda en la carpeta `data` junto al `.exe` (si esa carpeta no admite escritura, en `%APPDATA%\UltraCamStudio`).


## 📜 Licencia

UltraCam Studio es software libre bajo la licencia **GNU GPLv3**: puedes usarlo, estudiarlo, modificarlo y compartirlo, siempre que las versiones que distribuyas también sean GPLv3 con su código fuente. Ver [`LICENSE`](LICENSE) y los componentes de terceros en [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Copyright © 2026 UltraCam Studio
