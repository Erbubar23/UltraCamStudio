# Avisos de terceros

UltraCam Studio se distribuye bajo la licencia [GPLv3](LICENSE) e incluye o usa los siguientes componentes. Cada uno conserva su propia licencia.

## Incluidos en el código fuente

| Componente | Licencia | Uso |
|---|---|---|
| [Softcam](https://github.com/tshino/softcam) (estructura del filtro DirectShow) | MIT | `vcam_driver/` — ver [`vcam_driver/third_party/LICENSE-softcam.txt`](vcam_driver/third_party/LICENSE-softcam.txt) |
| DirectShow BaseClasses (Microsoft, vía Softcam) | MIT | `vcam_driver/third_party/baseclasses/` |

## Dependencias de Python (`requirements.txt`)

| Paquete | Licencia |
|---|---|
| [pedalboard](https://github.com/spotify/pedalboard) | GPLv3 |
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | MIT |
| [numpy](https://numpy.org) | BSD-3-Clause |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) | Apache 2.0 |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT |

## Programas externos incluidos en la versión portable

Se descargan durante `packaging/build.ps1` y se ejecutan como procesos aparte.

| Programa | Licencia | Código fuente |
|---|---|---|
| [FFmpeg](https://ffmpeg.org) (build `gpl-shared` de BtbN) | GPLv3 | https://github.com/BtbN/FFmpeg-Builds · https://ffmpeg.org/download.html |
| [scrcpy](https://github.com/Genymobile/scrcpy) (incluye adb) | Apache 2.0 | https://github.com/Genymobile/scrcpy |

Los textos de licencia de FFmpeg y scrcpy van en `bin/ffmpeg/LICENSE.txt` y `bin/scrcpy/LICENSE.txt` dentro del paquete.
