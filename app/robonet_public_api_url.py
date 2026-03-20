"""
URL canónica del API REST Robonet (producción POC).

Mantener alineada con:
- `robonet-mobile-app/lib/config/api_config.dart` → `kRobonetApiBaseUrlDefault`
- `robonet-firmware/esp32-somalink-sim/include/robonet_public_api_url.h`

En despliegues propios, cambiar los tres (o usar variables de entorno en cada capa).
"""

ROBONET_API_BASE_URL: str = "https://robonet-backend.onrender.com"
