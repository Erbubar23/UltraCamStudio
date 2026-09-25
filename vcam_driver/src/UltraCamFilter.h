#pragma once
// Filtro de captura DirectShow «UltraCam».
//
// Se comporta como una webcam física: ofrece una lista fija de modos, el programa
// que la abre elige uno y ese formato ya no cambia durante la sesión. Siempre
// entrega cuadros al ritmo del modo: imagen de la app, el último cuadro retenido
// o un cartel. Basado en la estructura del filtro de Softcam (MIT, tshino).

#include <streams.h>

#include <cstdint>
#include <memory>
#include <vector>

#include "SharedFrames.h"
#include "Slate.h"

namespace ultracam {

struct VideoMode
{
    int width;
    int height;
    int fps;
};

class UltraCamPin;

class UltraCamFilter : public CSource, public IAMStreamConfig
{
public:
    static CUnknown* WINAPI CreateInstance(LPUNKNOWN outer, HRESULT* hr);

    DECLARE_IUNKNOWN
    STDMETHODIMP NonDelegatingQueryInterface(REFIID riid, void** ppv) override;

    // IAMStreamConfig: algunos programas lo piden al filtro y no al pin.
    STDMETHODIMP SetFormat(AM_MEDIA_TYPE* pmt) override;
    STDMETHODIMP GetFormat(AM_MEDIA_TYPE** ppmt) override;
    STDMETHODIMP GetNumberOfCapabilities(int* count, int* size) override;
    STDMETHODIMP GetStreamCaps(int index, AM_MEDIA_TYPE** ppmt, BYTE* caps) override;

private:
    UltraCamFilter(LPUNKNOWN outer, HRESULT* hr);
    UltraCamPin* pin();
};

class UltraCamPin : public CSourceStream, public IKsPropertySet, public IAMStreamConfig
{
public:
    UltraCamPin(HRESULT* hr, UltraCamFilter* filter);

    DECLARE_IUNKNOWN
    STDMETHODIMP NonDelegatingQueryInterface(REFIID riid, void** ppv) override;

    // Negociación de formato
    HRESULT GetMediaType(int position, CMediaType* pmt) override;
    HRESULT CheckMediaType(const CMediaType* pmt) override;
    HRESULT DecideBufferSize(IMemAllocator* alloc, ALLOCATOR_PROPERTIES* props) override;
    STDMETHODIMP Notify(IBaseFilter* sender, Quality q) override;

    // Hilo de entrega
    HRESULT OnThreadCreate() override;
    HRESULT OnThreadDestroy() override;
    HRESULT FillBuffer(IMediaSample* sample) override;

    // IAMStreamConfig
    STDMETHODIMP SetFormat(AM_MEDIA_TYPE* pmt) override;
    STDMETHODIMP GetFormat(AM_MEDIA_TYPE** ppmt) override;
    STDMETHODIMP GetNumberOfCapabilities(int* count, int* size) override;
    STDMETHODIMP GetStreamCaps(int index, AM_MEDIA_TYPE** ppmt, BYTE* caps) override;

    // IKsPropertySet: marca el pin como de captura (lo exigen Zoom, OBS, etc.)
    STDMETHODIMP Set(REFGUID set, DWORD id, LPVOID instance, DWORD instanceSize,
                     LPVOID data, DWORD dataSize) override;
    STDMETHODIMP Get(REFGUID set, DWORD id, LPVOID instance, DWORD instanceSize,
                     LPVOID data, DWORD dataSize, DWORD* returned) override;
    STDMETHODIMP QuerySupported(REFGUID set, DWORD id, DWORD* support) override;

private:
    void waitForNextFrame();
    const std::vector<uint8_t>& slate(SlateKind kind);

    // Formato fijado con SetFormat antes de conectar (si el programa lo pidió).
    CMediaType m_requested;
    bool m_hasRequested = false;

    // Estado del hilo de entrega (solo se toca desde ese hilo).
    VideoMode m_mode{};
    bool m_yuy2 = false;
    SharedFrames m_source;
    std::vector<uint8_t> m_live;        // último cuadro de la app, ya al tamaño del modo
    bool m_haveLive = false;
    std::vector<uint8_t> m_slates[2];
    HANDLE m_timer = nullptr;
    bool m_timerHighRes = false;
    LARGE_INTEGER m_qpcFreq{};
    LONGLONG m_qpcStart = 0;
    LONGLONG m_frameIndex = 0;
};

} // namespace ultracam
