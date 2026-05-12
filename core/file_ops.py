"""
File Operations — find files, disk usage, organize directories.
Uses stdlib (os, glob, pathlib) — no external packages needed.
"""

import os
import glob as globmod
from pathlib import Path
from typing import Optional


class FileOps:

    @staticmethod
    def find(pattern: str, root: str = None) -> list:
        """Find files matching pattern within root directory."""
        if root is None:
            root = str(Path.home())
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            return []
        results = []
        full_pattern = os.path.join(root, "**", pattern)
        for path in globmod.iglob(full_pattern, recursive=True):
            if os.path.isfile(path):
                try:
                    size = os.path.getsize(path)
                    mtime = os.path.getmtime(path)
                    results.append({
                        "path": path,
                        "name": os.path.basename(path),
                        "size": size,
                        "size_hr": _human_size(size),
                        "modified": _format_time(mtime),
                    })
                except OSError:
                    pass
        results.sort(key=lambda x: x["modified"], reverse=True)
        return results[:50]

    @staticmethod
    def get_size(path: str) -> dict:
        """Get human-readable size of a file or directory."""
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return {"error": "Path does not exist"}
        try:
            if os.path.isfile(path):
                size = os.path.getsize(path)
                return {"path": path, "size": size, "size_hr": _human_size(size), "type": "file"}
            total = 0
            count = 0
            for dirpath, _, filenames in os.walk(path):
                for f in filenames:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, f))
                        count += 1
                    except OSError:
                        pass
            return {
                "path": path,
                "size": total,
                "size_hr": _human_size(total),
                "files": count,
                "type": "directory",
            }
        except OSError as e:
            return {"error": str(e)}

    @staticmethod
    def organize_downloads(downloads_path: str = None) -> dict:
        """Organize files in downloads folder by extension type."""
        if downloads_path is None:
            downloads_path = str(Path.home() / "Downloads")
        path = os.path.expanduser(downloads_path)
        if not os.path.isdir(path):
            return {"error": "Downloads directory not found"}

        categories = {
            "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico"],
            "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                          ".odt", ".ods", ".odp", ".txt", ".md", ".csv", ".rtf"],
            "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"],
            "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"],
            "Video": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"],
            "Code": [".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                     ".yaml", ".yml", ".sh", ".bat", ".ps1", ".sql"],
            "Installers": [".exe", ".msi", ".dmg", ".AppImage", ".deb", ".rpm"],
            "Torrents": [".torrent"],
        }

        moved = {}
        errors = []

        for entry in os.scandir(path):
            if not entry.is_file():
                continue
            ext = Path(entry.name).suffix.lower()
            target_category = "Other"
            for cat, exts in categories.items():
                if ext in exts:
                    target_category = cat
                    break
            target_dir = os.path.join(path, target_category)
            try:
                os.makedirs(target_dir, exist_ok=True)
                dest = os.path.join(target_dir, entry.name)
                counter = 1
                while os.path.exists(dest):
                    stem = Path(entry.name).stem
                    dest = os.path.join(target_dir, f"{stem}_{counter}{ext}")
                    counter += 1
                os.rename(entry.path, dest)
                moved[target_category] = moved.get(target_category, 0) + 1
            except OSError as e:
                errors.append(f"{entry.name}: {e}")

        result = {"total_moved": sum(moved.values()), "categories": moved}
        if errors:
            result["errors"] = errors
        return result

    @staticmethod
    def list_directory(path: str) -> list:
        """List contents of a directory."""
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return []
        entries = []
        try:
            for entry in os.scandir(path):
                try:
                    info = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "size": info.st_size if entry.is_file() else 0,
                        "size_hr": _human_size(info.st_size) if entry.is_file() else "",
                        "modified": _format_time(info.st_mtime),
                    })
                except OSError:
                    pass
        except OSError:
            pass
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return entries

    @staticmethod
    def disk_usage(path: str = None) -> dict:
        """Get disk usage info for a given path."""
        if path is None:
            path = "/"
        path = os.path.expanduser(path)
        try:
            usage = psutil.disk_usage(path)
        except (ImportError, OSError):
            import shutil
            usage = shutil.disk_usage(path)
        return {
            "path": path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
            "total_hr": _human_size(usage.total),
            "used_hr": _human_size(usage.used),
            "free_hr": _human_size(usage.free),
        }

    @staticmethod
    def create_directory(path: str) -> bool:
        """Create a directory (and parents)."""
        try:
            os.makedirs(os.path.expanduser(path), exist_ok=True)
            return True
        except OSError:
            return False


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _format_time(timestamp: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


file_ops = FileOps()


# Import psutil for disk_usage
import psutil
