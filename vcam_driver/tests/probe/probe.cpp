// vcam_probe: abre una cámara por DirectShow como lo haría Zoom u OBS y resume lo que llega.
//
//   vcam_probe.exe "UltraCam Test" 3
//   -> found=1 frames=90 width=1920 height=1080 left=235.0 right=16.0
//
// Se compila en 32 y 64 bits para probar las dos DLL del driver y su registro en las dos
// vistas del registro de Windows (los programas de 32 bits leen otra).

#include <windows.h>
#include <dshow.h>

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <string>

// qedit.h (ISampleGrabber) ya no viene en el SDK de Windows, pero el componente sigue
// en el sistema: se declaran aquí sus interfaces.
static const CLSID kClsidSampleGrabber = {0xC1F400A0, 0x3F08, 0x11d3, {0x9F, 0x0B, 0x00, 0x60, 0x08, 0x03, 0x9E, 0x37}};
static const CLSID kClsidNullRenderer = {0xC1F400A4, 0x3F08, 0x11d3, {0x9F, 0x0B, 0x00, 0x60, 0x08, 0x03, 0x9E, 0x37}};

MIDL_INTERFACE("0579154A-2B53-4994-B0D0-E773148EFF85")
ISampleGrabberCB : public IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE SampleCB(double time, IMediaSample* sample) = 0;
    virtual HRESULT STDMETHODCALLTYPE BufferCB(double time, BYTE* buffer, long length) = 0;
};

MIDL_INTERFACE("6B652FFF-11FE-4fce-92AD-0266B5D7C78F")
ISampleGrabber : public IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE SetOneShot(BOOL oneShot) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetMediaType(const AM_MEDIA_TYPE* type) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetConnectedMediaType(AM_MEDIA_TYPE* type) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetBufferSamples(BOOL buffer) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentBuffer(long* size, long* buffer) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentSample(IMediaSample** sample) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetCallback(ISampleGrabberCB* callback, long whichMethod) = 0;
};

// Cuenta cuadros y mide el brillo (plano Y del NV12) de la mitad izquierda y derecha
// del último cuadro: así la prueba distingue su patrón de un cartel.
class Counter : public ISampleGrabberCB
{
public:
    std::atomic<int> frames{0};
    int width = 0, height = 0;
    double left = 0, right = 0;

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override
    {
        if (riid == IID_IUnknown || riid == __uuidof(ISampleGrabberCB))
        {
            *ppv = static_cast<ISampleGrabberCB*>(this);
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }
    STDMETHODIMP_(ULONG) Release() override { return 1; }
    STDMETHODIMP SampleCB(double, IMediaSample*) override { return S_OK; }
    STDMETHODIMP BufferCB(double, BYTE* buffer, long length) override
    {
        ++frames;
        if (width > 0 && height > 0 && length >= width * height)
        {
            double l = 0, r = 0;
            int n = 0;
            for (int y = 0; y < height; y += 8)
            {
                const BYTE* row = buffer + static_cast<size_t>(y) * width;
                l += row[width / 4];
                r += row[width * 3 / 4];
                ++n;
            }
            left = l / n;
            right = r / n;
        }
        return S_OK;
    }
};

static IBaseFilter* findCamera(const std::wstring& name)
{
    ICreateDevEnum* devEnum = nullptr;
    IEnumMoniker* monikers = nullptr;
    IBaseFilter* filter = nullptr;
    if (FAILED(CoCreateInstance(CLSID_SystemDeviceEnum, nullptr, CLSCTX_INPROC_SERVER, IID_ICreateDevEnum,
                                reinterpret_cast<void**>(&devEnum))))
        return nullptr;
    if (devEnum->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &monikers, 0) == S_OK)
    {
        IMoniker* moniker = nullptr;
        while (!filter && monikers->Next(1, &moniker, nullptr) == S_OK)
        {
            IPropertyBag* bag = nullptr;
            if (SUCCEEDED(moniker->BindToStorage(nullptr, nullptr, IID_IPropertyBag, reinterpret_cast<void**>(&bag))))
            {
                VARIANT v;
                VariantInit(&v);
                if (SUCCEEDED(bag->Read(L"FriendlyName", &v, nullptr)) && name == v.bstrVal)
                    moniker->BindToObject(nullptr, nullptr, IID_IBaseFilter, reinterpret_cast<void**>(&filter));
                VariantClear(&v);
                bag->Release();
            }
            moniker->Release();
        }
        monikers->Release();
    }
    devEnum->Release();
    return filter;
}

int wmain(int argc, wchar_t** argv)
{
    const std::wstring name = argc > 1 ? argv[1] : L"UltraCam";
    const double seconds = argc > 2 ? _wtof(argv[2]) : 3.0;
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);

    IBaseFilter* camera = findCamera(name);
    if (!camera)
    {
        std::printf("found=0\n");
        return 2;
    }
    IGraphBuilder* graph = nullptr;
    ICaptureGraphBuilder2* builder = nullptr;
    IBaseFilter* grabberFilter = nullptr;
    IBaseFilter* sink = nullptr;
    ISampleGrabber* grabber = nullptr;
    IMediaControl* control = nullptr;
    Counter counter;
    HRESULT hr = CoCreateInstance(CLSID_FilterGraph, nullptr, CLSCTX_INPROC_SERVER, IID_IGraphBuilder,
                                  reinterpret_cast<void**>(&graph));
    if (SUCCEEDED(hr))
        hr = CoCreateInstance(CLSID_CaptureGraphBuilder2, nullptr, CLSCTX_INPROC_SERVER, IID_ICaptureGraphBuilder2,
                              reinterpret_cast<void**>(&builder));
    if (SUCCEEDED(hr))
        hr = CoCreateInstance(kClsidSampleGrabber, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter,
                              reinterpret_cast<void**>(&grabberFilter));
    if (SUCCEEDED(hr))
        hr = CoCreateInstance(kClsidNullRenderer, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter,
                              reinterpret_cast<void**>(&sink));
    if (SUCCEEDED(hr))
        hr = grabberFilter->QueryInterface(__uuidof(ISampleGrabber), reinterpret_cast<void**>(&grabber));
    if (SUCCEEDED(hr))
    {
        AM_MEDIA_TYPE mt = {};
        mt.majortype = MEDIATYPE_Video;
        mt.subtype = MEDIASUBTYPE_NV12;   // pide NV12: el plano Y va primero
        grabber->SetMediaType(&mt);
        builder->SetFiltergraph(graph);
        graph->AddFilter(camera, L"Camera");
        graph->AddFilter(grabberFilter, L"Grabber");
        graph->AddFilter(sink, L"Sink");
        hr = builder->RenderStream(&PIN_CATEGORY_CAPTURE, &MEDIATYPE_Video, camera, grabberFilter, sink);
    }
    if (SUCCEEDED(hr))
    {
        AM_MEDIA_TYPE connected = {};
        if (SUCCEEDED(grabber->GetConnectedMediaType(&connected)) && connected.pbFormat)
        {
            auto* vih = reinterpret_cast<VIDEOINFOHEADER*>(connected.pbFormat);
            counter.width = vih->bmiHeader.biWidth;
            counter.height = std::abs(vih->bmiHeader.biHeight);
            CoTaskMemFree(connected.pbFormat);
        }
        grabber->SetCallback(&counter, 1);
        hr = graph->QueryInterface(IID_IMediaControl, reinterpret_cast<void**>(&control));
    }
    if (SUCCEEDED(hr))
        hr = control->Run();
    if (SUCCEEDED(hr))
    {
        Sleep(static_cast<DWORD>(seconds * 1000));
        control->Stop();
    }
    std::printf("found=1 hr=0x%08lx frames=%d width=%d height=%d left=%.1f right=%.1f\n",
                static_cast<unsigned long>(hr), counter.frames.load(), counter.width, counter.height,
                counter.left, counter.right);
    if (control) control->Release();
    if (grabber) grabber->Release();
    if (sink) sink->Release();
    if (grabberFilter) grabberFilter->Release();
    if (builder) builder->Release();
    if (graph) graph->Release();
    camera->Release();
    CoUninitialize();
    return SUCCEEDED(hr) ? 0 : 1;
}
