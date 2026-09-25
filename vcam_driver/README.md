# Driver de cámara virtual «UltraCam»

Filtro DirectShow propio que aparece en Windows como la cámara **UltraCam**. No depende de OBS.

- **Funciona en** Zoom, Teams, Discord, Google Meet, OBS y los navegadores (Chrome, Edge, Firefox).
- **No lo ven** las apps que solo usan Media Foundation, como la app Cámara de Windows.

## Cómo funciona

```
UltraCam Studio ──(NV12 1080p, memoria compartida)──▶ ultracam-vcam64.dll ──▶ Zoom / Teams / OBS…
                  infrastructure/video/vcam_driver.py    (cargada dentro de cada programa)
```

- La app escribe los cuadros en una memoria compartida con nombre. El contrato está en [`src/protocol.h`](src/protocol.h) y el lado Python en `infrastructure/video/vcam_driver.py`; ambos deben coincidir.
- El driver se comporta como una webcam física. Ofrece 1080p y 720p a 30 y 60 fps, y 360p a 30 fps, en NV12 y en YUY2. Cada programa elige un modo al abrir la cámara, y ese modo no cambia en toda la sesión.
- **Nunca entrega negro ni se congela:**
  - Si deja de llegar imagen (por ejemplo, al cambiar de fuente), retiene el último cuadro durante 1,5 s.
  - Después muestra el cartel «Sin señal».
  - Si la app está cerrada, muestra «UltraCam Studio está cerrado».
  - Los carteles se dibujan en el propio driver, en español o inglés según el idioma de Windows.

## Compilar

Requiere Visual Studio 2022 o Build Tools 2022 con «Desarrollo para el escritorio con C++».

```powershell
powershell -ExecutionPolicy Bypass -File vcam_driver\build.ps1
```

El script deja `ultracam-vcam64.dll` y `ultracam-vcam32.dll` en `vcam_driver\bin\`. La DLL de 32 bits es para programas de 32 bits.

## Registrar

- **Por usuario, sin administrador:** lo hace la app al arrancar con `vcam_driver.register()`, que escribe en `HKCU`.
- **Para todo el equipo** (instalador): `regsvr32 ultracam-vcam64.dll` y, con el `regsvr32` de `SysWOW64`, la de 32 bits.

## Probar

```powershell
py vcam_driver\tests\test_vcam_driver.py
```

Las pruebas usan ffmpeg como si fuera Zoom y registran la cámara temporalmente como «UltraCam Test». Verifican:

- los carteles;
- la imagen en vivo;
- 10 cambios de fuente seguidos sin desconexión;
- los modos;
- el cierre de la app.

## Créditos

- La estructura del filtro está basada en [Softcam](https://github.com/tshino/softcam) (MIT, © tshino). Ver `third_party/LICENSE-softcam.txt`.
- `third_party/baseclasses` son las clases base de DirectShow de Microsoft (Windows-classic-samples, MIT), tal como las incluye Softcam.
