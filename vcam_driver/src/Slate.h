#pragma once
// Carteles que muestra la cámara cuando no hay imagen de la app.

#include <cstdint>
#include <vector>

namespace ultracam {

enum class SlateKind
{
    NoSignal,   // app abierta, sin cámara elegida o la fuente se cayó
    AppClosed,  // UltraCam Studio no está abierto
};

// Dibuja el cartel en NV12 al tamaño pedido (logo, nombre y un mensaje corto).
// El idioma sigue al de Windows: español si el sistema está en español, si no inglés.
std::vector<uint8_t> renderSlate(SlateKind kind, int width, int height);

} // namespace ultracam
