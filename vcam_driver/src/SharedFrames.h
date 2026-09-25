#pragma once
// Lado lector del contrato de protocol.h: lo usa cada instancia del filtro.

#include <windows.h>
#include <cstdint>
#include <vector>

#include "protocol.h"

namespace ultracam {

enum class SourceState
{
    Live,       // hay imagen reciente (o se retiene la última durante un cambio de fuente)
    NoSignal,   // la app está abierta pero no envía imagen
    AppClosed,  // la app no está abierta
};

class SharedFrames
{
public:
    SharedFrames() = default;
    ~SharedFrames();
    SharedFrames(const SharedFrames&) = delete;
    SharedFrames& operator=(const SharedFrames&) = delete;

    // Revisa la memoria compartida. `fresh` indica si frame() cambió desde la
    // última llamada (así quien llama solo reescala cuando hace falta).
    SourceState poll(bool& fresh);

    // Último cuadro válido en NV12, de tamaño width() x height().
    const uint8_t* frame() const { return m_frame.data(); }
    int width() const { return m_width; }
    int height() const { return m_height; }

private:
    bool open();
    void close();
    bool copyLatest(const volatile SharedHeader* h);

    HANDLE m_mapping = nullptr;
    const uint8_t* m_view = nullptr;
    std::size_t m_viewSize = 0;
    ULONGLONG m_nextOpenTry = 0;

    std::vector<uint8_t> m_frame;
    int m_width = 0;
    int m_height = 0;
    bool m_haveFrame = false;
    uint32_t m_lastSeq = 0;
};

} // namespace ultracam
