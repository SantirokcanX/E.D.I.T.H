"""Casa inteligente con Home Assistant (Fase 13, parte IoT).

Se activa al poner en Ajustes la dirección de Home Assistant (HA_URL) y un token de larga duración
(HA_TOKEN, se guarda cifrado). EDITH puede ver y manejar luces, enchufes, ventiladores, clima,
reproductores y escenas. Por seguridad NO toca cerraduras, alarmas, puertas de garaje ni persianas:
esas las controlas tú desde Home Assistant.
"""

from typing import Any, Dict, List, Optional

import httpx

from ..config import Config

CONTROLLABLE = {"light", "switch", "fan", "climate", "media_player", "scene", "script", "input_boolean", "humidifier"}
VISIBLE = CONTROLLABLE | {"sensor", "binary_sensor", "weather", "lock", "cover", "alarm_control_panel"}
FORBIDDEN = {"lock", "cover", "alarm_control_panel", "camera", "siren", "valve"}
ACTIONS = {
    "encender": "turn_on", "turn_on": "turn_on", "on": "turn_on",
    "apagar": "turn_off", "turn_off": "turn_off", "off": "turn_off",
    "alternar": "toggle", "toggle": "toggle",
    "temperatura": "set_temperature", "set_temperature": "set_temperature",
    "brillo": "brightness", "brightness": "brightness",
    "activar": "turn_on",
}


def enabled() -> bool:
    return bool(Config.HA_URL and Config.HA_TOKEN)


def _client() -> httpx.Client:
    return httpx.Client(base_url=Config.HA_URL.rstrip("/"), timeout=10.0,
                        headers={"Authorization": f"Bearer {Config.HA_TOKEN}", "Content-Type": "application/json"})


def _error(e: Exception) -> Dict[str, str]:
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 401:
        return {"error": "Home Assistant rechazó el token: revísalo en Ajustes › Casa y cuentas."}
    return {"error": f"No pude hablar con Home Assistant ({type(e).__name__}). ¿Está encendido y en la misma red?"}


def ha_list_devices(domain: str = "", search: str = "") -> Dict[str, Any]:
    if not enabled():
        return {"error": "Home Assistant no está configurado (Ajustes › Casa y cuentas)."}
    try:
        with _client() as c:
            r = c.get("/api/states")
            r.raise_for_status()
            states = r.json()
    except Exception as e:
        return _error(e)
    want = (domain or "").strip().lower()
    q = (search or "").strip().lower()
    devices: List[Dict[str, Any]] = []
    for s in states:
        eid = s.get("entity_id", "")
        dom = eid.split(".")[0]
        name = (s.get("attributes") or {}).get("friendly_name") or eid
        if dom not in VISIBLE or (want and dom != want) or (q and q not in name.lower() and q not in eid):
            continue
        attrs = s.get("attributes") or {}
        extra = {k: attrs[k] for k in ("brightness", "temperature", "current_temperature", "unit_of_measurement")
                 if k in attrs}
        devices.append({"entity_id": eid, "name": name, "state": s.get("state"),
                        "controllable": dom in CONTROLLABLE, **extra})
        if len(devices) >= 60:
            break
    return {"devices": devices, "count": len(devices)}


def ha_control(entity_id: str, action: str, value: Optional[float] = None) -> Dict[str, Any]:
    if not enabled():
        return {"error": "Home Assistant no está configurado (Ajustes › Casa y cuentas)."}
    eid = (entity_id or "").strip().lower()
    if "." not in eid:
        return {"error": "Indica el entity_id completo (ej. light.sala). Usa ha_list_devices para verlos."}
    dom = eid.split(".")[0]
    if dom in FORBIDDEN:
        return {"error": "Por seguridad no manejo cerraduras, alarmas, puertas ni persianas: hazlo desde Home Assistant."}
    if dom not in CONTROLLABLE:
        return {"error": f"«{eid}» no es un dispositivo que yo pueda manejar (solo luces, enchufes, clima, escenas...)."}
    act = ACTIONS.get((action or "").strip().lower())
    if not act:
        return {"error": "Acción no válida: usa encender, apagar, alternar, brillo o temperatura."}
    data: Dict[str, Any] = {"entity_id": eid}
    service = act
    if act == "brightness":
        if dom != "light" or value is None:
            return {"error": "El brillo solo se cambia en luces y necesita un valor de 0 a 100."}
        service, data["brightness_pct"] = "turn_on", max(0, min(100, int(value)))
    elif act == "set_temperature":
        if dom != "climate" or value is None:
            return {"error": "La temperatura solo se cambia en un clima y necesita un valor en grados."}
        data["temperature"] = float(value)
    elif dom == "scene" and act != "turn_on":
        return {"error": "Las escenas solo se activan."}
    try:
        with _client() as c:
            r = c.post(f"/api/services/{dom}/{service}", json=data)
            r.raise_for_status()
    except Exception as e:
        return _error(e)
    return {"status": "hecho", "entity_id": eid, "service": f"{dom}.{service}",
            **({k: v for k, v in data.items() if k != "entity_id"})}


HOME_HANDLERS = {"ha_list_devices": ha_list_devices, "ha_control": ha_control}
HOME_TOOLS_METADATA = [
    {"name": "ha_list_devices",
     "description": "Lista los dispositivos de la casa en Home Assistant (luces, enchufes, clima, sensores) con su estado.",
     "parameters": {"type": "object", "properties": {
         "domain": {"type": "string", "description": "Opcional: light, switch, climate, sensor..."},
         "search": {"type": "string", "description": "Opcional: parte del nombre (ej. 'sala')."}}}},
    {"name": "ha_control",
     "description": "Enciende, apaga o ajusta un dispositivo de la casa (luces, enchufes, ventiladores, clima, escenas).",
     "parameters": {"type": "object", "properties": {
         "entity_id": {"type": "string", "description": "Ej. light.sala (de ha_list_devices)."},
         "action": {"type": "string", "enum": ["encender", "apagar", "alternar", "brillo", "temperatura"]},
         "value": {"type": "number", "description": "Brillo 0-100 o temperatura en grados."}},
         "required": ["entity_id", "action"]}},
]
