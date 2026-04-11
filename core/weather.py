"""
WeatherManager — fetches weather from BOM JSON observations + Open-Meteo forecast.

Provider options (set in Settings):
  - BOM (Australia)     : Current temp/conditions from BOM station JSON feed (direct,
                          no API key). Nearest station to Kelmscott is Jandakot (94609).
                          Forecast from Open-Meteo Global as BOM has no public forecast API.
  - Open-Meteo (Global) : All data from Open-Meteo — works worldwide, no API key.
  - Custom URL          : User-supplied Open-Meteo-compatible endpoint.

BOM station JSON feeds are published by the Bureau of Meteorology at:
  http://www.bom.gov.au/fwo/IDW60901/IDW60901.<station_id>.json
These are free for personal/non-commercial use. Data courtesy of the Australian
Bureau of Meteorology (http://www.bom.gov.au).
"""

import requests
import traceback
from datetime import datetime
from core.settings_store import settings

# ---------------------------------------------------------------------------
# BOM observation stations — nearest to Perth/Kelmscott area
# IDW = WA prefix, 60901 = observations product
# ---------------------------------------------------------------------------
BOM_STATIONS = {
    "Jandakot (nearest Kelmscott)": "94609",
    "Perth Airport":                 "94610",
    "Perth (Swanbourne)":            "94614",
    "Perth (Gooseberry Hill)":       "94615",
    "Perth (Mt Lawley)":             "94608",
}
BOM_OBS_URL = "http://www.bom.gov.au/fwo/IDW60901/IDW60901.{station_id}.json"

# Open-Meteo forecast endpoint — used for hourly forecast regardless of provider
OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------
PROVIDERS = {
    "BOM (Australia)": {
        "description": "Bureau of Meteorology — direct station observations, best for Australia",
    },
    "Open-Meteo (Global)": {
        "description": "Free global weather — no API key required, works worldwide",
    },
    "Custom URL": {
        "description": "Enter your own Open-Meteo-compatible endpoint below",
    },
}

PROVIDER_NAMES = list(PROVIDERS.keys())

# ---------------------------------------------------------------------------
# Condition text mapping from BOM weather description strings
# ---------------------------------------------------------------------------
BOM_CONDITION_MAP = {
    "clear": "Clear", "sunny": "Clear", "fine": "Clear",
    "cloud": "Cloudy", "overcast": "Cloudy", "grey": "Cloudy",
    "fog": "Foggy", "mist": "Foggy", "haze": "Foggy",
    "shower": "Rain", "rain": "Rain", "drizzle": "Rain", "precip": "Rain",
    "storm": "Storm", "thunder": "Storm", "lightning": "Storm",
    "snow": "Snow", "sleet": "Snow", "hail": "Snow",
    "wind": "Windy", "gust": "Windy",
    "smoke": "Smoky", "dust": "Dusty",
}


def _bom_desc_to_condition(desc: str) -> str:
    """Map a BOM weather description string to a simple condition word."""
    if not desc:
        return "Unknown"
    desc_lower = desc.lower()
    for keyword, condition in BOM_CONDITION_MAP.items():
        if keyword in desc_lower:
            return condition
    return desc.strip() or "Unknown"


def _desc_to_code(desc: str) -> int:
    """Map a BOM condition description to a WMO-style code for icon selection."""
    cond = _bom_desc_to_condition(desc)
    mapping = {
        "Clear": 0, "Cloudy": 2, "Foggy": 45,
        "Rain": 61, "Storm": 95, "Snow": 71,
        "Windy": 2, "Smoky": 45, "Dusty": 45,
    }
    return mapping.get(cond, 0)


class WeatherManager:
    """Fetches current observations from BOM and hourly forecast from Open-Meteo."""

    def __init__(self):
        self.current_weather = None
        self.last_fetch = None

    # ── Settings helpers ────────────────────────────────────────────────────

    @property
    def lat(self):
        return settings.get("weather.latitude", -32.1151)

    @property
    def lon(self):
        return settings.get("weather.longitude", 116.0255)

    @property
    def provider(self):
        return settings.get("weather.provider", "BOM (Australia)")

    @property
    def temperature_unit(self):
        return settings.get("weather.temperature_unit", "celsius")

    @property
    def bom_station(self):
        return settings.get("weather.bom_station", "94609")  # Jandakot default

    @property
    def custom_url(self):
        return settings.get("weather.custom_url", "").strip()

    def _safe_coords(self):
        """Return validated float lat/lon, falling back to Kelmscott defaults."""
        try:
            lat = float(self.lat)
            lon = float(self.lon)
        except (TypeError, ValueError):
            lat, lon = -32.1151, 116.0255
        if lat == 0.0 and lon == 0.0:
            lat, lon = -32.1151, 116.0255
        return lat, lon

    # ── BOM fetch ────────────────────────────────────────────────────────────

    def _fetch_bom_observations(self, station_id: str) -> dict | None:
        """
        Fetch the latest observation from a BOM station JSON feed.
        Returns a normalised dict: {temp, condition, is_day, unit} or None.
        Data courtesy of the Australian Bureau of Meteorology (bom.gov.au).
        """
        url = BOM_OBS_URL.format(station_id=station_id)
        print(f"[Weather] BOM station URL: {url}")

        # BOM blocks requests without a browser-like User-Agent header
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "en-AU,en;q=0.9",
            "Referer":         "http://www.bom.gov.au/",
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"[Weather] BOM HTTP status: {response.status_code}")
            response.raise_for_status()
            data = response.json()

            observations = (
                data.get("observations", {})
                    .get("data", [])
            )
            if not observations:
                print("[Weather] BOM: no observation data in response")
                return None

            # Most recent observation is index 0
            obs = observations[0]
            print(f"[Weather] BOM latest obs: {obs}")

            temp_c = obs.get("air_temp")
            if temp_c is None:
                print("[Weather] BOM: air_temp missing from observation")
                return None

            unit = self.temperature_unit
            if unit == "fahrenheit":
                temp = temp_c * 9 / 5 + 32
                unit_sym = "°F"
            else:
                temp = temp_c
                unit_sym = "°C"

            desc    = obs.get("weather", "") or ""
            cond    = _bom_desc_to_condition(desc)
            code    = _desc_to_code(desc)
            is_day  = 1 if 6 <= datetime.now().hour < 20 else 0
            apparent = obs.get("apparent_t")
            humidity = obs.get("rel_hum")
            wind_spd = obs.get("wind_spd_kmh")
            wind_dir = obs.get("wind_dir")

            return {
                "temp":      round(temp, 1),
                "code":      code,
                "condition": cond,
                "is_day":    is_day,
                "unit":      unit_sym,
                "apparent":  apparent,
                "humidity":  humidity,
                "wind_spd":  wind_spd,
                "wind_dir":  wind_dir,
                "station":   obs.get("name", f"Station {station_id}"),
                "raw_desc":  desc,
            }

        except Exception as e:
            print(f"[Weather] BOM fetch error: {e}")
            traceback.print_exc()
            return None

    # ── Open-Meteo fetch ─────────────────────────────────────────────────────

    def _fetch_openmeteo(self, lat: float, lon: float) -> dict | None:
        """Fetch current + hourly data from Open-Meteo."""
        unit = self.temperature_unit or "celsius"
        params = {
            "latitude":         lat,
            "longitude":        lon,
            "current":          "temperature_2m,weather_code,is_day",
            "hourly":           "temperature_2m,weather_code",
            "temperature_unit": unit,
            "timezone":         "auto",
            "forecast_days":    1,
        }
        print(f"[Weather] Open-Meteo URL: {OPENMETEO_FORECAST_URL} lat={lat} lon={lon}")
        try:
            response = requests.get(OPENMETEO_FORECAST_URL, params=params, timeout=10)
            print(f"[Weather] Open-Meteo HTTP status: {response.status_code}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[Weather] Open-Meteo fetch error: {e}")
            traceback.print_exc()
            return None

    # ── Hourly forecast builder ──────────────────────────────────────────────

    def _build_forecast(self, om_data: dict) -> tuple:
        """Extract hourly forecast steps and high/low from Open-Meteo data."""
        hourly = om_data.get("hourly", {})
        times  = hourly.get("time", [])
        temps  = hourly.get("temperature_2m", [])
        codes  = hourly.get("weather_code", [])

        now_hour = datetime.now().hour
        forecast_step = []
        for i in range(now_hour, min(now_hour + 7, len(times)), 2):
            t_str = datetime.fromisoformat(times[i]).strftime("%I%p").lstrip("0")
            forecast_step.append({
                "time": t_str,
                "temp": round(temps[i], 1) if temps[i] is not None else 0,
                "code": codes[i] if codes[i] is not None else 0,
            })

        high = round(max(t for t in temps if t is not None), 1) if temps else 0
        low  = round(min(t for t in temps if t is not None), 1) if temps else 0
        return forecast_step[:4], high, low

    # ── Main get_weather ─────────────────────────────────────────────────────

    def get_weather(self) -> dict | None:
        """
        Fetch weather from the selected provider.
        Returns dict with: temp, code, is_day, forecast, high, low, unit, condition.
        Returns None on complete failure.
        """
        provider = self.provider or "BOM (Australia)"
        lat, lon = self._safe_coords()

        print(f"[Weather] Provider: {provider}  Lat/Lon: {lat}, {lon}")

        try:
            if provider == "BOM (Australia)":
                return self._get_bom(lat, lon)

            elif provider == "Open-Meteo (Global)":
                return self._get_openmeteo(lat, lon)

            elif provider == "Custom URL":
                url = self.custom_url
                if not url:
                    print("[Weather] Custom URL not set — falling back to Open-Meteo.")
                    return self._get_openmeteo(lat, lon)
                return self._get_custom(url, lat, lon)

            else:
                print(f"[Weather] Unknown provider '{provider}' — falling back to Open-Meteo.")
                return self._get_openmeteo(lat, lon)

        except Exception as e:
            print(f"[Weather] Unexpected error: {e}")
            traceback.print_exc()
            return None

    def _get_bom(self, lat: float, lon: float) -> dict | None:
        """BOM provider: current obs from BOM station + forecast from Open-Meteo."""
        station_id = self.bom_station or "94609"

        # 1. Current conditions from BOM observation station
        obs = self._fetch_bom_observations(station_id)

        # 2. Hourly forecast from Open-Meteo (BOM has no public forecast API)
        om_data = self._fetch_openmeteo(lat, lon)
        forecast, high, low = self._build_forecast(om_data) if om_data else ([], 0, 0)

        if obs is None and om_data is None:
            print("[Weather] Both BOM and Open-Meteo failed.")
            return None

        # Use BOM for current conditions, Open-Meteo for high/low/forecast
        if obs:
            unit = self.temperature_unit or "celsius"
            # Convert Open-Meteo high/low to correct unit if needed
            self.current_weather = {
                "temp":      obs["temp"],
                "code":      obs["code"],
                "condition": obs["condition"],
                "is_day":    obs["is_day"],
                "unit":      obs["unit"],
                "forecast":  forecast,
                "high":      high,
                "low":       low,
                "provider":  "BOM",
                "station":   obs.get("station", ""),
                "raw_desc":  obs.get("raw_desc", ""),
                "apparent":  obs.get("apparent"),
                "humidity":  obs.get("humidity"),
                "wind_spd":  obs.get("wind_spd"),
                "wind_dir":  obs.get("wind_dir"),
            }
        else:
            # BOM obs failed — fall back entirely to Open-Meteo
            print("[Weather] BOM obs failed — using Open-Meteo for current conditions.")
            return self._get_openmeteo(lat, lon)

        self.last_fetch = datetime.now()
        print(f"[Weather] Success — {self.current_weather['temp']}{self.current_weather['unit']} ({self.current_weather['condition']})")
        return self.current_weather

    def _get_openmeteo(self, lat: float, lon: float) -> dict | None:
        """Open-Meteo provider: all data from Open-Meteo."""
        om_data = self._fetch_openmeteo(lat, lon)
        if not om_data:
            return None

        current  = om_data.get("current", {})
        unit     = self.temperature_unit or "celsius"
        unit_sym = "°C" if unit == "celsius" else "°F"
        temp     = current.get("temperature_2m", 0)
        code     = current.get("weather_code", 0)
        is_day   = current.get("is_day", 1)

        forecast, high, low = self._build_forecast(om_data)

        self.current_weather = {
            "temp":      round(temp, 1) if temp is not None else 0,
            "code":      code,
            "condition": self._code_to_text(code),
            "is_day":    is_day,
            "unit":      unit_sym,
            "forecast":  forecast,
            "high":      high,
            "low":       low,
            "provider":  "Open-Meteo",
        }

        self.last_fetch = datetime.now()
        print(f"[Weather] Success — {self.current_weather['temp']}{unit_sym} ({self.current_weather['condition']})")
        return self.current_weather

    def _get_custom(self, url: str, lat: float, lon: float) -> dict | None:
        """Custom URL provider — treated as Open-Meteo-compatible endpoint."""
        unit = self.temperature_unit or "celsius"
        params = {
            "latitude": lat, "longitude": lon,
            "current":  "temperature_2m,weather_code,is_day",
            "hourly":   "temperature_2m,weather_code",
            "temperature_unit": unit,
            "timezone": "auto", "forecast_days": 1,
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return self._get_openmeteo(lat, lon)  # parse as Open-Meteo
        except Exception as e:
            print(f"[Weather] Custom URL failed: {e}")
            return None

    # ── Condition helpers ────────────────────────────────────────────────────

    def get_condition_info(self, code, is_day=1):
        return self._code_to_text(code)

    def _code_to_text(self, code):
        if code == 0:                          return "Clear"
        if code in [1, 2, 3]:                  return "Cloudy"
        if code in [45, 48]:                   return "Foggy"
        if code in [51, 53, 55, 61, 63, 65]:   return "Rain"
        if code in [71, 73, 75, 85, 86]:       return "Snow"
        if code in [95, 96, 99]:               return "Storm"
        return "Unknown"


weather_manager = WeatherManager()
