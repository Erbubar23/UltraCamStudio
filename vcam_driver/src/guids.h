#pragma once
// Identificador COM propio de la cámara UltraCam (distinto del de OBS, para que
// ambas puedan convivir). Debe coincidir con CLSID en infrastructure/video/vcam_driver.py.

#include <guiddef.h>

// {E7D1A5EA-54D9-4644-9E4D-1FA4F637870A}
DEFINE_GUID(CLSID_UltraCam,
            0xe7d1a5ea, 0x54d9, 0x4644, 0x9e, 0x4d, 0x1f, 0xa4, 0xf6, 0x37, 0x87, 0x0a);
