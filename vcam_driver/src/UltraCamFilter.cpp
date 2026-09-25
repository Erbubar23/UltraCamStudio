#include "UltraCamFilter.h"

#include <cstring>
#include <cstdlib>

#include "Convert.h"
#include "guids.h"

#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002
#endif

namespace ultracam {

namespace {

// Modos que ofrece la cámara, como una webcam física. El primero es el de
// omisión. La app siempre envía 1920x1080; el driver escala al modo elegido.
constexpr VideoMode kModes[] = {
    {1920, 1080, 30},
    {1280, 720, 30},
    {640, 360, 30},
    {1920, 1080, 60},
    {1280, 720, 60},
};
constexpr int kModeCount = static_cast<int>(sizeof(kModes) / sizeof(kModes[0]));
// Cada modo en NV12 (preferido) y en YUY2 (para programas que no aceptan NV12).
constexpr int kCapCount = kModeCount * 2;

std::size_t frameBytes(const VideoMode& m, bool yuy2)
{
    return yuy2 ? yuy2Size(m.width, m.height) : nv12Size(m.width, m.height);
}

// Duración de un cuadro en unidades de 100 ns. Los programas no se ponen de acuerdo
// al convertir «60 fps»: ffmpeg trunca (166666) y otros redondean (166667). Las
// capacidades ofrecen ese rango para que cualquiera de los dos case.
REFERENCE_TIME frameInterval(const VideoMode& m)
{
    return UNITS / m.fps;
}

REFERENCE_TIME frameIntervalMax(const VideoMode& m)
{
    return (UNITS + m.fps - 1) / m.fps;
}

HRESULT fillType(CMediaType* mt, const VideoMode& m, bool yuy2)
{
    mt->InitMediaType();
    auto* vih = reinterpret_cast<VIDEOINFOHEADER*>(mt->AllocFormatBuffer(sizeof(VIDEOINFOHEADER)));
    if (!vih)
    {
        return E_OUTOFMEMORY;
    }
    ZeroMemory(vih, sizeof(VIDEOINFOHEADER));
    const std::size_t size = frameBytes(m, yuy2);
    vih->AvgTimePerFrame = frameInterval(m);
    vih->dwBitRate = static_cast<DWORD>(size * 8 * m.fps);
    vih->bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    vih->bmiHeader.biWidth = m.width;
    vih->bmiHeader.biHeight = m.height;   // en YUV, positivo = de arriba abajo
    vih->bmiHeader.biPlanes = 1;
    vih->bmiHeader.biBitCount = yuy2 ? 16 : 12;
    vih->bmiHeader.biCompression = yuy2 ? MAKEFOURCC('Y', 'U', 'Y', '2') : MAKEFOURCC('N', 'V', '1', '2');
    vih->bmiHeader.biSizeImage = static_cast<DWORD>(size);

    mt->SetType(&MEDIATYPE_Video);
    mt->SetSubtype(yuy2 ? &MEDIASUBTYPE_YUY2 : &MEDIASUBTYPE_NV12);
    mt->SetFormatType(&FORMAT_VideoInfo);
    mt->SetTemporalCompression(FALSE);
    mt->SetSampleSize(static_cast<ULONG>(size));
    return S_OK;
}

// Reconoce un tipo pedido por un programa y lo traduce a uno de nuestros modos.
// Sin fps indicados (AvgTimePerFrame = 0) se toma el primer modo de ese tamaño.
bool parseType(const AM_MEDIA_TYPE* mt, VideoMode* mode, bool* yuy2)
{
    if (!mt || mt->majortype != MEDIATYPE_Video || mt->formattype != FORMAT_VideoInfo ||
        !mt->pbFormat || mt->cbFormat < sizeof(VIDEOINFOHEADER))
    {
        return false;
    }
    bool isYuy2;
    if (mt->subtype == MEDIASUBTYPE_NV12)
    {
        isYuy2 = false;
    }
    else if (mt->subtype == MEDIASUBTYPE_YUY2)
    {
        isYuy2 = true;
    }
    else
    {
        return false;
    }
    const auto* vih = reinterpret_cast<const VIDEOINFOHEADER*>(mt->pbFormat);
    const int w = vih->bmiHeader.biWidth;
    const int h = std::abs(vih->bmiHeader.biHeight);
    int fps = 0;
    if (vih->AvgTimePerFrame > 0)
    {
        fps = static_cast<int>((UNITS + vih->AvgTimePerFrame / 2) / vih->AvgTimePerFrame);
    }
    for (const VideoMode& m : kModes)
    {
        if (m.width == w && m.height == h && (fps == 0 || fps == m.fps))
        {
            *mode = m;
            *yuy2 = isYuy2;
            return true;
        }
    }
    return false;
}

} // namespace

// ============================================================================
// Filtro
// ============================================================================

CUnknown* WINAPI UltraCamFilter::CreateInstance(LPUNKNOWN outer, HRESULT* hr)
{
    CUnknown* filter = new UltraCamFilter(outer, hr);
    if (!filter && hr)
    {
        *hr = E_OUTOFMEMORY;
    }
    return filter;
}

UltraCamFilter::UltraCamFilter(LPUNKNOWN outer, HRESULT* hr)
    : CSource(NAME("UltraCam"), outer, CLSID_UltraCam)
{
    // El constructor del pin lo añade a este filtro (CSource::AddPin).
    (void)new UltraCamPin(hr, this);
}

UltraCamPin* UltraCamFilter::pin()
{
    return m_iPins > 0 ? static_cast<UltraCamPin*>(m_paStreams[0]) : nullptr;
}

STDMETHODIMP UltraCamFilter::NonDelegatingQueryInterface(REFIID riid, void** ppv)
{
    if (riid == IID_IAMStreamConfig)
    {
        return GetInterface(static_cast<IAMStreamConfig*>(this), ppv);
    }
    return CSource::NonDelegatingQueryInterface(riid, ppv);
}

STDMETHODIMP UltraCamFilter::SetFormat(AM_MEDIA_TYPE* pmt)
{
    return pin() ? pin()->SetFormat(pmt) : E_UNEXPECTED;
}

STDMETHODIMP UltraCamFilter::GetFormat(AM_MEDIA_TYPE** ppmt)
{
    return pin() ? pin()->GetFormat(ppmt) : E_UNEXPECTED;
}

STDMETHODIMP UltraCamFilter::GetNumberOfCapabilities(int* count, int* size)
{
    return pin() ? pin()->GetNumberOfCapabilities(count, size) : E_UNEXPECTED;
}

STDMETHODIMP UltraCamFilter::GetStreamCaps(int index, AM_MEDIA_TYPE** ppmt, BYTE* caps)
{
    return pin() ? pin()->GetStreamCaps(index, ppmt, caps) : E_UNEXPECTED;
}

// ============================================================================
// Pin de salida
// ============================================================================

UltraCamPin::UltraCamPin(HRESULT* hr, UltraCamFilter* filter)
    : CSourceStream(NAME("UltraCam Stream"), hr, filter, L"Capture")
{
}

STDMETHODIMP UltraCamPin::NonDelegatingQueryInterface(REFIID riid, void** ppv)
{
    if (riid == IID_IKsPropertySet)
    {
        return GetInterface(static_cast<IKsPropertySet*>(this), ppv);
    }
    if (riid == IID_IAMStreamConfig)
    {
        return GetInterface(static_cast<IAMStreamConfig*>(this), ppv);
    }
    return CSourceStream::NonDelegatingQueryInterface(riid, ppv);
}

HRESULT UltraCamPin::GetMediaType(int position, CMediaType* pmt)
{
    CheckPointer(pmt, E_POINTER);
    CAutoLock lock(m_pFilter->pStateLock());
    if (position < 0)
    {
        return E_INVALIDARG;
    }
    if (m_hasRequested)
    {
        if (position > 0)
        {
            return VFW_S_NO_MORE_ITEMS;
        }
        *pmt = m_requested;
        return S_OK;
    }
    if (position >= kCapCount)
    {
        return VFW_S_NO_MORE_ITEMS;
    }
    return fillType(pmt, kModes[position % kModeCount], position >= kModeCount);
}

HRESULT UltraCamPin::CheckMediaType(const CMediaType* pmt)
{
    VideoMode mode;
    bool yuy2;
    if (!parseType(pmt, &mode, &yuy2))
    {
        return VFW_E_TYPE_NOT_ACCEPTED;
    }
    if (m_hasRequested)
    {
        VideoMode wanted;
        bool wantedYuy2;
        parseType(&m_requested, &wanted, &wantedYuy2);
        if (wanted.width != mode.width || wanted.height != mode.height ||
            wanted.fps != mode.fps || wantedYuy2 != yuy2)
        {
            return VFW_E_TYPE_NOT_ACCEPTED;
        }
    }
    return S_OK;
}

HRESULT UltraCamPin::DecideBufferSize(IMemAllocator* alloc, ALLOCATOR_PROPERTIES* props)
{
    CheckPointer(alloc, E_POINTER);
    CheckPointer(props, E_POINTER);
    CAutoLock lock(m_pFilter->pStateLock());

    const auto* vih = reinterpret_cast<const VIDEOINFOHEADER*>(m_mt.Format());
    if (!vih)
    {
        return E_UNEXPECTED;
    }
    if (props->cBuffers < 1)
    {
        props->cBuffers = 1;
    }
    if (props->cbAlign < 1)
    {
        props->cbAlign = 1;
    }
    props->cbBuffer = static_cast<long>(vih->bmiHeader.biSizeImage);

    ALLOCATOR_PROPERTIES actual;
    HRESULT hr = alloc->SetProperties(props, &actual);
    if (FAILED(hr))
    {
        return hr;
    }
    return actual.cbBuffer < props->cbBuffer ? E_FAIL : S_OK;
}

STDMETHODIMP UltraCamPin::Notify(IBaseFilter*, Quality)
{
    // Una webcam no baja su ritmo porque el programa vaya lento: se ignora.
    return NOERROR;
}

HRESULT UltraCamPin::OnThreadCreate()
{
    // Sin cerrojo del filtro: DirectShow lo retiene mientras espera a que este hilo
    // arranque, y tomarlo aquí bloquearía a los dos. m_mt no cambia mientras el pin
    // está conectado.
    if (!parseType(&m_mt, &m_mode, &m_yuy2))
    {
        return E_UNEXPECTED;
    }
    m_live.assign(nv12Size(m_mode.width, m_mode.height), 0);
    m_haveLive = false;
    m_slates[0].clear();
    m_slates[1].clear();

    QueryPerformanceFrequency(&m_qpcFreq);
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    m_qpcStart = now.QuadPart;
    m_frameIndex = 0;

    // Temporizador de alta resolución (Windows 10 1803+); si no existe, se sube
    // la resolución del reloj del sistema mientras la cámara está en uso.
    m_timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    m_timerHighRes = m_timer != nullptr;
    if (!m_timer)
    {
        m_timer = CreateWaitableTimerW(nullptr, FALSE, nullptr);
        timeBeginPeriod(1);
    }
    return NOERROR;
}

HRESULT UltraCamPin::OnThreadDestroy()
{
    if (m_timer)
    {
        CloseHandle(m_timer);
        m_timer = nullptr;
    }
    if (!m_timerHighRes)
    {
        timeEndPeriod(1);
    }
    return NOERROR;
}

void UltraCamPin::waitForNextFrame()
{
    const LONGLONG period = m_qpcFreq.QuadPart / m_mode.fps;
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    const LONGLONG deadline = m_qpcStart + m_frameIndex * period;
    if (now.QuadPart - deadline > 2 * period)
    {
        // Muy atrasados (el programa dejó de pedir cuadros un rato): se salta al
        // presente en vez de entregar una ráfaga de cuadros viejos.
        m_frameIndex = (now.QuadPart - m_qpcStart) / period;
        return;
    }
    const LONGLONG wait = deadline - now.QuadPart;
    if (wait <= 0)
    {
        return;
    }
    const LONGLONG wait100ns = wait * 10000000 / m_qpcFreq.QuadPart;
    LARGE_INTEGER due;
    due.QuadPart = -wait100ns;
    if (m_timer && SetWaitableTimer(m_timer, &due, 0, nullptr, nullptr, FALSE))
    {
        WaitForSingleObject(m_timer, 1000);
    }
    else
    {
        Sleep(static_cast<DWORD>(wait100ns / 10000));
    }
}

const std::vector<uint8_t>& UltraCamPin::slate(SlateKind kind)
{
    std::vector<uint8_t>& cached = m_slates[kind == SlateKind::NoSignal ? 0 : 1];
    if (cached.empty())
    {
        cached = renderSlate(kind, m_mode.width, m_mode.height);
    }
    return cached;
}

HRESULT UltraCamPin::FillBuffer(IMediaSample* sample)
{
    CheckPointer(sample, E_POINTER);
    waitForNextFrame();

    bool fresh = false;
    const SourceState state = m_source.poll(fresh);
    if (fresh)
    {
        scaleNV12(m_source.frame(), m_source.width(), m_source.height(),
                  m_live.data(), m_mode.width, m_mode.height);
        m_haveLive = true;
    }
    const uint8_t* nv12;
    if (state == SourceState::Live && m_haveLive)
    {
        nv12 = m_live.data();
    }
    else
    {
        nv12 = slate(state == SourceState::NoSignal ? SlateKind::NoSignal : SlateKind::AppClosed).data();
    }

    BYTE* data = nullptr;
    const std::size_t need = frameBytes(m_mode, m_yuy2);
    if (FAILED(sample->GetPointer(&data)) || !data || static_cast<std::size_t>(sample->GetSize()) < need)
    {
        return E_UNEXPECTED;
    }
    if (m_yuy2)
    {
        nv12ToYUY2(nv12, m_mode.width, m_mode.height, data);
    }
    else
    {
        std::memcpy(data, nv12, need);
    }
    sample->SetActualDataLength(static_cast<long>(need));

    REFERENCE_TIME start = m_frameIndex * UNITS / m_mode.fps;
    REFERENCE_TIME end = (m_frameIndex + 1) * UNITS / m_mode.fps;
    sample->SetTime(&start, &end);
    sample->SetSyncPoint(TRUE);
    sample->SetDiscontinuity(m_frameIndex == 0);
    ++m_frameIndex;
    return NOERROR;
}

// ---- IAMStreamConfig ----

STDMETHODIMP UltraCamPin::SetFormat(AM_MEDIA_TYPE* pmt)
{
    CAutoLock lock(m_pFilter->pStateLock());
    if (!pmt)
    {
        m_hasRequested = false;   // NULL vuelve a ofrecer todos los modos
        return S_OK;
    }
    VideoMode mode;
    bool yuy2;
    if (!parseType(pmt, &mode, &yuy2))
    {
        return VFW_E_INVALIDMEDIATYPE;
    }
    if (m_pFilter->IsActive())
    {
        return VFW_E_NOT_STOPPED;
    }
    CMediaType canonical;
    HRESULT hr = fillType(&canonical, mode, yuy2);
    if (FAILED(hr))
    {
        return hr;
    }
    m_requested = canonical;
    m_hasRequested = true;

    if (IsConnected() && !(m_mt == canonical))
    {
        IFilterGraph* graph = m_pFilter->GetFilterGraph();
        if (graph)
        {
            return graph->Reconnect(this);
        }
    }
    return S_OK;
}

STDMETHODIMP UltraCamPin::GetFormat(AM_MEDIA_TYPE** ppmt)
{
    CheckPointer(ppmt, E_POINTER);
    CAutoLock lock(m_pFilter->pStateLock());
    CMediaType mt;
    if (IsConnected())
    {
        mt = m_mt;
    }
    else if (m_hasRequested)
    {
        mt = m_requested;
    }
    else
    {
        HRESULT hr = fillType(&mt, kModes[0], false);
        if (FAILED(hr))
        {
            return hr;
        }
    }
    *ppmt = CreateMediaType(&mt);
    return *ppmt ? S_OK : E_OUTOFMEMORY;
}

STDMETHODIMP UltraCamPin::GetNumberOfCapabilities(int* count, int* size)
{
    CheckPointer(count, E_POINTER);
    CheckPointer(size, E_POINTER);
    *count = kCapCount;
    *size = sizeof(VIDEO_STREAM_CONFIG_CAPS);
    return S_OK;
}

STDMETHODIMP UltraCamPin::GetStreamCaps(int index, AM_MEDIA_TYPE** ppmt, BYTE* caps)
{
    CheckPointer(ppmt, E_POINTER);
    CheckPointer(caps, E_POINTER);
    if (index < 0 || index >= kCapCount)
    {
        return S_FALSE;
    }
    const VideoMode& m = kModes[index % kModeCount];
    const bool yuy2 = index >= kModeCount;
    CMediaType mt;
    HRESULT hr = fillType(&mt, m, yuy2);
    if (FAILED(hr))
    {
        return hr;
    }
    *ppmt = CreateMediaType(&mt);
    if (!*ppmt)
    {
        return E_OUTOFMEMORY;
    }

    auto* scc = reinterpret_cast<VIDEO_STREAM_CONFIG_CAPS*>(caps);
    ZeroMemory(scc, sizeof(VIDEO_STREAM_CONFIG_CAPS));
    const SIZE size{m.width, m.height};
    const LONG bits = static_cast<LONG>(frameBytes(m, yuy2) * 8 * m.fps);
    scc->guid = FORMAT_VideoInfo;
    scc->VideoStandard = AnalogVideo_None;
    scc->InputSize = size;
    scc->MinCroppingSize = size;
    scc->MaxCroppingSize = size;
    scc->CropGranularityX = 1;
    scc->CropGranularityY = 1;
    scc->CropAlignX = 1;
    scc->CropAlignY = 1;
    scc->MinOutputSize = size;
    scc->MaxOutputSize = size;
    scc->OutputGranularityX = 1;
    scc->OutputGranularityY = 1;
    scc->MinFrameInterval = frameInterval(m);
    scc->MaxFrameInterval = frameIntervalMax(m);
    scc->MinBitsPerSecond = bits;
    scc->MaxBitsPerSecond = bits;
    return S_OK;
}

// ---- IKsPropertySet ----

STDMETHODIMP UltraCamPin::Set(REFGUID, DWORD, LPVOID, DWORD, LPVOID, DWORD)
{
    return E_NOTIMPL;
}

STDMETHODIMP UltraCamPin::Get(REFGUID set, DWORD id, LPVOID, DWORD, LPVOID data, DWORD dataSize, DWORD* returned)
{
    if (set != AMPROPSETID_Pin)
    {
        return E_PROP_SET_UNSUPPORTED;
    }
    if (id != AMPROPERTY_PIN_CATEGORY)
    {
        return E_PROP_ID_UNSUPPORTED;
    }
    if (!data && !returned)
    {
        return E_POINTER;
    }
    if (returned)
    {
        *returned = sizeof(GUID);
    }
    if (data)
    {
        if (dataSize < sizeof(GUID))
        {
            return E_UNEXPECTED;
        }
        *static_cast<GUID*>(data) = PIN_CATEGORY_CAPTURE;
    }
    return S_OK;
}

STDMETHODIMP UltraCamPin::QuerySupported(REFGUID set, DWORD id, DWORD* support)
{
    if (set != AMPROPSETID_Pin)
    {
        return E_PROP_SET_UNSUPPORTED;
    }
    if (id != AMPROPERTY_PIN_CATEGORY)
    {
        return E_PROP_ID_UNSUPPORTED;
    }
    if (support)
    {
        *support = KSPROPERTY_SUPPORT_GET;
    }
    return S_OK;
}

} // namespace ultracam
