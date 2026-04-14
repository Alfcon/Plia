"""
core/kasa_control.py
TP-Link Kasa device manager using the python-kasa library.

Changes from original:
  - discover_devices() now accepts optional username / password kwargs
    so newer KLAP-protocol devices (KP125M, EP25, etc.) can authenticate.
  - Credentials fall back gracefully if not supplied (older devices work without them).
"""

import asyncio
from kasa import Discover, Module
from typing import Any, Dict, Optional


class KasaManager:
    """Manager for TP-Link Kasa smart devices using the python-kasa Module API."""

    def __init__(self):
        self.devices: Dict[str, Any] = {}

    async def discover_devices(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Scan the network for Kasa devices.

        Args:
            username: TP-Link cloud email (required for newer KLAP-protocol devices).
            password: TP-Link cloud password (required for newer KLAP-protocol devices).

        Returns:
            Dict keyed by IP address containing device info dicts.
        """
        print("[KasaManager] Discovering Kasa devices …")
        try:
            kwargs: Dict[str, Any] = {"timeout": 5}
            if username and password:
                kwargs["username"] = username
                kwargs["password"] = password

            found = await Discover.discover(**kwargs)

            device_dict: Dict[str, Any] = {}
            for ip, dev in found.items():
                try:
                    await dev.update()

                    light_mod = dev.modules.get(Module.Light) if hasattr(dev, "modules") else None
                    is_dimmable = light_mod and light_mod.has_feature("brightness")
                    is_color    = light_mod and light_mod.has_feature("hsv")

                    device_dict[ip] = {
                        "alias":      dev.alias,
                        "ip":         ip,
                        "mac":        "",
                        "model":      dev.model,
                        "brand":      "kasa",
                        "is_on":      dev.is_on,
                        "type":       dev.device_type.name if hasattr(dev, "device_type") else "Unknown",
                        "brightness": light_mod.brightness if is_dimmable else None,
                        "is_color":   bool(is_color),
                        "hsv":        light_mod.hsv if is_color else None,
                        "obj":        dev,
                    }
                except Exception as dev_exc:
                    print(f"[KasaManager] Skipping {ip}: {dev_exc}")

            self.devices = device_dict
            print(f"[KasaManager] Found {len(device_dict)} device(s)")
            return device_dict

        except Exception as exc:
            print(f"[KasaManager] Discovery error: {exc}")
            return {}

    async def _get_fresh_device(self, ip: str,
                                 username: Optional[str] = None,
                                 password: Optional[str] = None):
        """Connect to a device by IP, returning a freshly updated device object."""
        kwargs: Dict[str, Any] = {}
        if username and password:
            kwargs["username"] = username
            kwargs["password"] = password
        try:
            dev = await Discover.discover_single(ip, **kwargs)
            if dev:
                await dev.update()
            return dev
        except Exception as exc:
            print(f"[KasaManager] Cannot reach {ip}: {exc}")
            return None

    async def _get_light_module(self, ip: str):
        """Return (device, light_module) for bulb/dimmer devices."""
        try:
            dev = await Discover.discover_single(ip)
            if dev:
                await dev.update()
                if hasattr(dev, "modules") and Module.Light in dev.modules:
                    return dev, dev.modules[Module.Light]
            return dev, None
        except Exception as exc:
            print(f"[KasaManager] Light module error for {ip}: {exc}")
            return None, None

    async def turn_on(self, ip: str, dev: Any = None) -> bool:
        try:
            if dev is None:
                dev = await self._get_fresh_device(ip)
            if dev:
                await dev.turn_on()
                return True
        except Exception as exc:
            print(f"[KasaManager] turn_on {ip}: {exc}")
        return False

    async def turn_off(self, ip: str, dev: Any = None) -> bool:
        try:
            if dev is None:
                dev = await self._get_fresh_device(ip)
            if dev:
                await dev.turn_off()
                return True
        except Exception as exc:
            print(f"[KasaManager] turn_off {ip}: {exc}")
        return False

    async def set_brightness(self, ip: str, level: int, dev: Any = None) -> bool:
        try:
            light = None
            if dev:
                await dev.update()
                if hasattr(dev, "modules") and Module.Light in dev.modules:
                    light = dev.modules[Module.Light]
            else:
                dev, light = await self._get_light_module(ip)

            if light and light.has_feature("brightness"):
                await light.set_brightness(level)
                return True
        except Exception as exc:
            print(f"[KasaManager] set_brightness {ip}: {exc}")
        return False

    async def set_hsv(self, ip: str, h: int, s: int, v: int, dev: Any = None) -> bool:
        try:
            light = None
            if dev:
                await dev.update()
                if hasattr(dev, "modules") and Module.Light in dev.modules:
                    light = dev.modules[Module.Light]
            else:
                dev, light = await self._get_light_module(ip)

            if light and light.has_feature("hsv"):
                await light.set_hsv(h, s, v)
                return True
        except Exception as exc:
            print(f"[KasaManager] set_hsv {ip}: {exc}")
        return False


# Global singleton
kasa_manager = KasaManager()
