"""
System Control — volume, brightness, power, battery, network info.
Cross-platform: Windows (primary), Linux (secondary).
No external packages needed beyond stdlib + psutil (already in Plia).
"""

import os
import platform
import subprocess
import re
import socket
from typing import Optional

import psutil

SYSTEM = platform.system()


class SystemController:

    @staticmethod
    def get_battery() -> dict:
        """Return battery percentage, charging state, and remaining time."""
        battery = psutil.sensors_battery()
        if battery is None:
            return {"available": False}
        return {
            "available": True,
            "percent": round(battery.percent, 1),
            "charging": battery.power_plugged or False,
            "remaining": battery.secsleft if battery.secsleft != -1 else None,
        }

    @staticmethod
    def get_volume() -> Optional[int]:
        """Return system volume level 0-100, or None if unsupported."""
        if SYSTEM == "Windows":
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                level = round(volume.GetMasterVolumeLevelScalar() * 100)
                return level
            except ImportError:
                pass
            except Exception:
                pass
            try:
                result = subprocess.run(
                    ["powershell", "-c", "(Get-AudioDevice -PlaybackVolume).Volume"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return int(float(result.stdout.strip()))
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                result = subprocess.run(
                    ["amixer", "sget", "Master"],
                    capture_output=True, text=True, timeout=3
                )
                m = re.search(r'(\d+)%', result.stdout)
                if m:
                    return int(m.group(1))
            except Exception:
                pass
        return None

    @staticmethod
    def set_volume(level: int) -> bool:
        """Set volume 0-100."""
        level = max(0, min(100, level))
        if SYSTEM == "Windows":
            try:
                subprocess.run(
                    ["powershell", "-c", f"Set-AudioDevice -PlaybackVolume {level}"],
                    capture_output=True, timeout=5
                )
                return True
            except Exception:
                pass
            try:
                nircmd = os.path.expandvars(r"%ProgramFiles%\nircmd\nircmd.exe")
                if os.path.exists(nircmd):
                    subprocess.run([nircmd, "setsysvolume", str(level * 655)], timeout=3)
                    return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["amixer", "sset", "Master", f"{level}%"],
                               capture_output=True, timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def toggle_mute() -> Optional[bool]:
        """Toggle system mute. Returns new muted state or None."""
        if SYSTEM == "Windows":
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                muted = volume.GetMute()
                volume.SetMute(not muted, None)
                return not muted
            except ImportError:
                pass
            except Exception:
                pass
            try:
                result = subprocess.run(
                    ["powershell", "-c", "(Get-AudioDevice -PlaybackVolume).Muted"],
                    capture_output=True, text=True, timeout=5
                )
                new_mute = "True" not in result.stdout
                subprocess.run(
                    ["powershell", "-c", f"Set-AudioDevice -PlaybackMute ${new_mute}"],
                    capture_output=True, timeout=5
                )
                return new_mute
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["amixer", "sset", "Master", "toggle"],
                               capture_output=True, timeout=3)
                result = subprocess.run(["amixer", "sget", "Master"],
                                        capture_output=True, text=True, timeout=3)
                return "[on]" in result.stdout
            except Exception:
                pass
        return None

    @staticmethod
    def get_brightness() -> Optional[int]:
        """Return screen brightness 0-100, or None."""
        if SYSTEM == "Windows":
            try:
                result = subprocess.run(
                    ["powershell", "-c",
                     "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip().isdigit():
                    return int(result.stdout.strip())
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                result = subprocess.run(
                    ["brightnessctl", "g"], capture_output=True, text=True, timeout=3
                )
                max_r = subprocess.run(
                    ["brightnessctl", "m"], capture_output=True, text=True, timeout=3
                )
                if result.stdout.strip().isdigit() and max_r.stdout.strip().isdigit():
                    return int(int(result.stdout.strip()) / int(max_r.stdout.strip()) * 100)
            except Exception:
                pass
        return None

    @staticmethod
    def set_brightness(level: int) -> bool:
        """Set screen brightness 0-100."""
        level = max(0, min(100, level))
        if SYSTEM == "Windows":
            try:
                subprocess.run(
                    ["powershell", "-c",
                     f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                     f".WmiSetBrightness(1, {level})"],
                    capture_output=True, timeout=5
                )
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["brightnessctl", "s", f"{level}%"],
                               capture_output=True, timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def get_network_info() -> dict:
        """Return network SSID, IP, interface info."""
        info = {"interfaces": []}
        try:
            hostname = socket.gethostname()
            info["hostname"] = hostname
        except Exception:
            pass
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            info["local_ip"] = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        for name, stats in psutil.net_if_stats().items():
            if stats.isup:
                addrs = psutil.net_if_addrs().get(name, [])
                ip4 = next((a.address for a in addrs if a.family == socket.AF_INET), None)
                if ip4:
                    info["interfaces"].append({
                        "name": name,
                        "ip": ip4,
                        "speed": stats.speed,
                    })
        if SYSTEM == "Windows":
            try:
                result = subprocess.run(
                    ["powershell", "-c",
                     "(Get-NetConnectionProfile).Name"],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    info["ssid"] = result.stdout.strip()
            except Exception:
                pass
        return info

    @staticmethod
    def shutdown(delay: int = 60) -> bool:
        """Shutdown the computer after delay seconds."""
        if SYSTEM == "Windows":
            try:
                subprocess.run(["shutdown", "/s", "/t", str(delay)], timeout=3)
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["shutdown", "-h", f"+{delay // 60}"], timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def restart(delay: int = 60) -> bool:
        """Restart the computer after delay seconds."""
        if SYSTEM == "Windows":
            try:
                subprocess.run(["shutdown", "/r", "/t", str(delay)], timeout=3)
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["shutdown", "-r", f"+{delay // 60}"], timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def sleep() -> bool:
        """Put the computer to sleep."""
        if SYSTEM == "Windows":
            try:
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                               timeout=3)
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["systemctl", "suspend"], timeout=3)
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def lock() -> bool:
        """Lock the workstation."""
        if SYSTEM == "Windows":
            try:
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], timeout=3)
                return True
            except Exception:
                pass
        elif SYSTEM == "Linux":
            try:
                subprocess.run(["loginctl", "lock-session"], timeout=3)
                return True
            except Exception:
                pass
        return False


system_controller = SystemController()
