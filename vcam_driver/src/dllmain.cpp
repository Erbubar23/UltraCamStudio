// Punto de entrada de la DLL: tabla COM y registro.
//
// Dos formas de registrar la cámara:
//   - Por usuario, sin permisos de administrador: lo hace la app al arrancar
//     (infrastructure/video/vcam_driver.py) escribiendo en HKCU.
//   - Para todo el equipo: regsvr32 ultracam-vcam64.dll (lo usa el instalador).

#include <streams.h>
#include <olectl.h>
#include <initguid.h>

#include "guids.h"
#include "UltraCamFilter.h"

namespace {

const wchar_t kFriendlyName[] = L"UltraCam";

const AMOVIESETUP_MEDIATYPE kPinTypes[] = {
    {&MEDIATYPE_Video, &MEDIASUBTYPE_NV12},
    {&MEDIATYPE_Video, &MEDIASUBTYPE_YUY2},
};

const AMOVIESETUP_PIN kPins[] = {
    {
        const_cast<LPWSTR>(L"Capture"),
        FALSE,          // se renderiza
        TRUE,           // es de salida
        FALSE,          // puede no existir
        FALSE,          // puede haber varios
        &CLSID_NULL,
        nullptr,
        static_cast<UINT>(sizeof(kPinTypes) / sizeof(kPinTypes[0])),
        kPinTypes,
    },
};

const REGFILTER2 kFilterReg = {1, MERIT_DO_NOT_USE, 1, kPins};

HRESULT registerInCategory(bool add)
{
    HRESULT hr = CoInitialize(nullptr);
    if (FAILED(hr))
    {
        return hr;
    }
    IFilterMapper2* mapper = nullptr;
    hr = CoCreateInstance(CLSID_FilterMapper2, nullptr, CLSCTX_INPROC_SERVER, IID_IFilterMapper2,
                          reinterpret_cast<void**>(&mapper));
    if (SUCCEEDED(hr))
    {
        mapper->UnregisterFilter(&CLSID_VideoInputDeviceCategory, kFriendlyName, CLSID_UltraCam);
        if (add)
        {
            hr = mapper->RegisterFilter(CLSID_UltraCam, kFriendlyName, nullptr,
                                        &CLSID_VideoInputDeviceCategory, kFriendlyName, &kFilterReg);
        }
        mapper->Release();
    }
    CoFreeUnusedLibraries();
    CoUninitialize();
    return hr;
}

} // namespace

CFactoryTemplate g_Templates[] = {
    {kFriendlyName, &CLSID_UltraCam, ultracam::UltraCamFilter::CreateInstance, nullptr, nullptr},
};
int g_cTemplates = sizeof(g_Templates) / sizeof(g_Templates[0]);

STDAPI DllRegisterServer()
{
    HRESULT hr = AMovieDllRegisterServer2(TRUE);
    return FAILED(hr) ? hr : registerInCategory(true);
}

STDAPI DllUnregisterServer()
{
    registerInCategory(false);
    return AMovieDllRegisterServer2(FALSE);
}

extern "C" BOOL WINAPI DllEntryPoint(HINSTANCE, ULONG, LPVOID);

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID reserved)
{
    return DllEntryPoint(static_cast<HINSTANCE>(module), reason, reserved);
}
