"""Fetch today's weather forecast from Open-Meteo (no API key required)."""
import asyncio
import httpx
from config import USER_LAT, USER_LNG, USER_TIMEZONE
async def get_today_weather() -> dict:
    """Return a weather summary dict for today.
    Keys: condition, temp_max_c, temp_min_c, precipitation_mm,
          wind_speed_kmh, uv_index, summary_line
    Returns empty dict on failure.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={USER_LAT}&longitude={USER_LNG}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,windspeed_10m_max,uv_index_max"
        f"&timezone={USER_TIMEZONE}&forecast_days=1"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        daily = data.get("daily", {})
        code  = (daily.get("weathercode") or [0])[0]
        t_max = (daily.get("temperature_2m_max") or [None])[0]
        t_min = (daily.get("temperature_2m_min") or [None])[0]
        rain  = (daily.get("precipitation_sum") or [0.0])[0]
        wind  = (daily.get("windspeed_10m_max") or [None])[0]
        uv    = (daily.get("uv_index_max") or [None])[0]
        condition = _wmo_to_label(code)
        summary = f"{condition}, {t_min}–{t_max}°C"
        if rain and rain > 1:
            summary += f", {rain:.0f}mm rain"
        if uv and uv >= 6:
            summary += f", UV {uv:.0f} (high — wear sunscreen)"
        return {
            "condition": condition, "temp_max_c": t_max, "temp_min_c": t_min,
            "precipitation_mm": rain, "wind_speed_kmh": wind,
            "uv_index": uv, "summary_line": summary,
        }
    except Exception as exc:
        print(f"[weather_ops] fetch failed: {exc}")
        return {}
def _wmo_to_label(code: int) -> str:
    if code == 0:   return "Clear sky"
    if code <= 3:   return "Partly cloudy"
    if code <= 9:   return "Foggy"
    if code <= 19:  return "Light drizzle"
    if code <= 29:  return "Rain"
    if code <= 39:  return "Snow"
    if code <= 49:  return "Fog"
    if code <= 59:  return "Drizzle"
    if code <= 69:  return "Rain"
    if code <= 79:  return "Snow"
    if code <= 84:  return "Rain showers"
    if code <= 94:  return "Thunderstorm"
    return "Severe weather"
