#include "Convert.h"

#include <cstring>
#include <vector>

namespace ultracam {

namespace {

// Escala un plano de `C` canales intercalados con interpolación bilineal en
// punto fijo 16.16. Muestrea en el centro de cada píxel para no desplazar la imagen.
template <int C>
void scalePlane(const uint8_t* src, int sw, int sh, uint8_t* dst, int dw, int dh)
{
    if (sw == dw && sh == dh)
    {
        std::memcpy(dst, src, static_cast<std::size_t>(sw) * sh * C);
        return;
    }
    const int64_t stepX = (static_cast<int64_t>(sw) << 16) / dw;
    const int64_t stepY = (static_cast<int64_t>(sh) << 16) / dh;

    // Columnas de origen y pesos, calculados una sola vez por cuadro.
    std::vector<int> x0(dw), x1(dw), wx(dw);
    for (int x = 0; x < dw; ++x)
    {
        int64_t fx = x * stepX + stepX / 2 - (1 << 15);
        if (fx < 0) fx = 0;
        int ix = static_cast<int>(fx >> 16);
        if (ix > sw - 1) ix = sw - 1;
        x0[x] = ix * C;
        x1[x] = (ix + 1 < sw ? ix + 1 : ix) * C;
        wx[x] = static_cast<int>((fx >> 8) & 0xFF);
    }
    for (int y = 0; y < dh; ++y)
    {
        int64_t fy = y * stepY + stepY / 2 - (1 << 15);
        if (fy < 0) fy = 0;
        int iy = static_cast<int>(fy >> 16);
        if (iy > sh - 1) iy = sh - 1;
        const int iy1 = iy + 1 < sh ? iy + 1 : iy;
        const int wy = static_cast<int>((fy >> 8) & 0xFF);
        const uint8_t* r0 = src + static_cast<std::size_t>(iy) * sw * C;
        const uint8_t* r1 = src + static_cast<std::size_t>(iy1) * sw * C;
        uint8_t* out = dst + static_cast<std::size_t>(y) * dw * C;
        for (int x = 0; x < dw; ++x)
        {
            for (int c = 0; c < C; ++c)
            {
                const int a = r0[x0[x] + c], b = r0[x1[x] + c];
                const int d = r1[x0[x] + c], e = r1[x1[x] + c];
                const int top = a * 256 + (b - a) * wx[x];
                const int bottom = d * 256 + (e - d) * wx[x];
                const int v = top * 256 + (bottom - top) * wy;
                *out++ = static_cast<uint8_t>((v + (1 << 15)) >> 16);
            }
        }
    }
}

inline uint8_t clamp8(int v)
{
    return static_cast<uint8_t>(v < 0 ? 0 : (v > 255 ? 255 : v));
}

} // namespace

void scaleNV12(const uint8_t* src, int srcW, int srcH, uint8_t* dst, int dstW, int dstH)
{
    scalePlane<1>(src, srcW, srcH, dst, dstW, dstH);
    scalePlane<2>(src + static_cast<std::size_t>(srcW) * srcH, srcW / 2, srcH / 2,
                  dst + static_cast<std::size_t>(dstW) * dstH, dstW / 2, dstH / 2);
}

void nv12ToYUY2(const uint8_t* nv12, int width, int height, uint8_t* yuy2)
{
    const uint8_t* uvPlane = nv12 + static_cast<std::size_t>(width) * height;
    for (int y = 0; y < height; ++y)
    {
        const uint8_t* yRow = nv12 + static_cast<std::size_t>(y) * width;
        const uint8_t* uvRow = uvPlane + static_cast<std::size_t>(y / 2) * width;
        uint8_t* out = yuy2 + static_cast<std::size_t>(y) * width * 2;
        for (int x = 0; x < width; x += 2)
        {
            *out++ = yRow[x];
            *out++ = uvRow[x];
            *out++ = yRow[x + 1];
            *out++ = uvRow[x + 1];
        }
    }
}

void bgraToNV12(const uint8_t* bgra, int width, int height, int stride, uint8_t* nv12)
{
    uint8_t* yPlane = nv12;
    uint8_t* uvPlane = nv12 + static_cast<std::size_t>(width) * height;
    for (int y = 0; y < height; ++y)
    {
        const uint8_t* p = bgra + static_cast<std::size_t>(y) * stride;
        uint8_t* yRow = yPlane + static_cast<std::size_t>(y) * width;
        for (int x = 0; x < width; ++x, p += 4)
        {
            yRow[x] = clamp8(((66 * p[2] + 129 * p[1] + 25 * p[0] + 128) >> 8) + 16);
        }
    }
    for (int y = 0; y < height; y += 2)
    {
        uint8_t* uvRow = uvPlane + static_cast<std::size_t>(y / 2) * width;
        for (int x = 0; x < width; x += 2)
        {
            // Promedio de 2x2 píxeles para cada muestra de color.
            int r = 0, g = 0, b = 0;
            for (int dy = 0; dy < 2; ++dy)
            {
                const uint8_t* p = bgra + static_cast<std::size_t>(y + dy) * stride + static_cast<std::size_t>(x) * 4;
                b += p[0] + p[4];
                g += p[1] + p[5];
                r += p[2] + p[6];
            }
            r /= 4; g /= 4; b /= 4;
            uvRow[x] = clamp8(((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128);
            uvRow[x + 1] = clamp8(((112 * r - 94 * g - 18 * b + 128) >> 8) + 128);
        }
    }
}

} // namespace ultracam
