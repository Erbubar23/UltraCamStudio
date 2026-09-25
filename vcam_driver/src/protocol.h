#pragma once
//
// Contrato de memoria compartida entre UltraCam Studio (escribe) y el driver (lee).
//
// La app crea una "file mapping" con nombre y deja ahí los cuadros en NV12. El
// driver vive dentro de cada programa que usa la cámara (Zoom, Teams, OBS…) y
// solo lee. Si la app está cerrada, el driver dibuja su propio cartel: por eso
// la cámara nunca se queda en negro ni se desconecta.
//
// Todos los campos son uint32 little-endian: las escrituras de 32 bits alineadas
// son atómicas en x86/x64, así un lector nunca ve un valor a medio escribir.
// Los tiempos son GetTickCount64() & 0xFFFFFFFF (ms); la edad se calcula con
// resta sin signo, que tolera el desborde cada ~49 días.
//
// Escritura de un cuadro (app):
//   1. slot = (latest_slot + 1) % slot_count
//   2. slot_seq[slot] = 0            (el slot queda "en obras")
//   3. copiar NV12 a data_offset + slot * slot_size
//   4. slot_seq[slot] = frame_seq + 1
//   5. latest_slot = slot; frame_tick = ahora; frame_seq = frame_seq + 1
// Además, heartbeat_tick = ahora al menos cada 500 ms mientras la app está abierta.
//
// Lectura (driver): leer latest_slot y su slot_seq, copiar el cuadro y volver a
// leer slot_seq; si cambió o es 0, el cuadro se descarta y se repite el anterior.
// Con tres slots el escritor tendría que dar dos vueltas durante una copia.
//
// El formato lo fijan width/height del encabezado (la app envía 1920x1080). El
// driver escala al modo que eligió cada programa, así un cambio de fuente nunca
// cambia el formato que ellos ven.
//
// Este archivo es la referencia; el lado Python está en
// infrastructure/video/vcam_writer.py y debe mantenerse igual.

#include <cstdint>

namespace ultracam {

constexpr wchar_t kSharedMemoryName[] = L"Local\\UltraCamStudio.VirtualCamera.v1";
constexpr uint32_t kMagic = 0x43564355;   // "UCVC"
constexpr uint32_t kVersion = 1;
constexpr uint32_t kSlotCount = 3;
constexpr uint32_t kDataOffset = 4096;

// Tras este tiempo sin cuadros nuevos se muestra el cartel (se retiene el último
// cuadro mientras tanto, para que un cambio de fuente no parpadee).
constexpr uint32_t kHoldLastFrameMs = 1500;
// Sin latido de la app durante este tiempo se considera cerrada.
constexpr uint32_t kAppAliveMs = 2000;

#pragma pack(push, 4)
struct SharedHeader
{
    uint32_t magic;
    uint32_t version;
    uint32_t width;
    uint32_t height;
    uint32_t slot_count;
    uint32_t slot_size;
    uint32_t data_offset;
    uint32_t latest_slot;
    uint32_t frame_seq;
    uint32_t frame_tick;
    uint32_t heartbeat_tick;
    uint32_t fps;
    uint32_t slot_seq[kSlotCount];
    uint32_t reserved;
};
#pragma pack(pop)

static_assert(sizeof(SharedHeader) == 64, "el encabezado debe medir 64 bytes");

} // namespace ultracam
