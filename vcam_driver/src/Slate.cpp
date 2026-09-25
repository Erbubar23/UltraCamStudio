#include "Slate.h"

#include <windows.h>
#include <cstring>

#include "Convert.h"
#include "resource.h"

namespace ultracam {

namespace {

// Paleta de la app (presentation/theme.py).
constexpr COLORREF kBackground = RGB(0x11, 0x11, 0x13);
constexpr COLORREF kText = RGB(0xEC, 0xEA, 0xE4);
constexpr COLORREF kAccent = RGB(0xE9, 0xB2, 0x4A);
constexpr COLORREF kMuted = RGB(0xA0, 0x9D, 0x95);

struct SlateText
{
    const wchar_t* status;
    const wchar_t* hint;
};

SlateText textFor(SlateKind kind)
{
    const bool spanish = PRIMARYLANGID(GetUserDefaultUILanguage()) == LANG_SPANISH;
    if (kind == SlateKind::NoSignal)
    {
        return spanish ? SlateText{L"Sin señal", L"Elige una cámara en UltraCam Studio"}
                       : SlateText{L"No signal", L"Choose a camera in UltraCam Studio"};
    }
    return spanish ? SlateText{L"UltraCam Studio está cerrado", L"Ábrelo para mostrar tu cámara aquí"}
                   : SlateText{L"UltraCam Studio is closed", L"Open it to show your camera here"};
}

HMODULE thisModule()
{
    HMODULE module = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       reinterpret_cast<LPCWSTR>(&thisModule), &module);
    return module;
}

void drawLine(HDC dc, const wchar_t* text, int height, int weight, COLORREF color, RECT box)
{
    HFONT font = CreateFontW(-height, 0, 0, 0, weight, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                             OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY,
                             DEFAULT_PITCH | FF_SWISS, L"Segoe UI");
    HGDIOBJ old = SelectObject(dc, font);
    SetTextColor(dc, color);
    DrawTextW(dc, text, -1, &box, DT_CENTER | DT_SINGLELINE | DT_NOPREFIX | DT_VCENTER);
    SelectObject(dc, old);
    DeleteObject(font);
}

} // namespace

std::vector<uint8_t> renderSlate(SlateKind kind, int width, int height)
{
    std::vector<uint8_t> nv12(nv12Size(width, height));

    BITMAPINFO bmi{};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = width;
    bmi.bmiHeader.biHeight = -height;   // de arriba abajo
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;

    void* pixels = nullptr;
    HDC dc = CreateCompatibleDC(nullptr);
    HBITMAP bitmap = dc ? CreateDIBSection(dc, &bmi, DIB_RGB_COLORS, &pixels, nullptr, 0) : nullptr;
    if (!bitmap || !pixels)
    {
        // Sin GDI (muy raro): al menos un fondo gris oscuro, nunca negro puro.
        std::memset(nv12.data(), 32, static_cast<std::size_t>(width) * height);
        std::memset(nv12.data() + static_cast<std::size_t>(width) * height, 128,
                    static_cast<std::size_t>(width) * height / 2);
        if (dc) DeleteDC(dc);
        return nv12;
    }
    HGDIOBJ oldBitmap = SelectObject(dc, bitmap);

    RECT all{0, 0, width, height};
    HBRUSH bg = CreateSolidBrush(kBackground);
    FillRect(dc, &all, bg);
    DeleteObject(bg);
    SetBkMode(dc, TRANSPARENT);

    // Bloque centrado: logo, nombre, estado y una pista de qué hacer. Cada línea
    // ocupa 1,5 veces el tamaño de su letra para que no se corten «g», «p» o tildes.
    const int icon = height * 16 / 100;
    const int title = height * 7 / 100;
    const int status = height * 45 / 1000;
    const int hint = height * 3 / 100;
    const auto box = [](int size) { return size * 3 / 2; };
    const int gap = height * 2 / 100;
    const int block = icon + gap + box(title) + box(status) + box(hint);
    int y = (height - block) / 2;

    HICON logo = static_cast<HICON>(LoadImageW(thisModule(), MAKEINTRESOURCEW(IDI_ULTRACAM), IMAGE_ICON,
                                               icon, icon, LR_DEFAULTCOLOR));
    if (logo)
    {
        DrawIconEx(dc, (width - icon) / 2, y, logo, icon, icon, 0, nullptr, DI_NORMAL);
        DestroyIcon(logo);
    }
    y += icon + gap;

    const SlateText text = textFor(kind);
    drawLine(dc, L"UltraCam", title, FW_BOLD, kText, RECT{0, y, width, y + box(title)});
    y += box(title);
    drawLine(dc, text.status, status, FW_SEMIBOLD, kAccent, RECT{0, y, width, y + box(status)});
    y += box(status);
    drawLine(dc, text.hint, hint, FW_NORMAL, kMuted, RECT{0, y, width, y + box(hint)});

    GdiFlush();
    bgraToNV12(static_cast<const uint8_t*>(pixels), width, height, width * 4, nv12.data());

    SelectObject(dc, oldBitmap);
    DeleteObject(bitmap);
    DeleteDC(dc);
    return nv12;
}

} // namespace ultracam
