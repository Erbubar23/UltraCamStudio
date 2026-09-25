#include "SharedFrames.h"

#include <cstring>

#include "Convert.h"

namespace ultracam {

namespace {

uint32_t tickNow()
{
    return static_cast<uint32_t>(GetTickCount64() & 0xFFFFFFFFu);
}

} // namespace

SharedFrames::~SharedFrames()
{
    close();
}

bool SharedFrames::open()
{
    if (m_view)
    {
        return true;
    }
    // Sin la app abierta la memoria no existe: se reintenta como mucho dos veces
    // por segundo para no gastar CPU dentro del programa que usa la cámara.
    const ULONGLONG now = GetTickCount64();
    if (now < m_nextOpenTry)
    {
        return false;
    }
    m_nextOpenTry = now + 500;

    m_mapping = OpenFileMappingW(FILE_MAP_READ, FALSE, kSharedMemoryName);
    if (!m_mapping)
    {
        return false;
    }
    m_view = static_cast<const uint8_t*>(MapViewOfFile(m_mapping, FILE_MAP_READ, 0, 0, 0));
    if (!m_view)
    {
        close();
        return false;
    }
    MEMORY_BASIC_INFORMATION info{};
    VirtualQuery(m_view, &info, sizeof(info));
    m_viewSize = info.RegionSize;
    return true;
}

void SharedFrames::close()
{
    if (m_view)
    {
        UnmapViewOfFile(m_view);
        m_view = nullptr;
    }
    if (m_mapping)
    {
        CloseHandle(m_mapping);
        m_mapping = nullptr;
    }
    m_viewSize = 0;
}

bool SharedFrames::copyLatest(const volatile SharedHeader* h)
{
    const uint32_t width = h->width;
    const uint32_t height = h->height;
    const uint32_t slotSize = h->slot_size;
    const uint32_t dataOffset = h->data_offset;
    const uint32_t slot = h->latest_slot;
    if (width == 0 || height == 0 || width > 7680 || height > 4320 || (width | height) & 1 ||
        slotSize != nv12Size(static_cast<int>(width), static_cast<int>(height)) || slot >= kSlotCount ||
        dataOffset < sizeof(SharedHeader) ||
        static_cast<std::size_t>(dataOffset) + static_cast<std::size_t>(slotSize) * kSlotCount > m_viewSize)
    {
        return false;
    }

    const uint32_t before = h->slot_seq[slot];
    if (before == 0)
    {
        return false;   // la app está escribiendo justo este slot
    }
    if (m_frame.size() != slotSize)
    {
        m_frame.resize(slotSize);
    }
    MemoryBarrier();
    std::memcpy(m_frame.data(), m_view + dataOffset + static_cast<std::size_t>(slot) * slotSize, slotSize);
    MemoryBarrier();
    if (h->slot_seq[slot] != before)
    {
        return false;   // se sobrescribió durante la copia: se descarta
    }
    m_width = static_cast<int>(width);
    m_height = static_cast<int>(height);
    return true;
}

SourceState SharedFrames::poll(bool& fresh)
{
    fresh = false;
    if (!open())
    {
        return SourceState::AppClosed;
    }
    const volatile SharedHeader* h = reinterpret_cast<const volatile SharedHeader*>(m_view);
    if (h->magic != kMagic || h->version != kVersion)
    {
        return SourceState::AppClosed;   // la app aún está inicializando la memoria
    }

    const uint32_t now = tickNow();
    const uint32_t seq = h->frame_seq;
    if (seq != 0 && seq != m_lastSeq && copyLatest(h))
    {
        m_lastSeq = seq;
        m_haveFrame = true;
        fresh = true;
    }

    const bool appAlive = static_cast<uint32_t>(now - h->heartbeat_tick) <= kAppAliveMs;
    const bool recent = static_cast<uint32_t>(now - h->frame_tick) <= kHoldLastFrameMs;
    if (m_haveFrame && recent && appAlive)
    {
        return SourceState::Live;
    }
    return appAlive ? SourceState::NoSignal : SourceState::AppClosed;
}

} // namespace ultracam
