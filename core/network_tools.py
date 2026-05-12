"""
Network Tools — public IP, ping, DNS lookup.
Uses stdlib + requests (already in Plia).
"""

import socket
import subprocess
import re
import platform
from typing import Optional

import requests


SYSTEM = platform.system()


class NetworkTools:

    @staticmethod
    def public_ip() -> Optional[str]:
        """Get public IP address via ipify.org."""
        try:
            resp = requests.get("https://api.ipify.org?format=json", timeout=8)
            resp.raise_for_status()
            return resp.json().get("ip")
        except Exception:
            pass
        try:
            resp = requests.get("https://api.ip.sb/ip", timeout=8)
            resp.raise_for_status()
            return resp.text.strip()
        except Exception:
            return None

    @staticmethod
    def public_ip_info() -> Optional[dict]:
        """Get public IP with geolocation info (city, country, ISP)."""
        try:
            resp = requests.get("http://ip-api.com/json/", timeout=8)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return {
                    "ip": data.get("query"),
                    "city": data.get("city"),
                    "region": data.get("regionName"),
                    "country": data.get("country"),
                    "isp": data.get("isp"),
                    "org": data.get("org"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                }
        except Exception:
            pass
        ip = NetworkTools.public_ip()
        return {"ip": ip} if ip else None

    @staticmethod
    def ping(host: str = "8.8.8.8", count: int = 4) -> dict:
        """Ping a host and return statistics."""
        if SYSTEM == "Windows":
            cmd = ["ping", "-n", str(count), host]
        else:
            cmd = ["ping", "-c", str(count), host]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout + result.stderr

            avg = None
            loss = None
            m = re.search(r'(?:Average|avg|mittelwert|moyenne|media|rtt)\s*[:=]\s*(\d+\.?\d*)\s*ms',
                          output, re.IGNORECASE)
            if not m:
                m = re.search(r'(?:min/avg/max|min/avg/max/mdev)\s*[:=]\s*[0-9.]+/(\d+\.?\d+)/',
                              output, re.IGNORECASE)
            if m:
                avg = round(float(m.group(1)), 1)

            m = re.search(r'(\d+)%\s*(?:loss|packet loss)', output, re.IGNORECASE)
            if not m:
                m = re.search(r'(?:loss|packet loss)\s*[:=]\s*(\d+)%', output, re.IGNORECASE)
            if m:
                loss = int(m.group(1))

            return {
                "host": host,
                "alive": loss is None or loss < 100,
                "avg_ms": avg,
                "packet_loss_pct": loss if loss is not None else 0,
                "output": output[:500],
            }
        except subprocess.TimeoutExpired:
            return {"host": host, "alive": False, "error": "timeout"}
        except FileNotFoundError:
            return {"host": host, "alive": False, "error": "ping not found"}
        except Exception as e:
            return {"host": host, "alive": False, "error": str(e)}

    @staticmethod
    def dns_lookup(hostname: str) -> list:
        """DNS resolve a hostname to IP addresses."""
        try:
            results = []
            for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
                ip = sockaddr[0]
                if ip not in results:
                    results.append(ip)
            return results
        except socket.gaierror:
            return []
        except Exception:
            return []

    @staticmethod
    def speed_test() -> dict:
        """Approximate internet speed via download test from speedtest servers."""
        try:
            import time
            url = "https://proof.ovh.net/files/10Mb.dat"
            start = time.time()
            resp = requests.get(url, stream=True, timeout=15)
            resp.raise_for_status()
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=8192):
                downloaded += len(chunk)
            elapsed = time.time() - start
            if elapsed > 0:
                speed_bps = downloaded * 8 / elapsed
                speed_mbps = round(speed_bps / 1_000_000, 1)
                return {
                    "download_mbps": speed_mbps,
                    "duration_s": round(elapsed, 1),
                    "size_mb": round(downloaded / 1_000_000, 1),
                }
        except ImportError:
            pass
        except Exception:
            pass
        return {"error": "Speed test unavailable"}


network_tools = NetworkTools()
