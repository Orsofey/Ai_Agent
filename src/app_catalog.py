"""Discover and launch installed Windows applications.

The scanner reads Start Menu shortcuts and common executable folders. It does
not execute arbitrary shell text; launches are made from a selected catalog
entry using os.startfile/subprocess.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


@dataclass
class LaunchResult:
    success: bool
    message: str
    application: dict | None = None


class ApplicationCatalog:
    def __init__(self):
        self._cache = []
        self._cache_time = 0.0

    @staticmethod
    def _roots():
        roots = []
        appdata = os.environ.get("APPDATA")
        program_data = os.environ.get("PROGRAMDATA")
        local = os.environ.get("LOCALAPPDATA")
        if appdata:
            roots.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs")
        if program_data:
            roots.append(Path(program_data) / "Microsoft/Windows/Start Menu/Programs")
        if local:
            roots.extend([Path(local) / "Programs", Path(local) / "Microsoft/WindowsApps"])
        for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            value = os.environ.get(variable)
            if value:
                roots.append(Path(value))
        return roots

    @staticmethod
    def _clean_name(value):
        return re.sub(r"\s+", " ", value.replace("_", " ").strip()).strip()

    def list_applications(self, force=False):
        if os.name != "nt":
            return [{"name": "Web browser", "path": "", "kind": "browser"}]
        now = time.time()
        if self._cache and not force and now - self._cache_time < 60:
            return self._cache
        seen = {}
        roots = self._roots()
        extensions = {".lnk", ".url", ".exe"}
        for root in roots:
            if not root.exists():
                continue
            try:
                iterator = root.rglob("*") if "Start Menu" in str(root) else root.glob("*")
                for item in iterator:
                    if not item.is_file() or item.suffix.casefold() not in extensions:
                        continue
                    if item.name.casefold() in {"uninstall.exe", "unins000.exe"}:
                        continue
                    name = self._clean_name(item.stem)
                    if not name or len(name) < 2:
                        continue
                    key = name.casefold()
                    seen.setdefault(key, {"name": name, "path": str(item), "kind": item.suffix.lower()[1:]})
            except (OSError, PermissionError):
                continue
        # Include Windows StartApps (Microsoft Store/UWP applications).
        if os.name == "nt":
            try:
                output = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
                    capture_output=True, text=True, timeout=20, check=False,
                ).stdout
                rows = json.loads(output) if output.strip() else []
                if isinstance(rows, dict):
                    rows = [rows]
                for row in rows:
                    name = self._clean_name(str(row.get("Name", "")))
                    app_id = str(row.get("AppID", ""))
                    if name and app_id:
                        seen.setdefault(name.casefold(), {"name": name, "path": app_id, "kind": "startapp"})
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass

        # Include common aliases even when the executable is on PATH.
        for executable in ("chrome.exe", "msedge.exe", "firefox.exe", "Code.exe", "WINWORD.EXE", "EXCEL.EXE", "notepad.exe", "calc.exe", "explorer.exe"):
            path = shutil.which(executable)
            if path:
                name = Path(path).stem
                seen.setdefault(name.casefold(), {"name": name, "path": path, "kind": "exe"})
        self._cache = sorted(seen.values(), key=lambda item: item["name"].casefold())[:2000]
        self._cache_time = now
        return self._cache

    def find(self, query):
        query = self._clean_name(query).casefold()
        items = self.list_applications()
        exact = next((item for item in items if item["name"].casefold() == query), None)
        if exact:
            return exact
        return next((item for item in items if query in item["name"].casefold()), None)

    def launch(self, query):
        item = query if isinstance(query, dict) else self.find(query)
        if not item:
            return LaunchResult(False, f"Приложение «{query}» не найдено в меню Пуск и стандартных каталогах.")
        path = item.get("path", "")
        try:
            if os.name == "nt" and item.get("kind") == "startapp":
                command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Start-Process 'shell:AppsFolder\\{path}'"]
                subprocess.Popen(command, shell=False)
            elif os.name == "nt" and path.lower().endswith((".lnk", ".url")):
                os.startfile(path)  # noqa: S606 - intentional selected shortcut launch
            elif os.name == "nt":
                subprocess.Popen([path], shell=False)
            elif path:
                subprocess.Popen([path], shell=False)
            else:
                return LaunchResult(False, "В этой системе нет пути запуска для приложения.", item)
            return LaunchResult(True, f"Запуск выполнен: {item['name']}", item)
        except (OSError, PermissionError) as error:
            return LaunchResult(False, f"Не удалось открыть {item['name']}: {error}", item)


catalog = ApplicationCatalog()
