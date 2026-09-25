#pragma once
// Conversiones de imagen del driver. Todo trabaja en NV12 (Y completo + UV
// intercalado a media resolución), que es lo que envía la app.

#include <cstdint>
#include <cstddef>

namespace ultracam {

inline std::size_t nv12Size(int width, int height)
{
    return static_cast<std::size_t>(width) * height * 3 / 2;
}

inline std::size_t yuy2Size(int width, int height)
{
    return static_cast<std::size_t>(width) * height * 2;
}

// Escala un cuadro NV12 a otro tamaño (bilineal). Si el tamaño coincide, copia.
void scaleNV12(const uint8_t* src, int srcW, int srcH, uint8_t* dst, int dstW, int dstH);

// Empaqueta NV12 en YUY2 (Y0 U Y1 V), para programas que no aceptan NV12.
void nv12ToYUY2(const uint8_t* nv12, int width, int height, uint8_t* yuy2);

// Convierte una imagen BGRA (de arriba abajo) a NV12, BT.601 rango limitado:
// la misma matriz que usa ffmpeg por defecto al generar los cuadros de la app.
void bgraToNV12(const uint8_t* bgra, int width, int height, int stride, uint8_t* nv12);

} // namespace ultracam
