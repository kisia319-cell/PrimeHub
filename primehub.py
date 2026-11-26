import os, sys, json, time, shutil, threading, urllib.request, urllib.error, urllib.parse, zipfile, subprocess, re, html, ctypes, hashlib, traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "PrimeHub"
APP_VERSION = "v1.3.0"
APOCALYPSE_PC_VERSION = "apocalypse-pc-v1.5.5"
ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PrimeHub"
GAMES = ROOT / "Games"
DATA = ROOT / "hub-state.json"
AUTH_SESSION = ROOT / "auth-session.bin"
APOCALYPSE_CONFIG = ROOT / "apocalypse-settings.json"
API_SKY = "https://api.github.com/repos/kisia319-cell/SkyRealm-PC-Launcher/releases/latest"
API_APOCALYPSE_PC = "https://api.github.com/repos/kisia319-cell/SkyRealm-Hub-Mobile/releases?per_page=100"
API_PRIME_MOBILE = "https://api.github.com/repos/kisia319-cell/SkyRealm-Hub-Mobile/releases/latest"
API_HUB = "https://api.github.com/repos/kisia319-cell/PrimeHub/releases/latest"
API_AUTH = "https://jaaguprbfrzrcwuusher.supabase.co/functions/v1/skyrealm-auth"
API_KEY = "sb_publishable_MKaNYqw3r0BLa1GTDVvjfw_yU3Wd6QL"
HEADERS = {"User-Agent": "PrimeHub/1.0", "Accept": "application/vnd.github+json"}


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi_transform(raw: bytes, protect: bool) -> bytes:
    """Encrypt/decrypt small local secrets with the current Windows user's DPAPI."""
    if os.name != "nt":
        raise OSError("Windows DPAPI is unavailable")
    source_buffer = ctypes.create_string_buffer(raw)
    source = _DATA_BLOB(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DATA_BLOB()
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(_DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_DATA_BLOB)]
    crypt.CryptProtectData.restype = ctypes.c_int
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_DATA_BLOB)]
    crypt.CryptUnprotectData.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if protect:
        ok = crypt.CryptProtectData(ctypes.byref(source), "PrimeHub auth session", None, None, None, 0x1, ctypes.byref(target))
    else:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(target.pbData)

def _version_key(value):
    """Compare dotted release versions numerically (v1.2.10 > v1.2.9)."""
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts) if parts else ()


COLORS = {"bg":"#0b1020","panel":"#121a2d","panel2":"#18243b","line":"#263650","text":"#eef4ff","muted":"#91a3bf","blue":"#4d8dff","cyan":"#55d5e8","green":"#54d69a","orange":"#ffbd66"}

class PrimeHub:
    def __init__(self, root):
        self.root = root
        self.root.title("PrimeHub")
        self.root.geometry("1120x740")
        self.root.minsize(900, 620)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.platform = "PC"
        self.releases = {}
        self.busy = False
        self.state = self.load_state()
        self.root.geometry(self.get_launcher_settings().get("window_geometry", "1120x740"))
        self.channel_status = self.state.get("channel_status", {}) if isinstance(self.state.get("channel_status", {}), dict) else {}
        self.channels_view = None
        self.session = None  # Only the rotating refresh token is persisted, encrypted with Windows DPAPI.
        self.pending_email = ""
        self.account_window = None
        self.build_ui()
        self.refresh_cards()
        self.root.after(250, self.restore_auth_session_async)
        if self.get_launcher_settings().get('check_updates_on_start', True):
            self.root.after(700, self.check_updates_async)
        else:
            self.set_status('Автоматическая проверка отключена настройками', COLORS['muted'])

    def on_close(self):
        try:
            settings = self.get_launcher_settings()
            if settings.get("remember_window_size", True):
                settings["window_geometry"] = self.root.geometry()
                self.state["primehub_settings"] = settings
                self.save_state()
        except (tk.TclError, OSError, ValueError):
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def load_state(self):
        try:
            value = json.loads(DATA.read_text("utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            if DATA.exists():
                try:
                    damaged = DATA.with_name("hub-state.corrupt-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
                    DATA.replace(damaged)
                except OSError:
                    pass
            return {}
    def save_state(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        temp = DATA.with_suffix(".tmp")
        payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, DATA)
    def build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Hub.Horizontal.TProgressbar", troughcolor=COLORS["panel2"], background=COLORS["blue"], bordercolor=COLORS["panel2"], lightcolor=COLORS["blue"], darkcolor=COLORS["blue"])

        shell = tk.Frame(self.root, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(shell, bg=COLORS["panel"], width=214, highlightbackground=COLORS["line"], highlightthickness=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.content = tk.Frame(shell, bg=COLORS["bg"])
        self.content.pack(side="left", fill="both", expand=True)

        brand = tk.Frame(self.sidebar, bg=COLORS["panel"])
        brand.pack(fill="x", padx=18, pady=(24, 26))
        tk.Label(brand, text="PRIME", font=("Segoe UI", 21, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
        tk.Label(brand, text="HUB  /  GAME CENTER", font=("Segoe UI", 8, "bold"), fg=COLORS["blue"], bg=COLORS["panel"]).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.sidebar, bg=COLORS["line"], height=1).pack(fill="x", padx=14, pady=(0, 12))

        self.nav_home = tk.Button(self.sidebar, text="▦   Моя библиотека", command=self.show_home, anchor="w", bg=COLORS["blue"], fg="white", activebackground=COLORS["blue"], activeforeground="white", bd=0, padx=17, pady=13, font=("Segoe UI", 10, "bold"), cursor="hand2")
        self.nav_home.pack(fill="x", padx=10, pady=4)
        self.nav_settings = tk.Button(self.sidebar, text="⚙   Настройки", command=self.show_settings, anchor="w", bg=COLORS["panel"], fg=COLORS["muted"], activebackground=COLORS["panel2"], activeforeground=COLORS["text"], bd=0, padx=17, pady=13, font=("Segoe UI", 10, "bold"), cursor="hand2")
        self.nav_settings.pack(fill="x", padx=10, pady=4)
        self.nav_channels = tk.Button(self.sidebar, text="◉   Каналы и диагностика", command=self.show_channels, anchor="w", bg=COLORS["panel"], fg=COLORS["muted"], activebackground=COLORS["panel2"], activeforeground=COLORS["text"], bd=0, padx=17, pady=12, font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.nav_channels.pack(fill="x", padx=10, pady=3)
        tk.Label(self.sidebar, text="ПРОФИЛЬ ИГР", font=("Segoe UI", 8, "bold"), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", padx=18, pady=(22, 7))
        self.nav_apocalypse = tk.Button(self.sidebar, text="☣   Apocalypse", command=self.show_apocalypse_settings, anchor="w", bg=COLORS["panel"], fg="#e89a9d", activebackground=COLORS["panel2"], activeforeground=COLORS["text"], bd=0, padx=17, pady=11, font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.nav_apocalypse.pack(fill="x", padx=10, pady=2)
        tk.Frame(self.sidebar, bg=COLORS["panel"]).pack(fill="both", expand=True)
        tk.Label(self.sidebar, text="PRIMEHUB  " + APP_VERSION, font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", padx=17, pady=(0, 18))

        self.home_view = tk.Frame(self.content, bg=COLORS["bg"])
        self.home_view.pack(fill="both", expand=True)
        header = tk.Frame(self.home_view, bg=COLORS["bg"])
        header.pack(fill="x", padx=28, pady=(22, 12))
        brand_header = tk.Frame(header, bg=COLORS["bg"])
        brand_header.pack(side="left")
        tk.Label(brand_header, text="ТВОЯ БИБЛИОТЕКА", font=("Segoe UI", 18, "bold"), fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        self.platform_box = tk.Frame(header, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        self.platform_box.pack(side="right")
        self.pc_btn = tk.Button(self.platform_box, text="▣  PC", command=lambda:self.set_platform("PC"), bd=0, padx=18, pady=10, font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.android_btn = tk.Button(self.platform_box, text="▣  ANDROID", command=lambda:self.set_platform("Android"), bd=0, padx=18, pady=10, font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.pc_btn.pack(side="left")
        self.android_btn.pack(side="left")
        self.account_btn = tk.Button(header, text="Войти / Регистрация", command=self.open_account, bg=COLORS["panel2"], fg=COLORS["text"], activebackground=COLORS["line"], activeforeground=COLORS["text"], bd=0, padx=13, pady=10, font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.account_btn.pack(side="right", padx=(0, 10))

        hero = tk.Frame(self.home_view, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        hero.pack(fill="x", padx=28, pady=(6, 17))
        hero_inner = tk.Frame(hero, bg=COLORS["panel"])
        hero_inner.pack(fill="x", padx=22, pady=17)
        tk.Label(hero_inner, text="ТВОИ ИГРЫ. В ОДНОМ МЕСТЕ.", font=("Segoe UI", 18, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
        tk.Label(hero_inner, text="PrimeHub проверяет обновления, устанавливает файлы и запускает игры.", font=("Segoe UI", 9), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", pady=(6, 0))
        row = tk.Frame(hero_inner, bg=COLORS["panel"])
        row.pack(fill="x", pady=(12, 0))
        self.status = tk.Label(row, text="● Проверка каталога...", font=("Segoe UI", 9, "bold"), fg=COLORS["cyan"], bg=COLORS["panel"])
        self.status.pack(side="left")
        self.refresh_btn = tk.Button(row, text="Проверить обновления", command=self.check_updates_async, bg=COLORS["panel2"], fg=COLORS["text"], activebackground=COLORS["line"], activeforeground=COLORS["text"], bd=0, padx=13, pady=8, cursor="hand2")
        self.refresh_btn.pack(side="right")
        # Keep a permanent packed slot between the hero and library. The banner
        # itself can be hidden/shown inside this slot without pack(before=...),
        # which raises TclError when its sibling is temporarily unmanaged.
        self.update_banner_slot = tk.Frame(self.home_view, bg=COLORS["bg"])
        self.update_banner_slot.pack(fill="x", padx=28, pady=(0, 10))
        self.update_banner = tk.Frame(self.update_banner_slot, bg="#183b35", highlightbackground=COLORS["green"], highlightthickness=1)
        self.update_banner_label = tk.Label(self.update_banner, text="", font=("Segoe UI", 10, "bold"), fg="#d9fff0", bg="#183b35", justify="left")
        self.update_banner_label.pack(side="left", fill="x", expand=True, padx=16, pady=12)
        self.update_banner_button = tk.Button(self.update_banner, text="ОБНОВИТЬ APOCALYPSE", command=lambda:self.install_game("Apocalypse"), bg=COLORS["green"], fg="#071b16", activebackground="#8af0c0", bd=0, padx=18, pady=11, font=("Segoe UI", 10, "bold"), cursor="hand2")
        self.update_banner_button.pack(side="right", padx=12, pady=8)
        self.update_banner.pack_forget()
        self.library_section = tk.Frame(self.home_view, bg=COLORS["bg"])
        self.library_section.pack(fill="x", padx=28, pady=(0, 9))
        section = self.library_section
        tk.Label(section, text="БИБЛИОТЕКА", font=("Segoe UI", 10, "bold"), fg=COLORS["muted"], bg=COLORS["bg"]).pack(side="left")
        self.count_label = tk.Label(section, text="", font=("Segoe UI", 9), fg=COLORS["muted"], bg=COLORS["bg"])
        self.count_label.pack(side="right")
        self.cards = tk.Frame(self.home_view, bg=COLORS["bg"])
        self.cards.pack(fill="both", expand=True, padx=28, pady=(0, 8))
        bottom = tk.Frame(self.home_view, bg=COLORS["bg"])
        bottom.pack(fill="x", padx=28, pady=(0, 16))
        self.progress = ttk.Progressbar(bottom, style="Hub.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.progress_text = tk.Label(bottom, text="Игры устанавливаются в папку PrimeHub, не на рабочий стол.", font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["bg"])
        self.progress_text.pack(anchor="w", pady=(7, 0))
        self.settings_view = None
        last_platform = self.state.get("last_platform", "PC") if self.get_launcher_settings().get("remember_platform", True) else "PC"
        self.set_platform(last_platform if last_platform in ("PC", "Android") else "PC")

    def get_launcher_settings(self):
        defaults = {
            "check_updates_on_start": True, "confirm_updates": True,
            "close_hub_after_launch": False, "remember_platform": True,
            "download_unlimited": True, "download_limit_mbps": 2.0,
            "check_skyrealm_channel": True, "check_apocalypse_channel": True,
            "check_android_channel": True, "check_primehub_channel": True,
            "network_retries": 2, "network_timeout_seconds": 35,
            "keep_backups": True, "clear_cache_after_install": False,
            "remember_window_size": True, "window_geometry": "1120x740",
        }
        stored = self.state.get("primehub_settings", {})
        if not isinstance(stored, dict):
            stored = {}
        result = {**defaults, **stored}
        for key in (
            "check_updates_on_start", "confirm_updates", "close_hub_after_launch",
            "remember_platform", "download_unlimited", "check_skyrealm_channel",
            "check_apocalypse_channel", "check_android_channel", "check_primehub_channel",
            "keep_backups", "clear_cache_after_install", "remember_window_size",
        ):
            result[key] = bool(result.get(key, defaults[key]))
        try:
            result["download_limit_mbps"] = max(0.05, min(1000.0, float(result["download_limit_mbps"])))
        except (TypeError, ValueError):
            result["download_limit_mbps"] = defaults["download_limit_mbps"]
        try:
            result["network_retries"] = max(0, min(4, int(result["network_retries"])))
        except (TypeError, ValueError):
            result["network_retries"] = defaults["network_retries"]
        try:
            result["network_timeout_seconds"] = max(10, min(120, int(result["network_timeout_seconds"])))
        except (TypeError, ValueError):
            result["network_timeout_seconds"] = defaults["network_timeout_seconds"]
        geometry = str(result.get("window_geometry") or defaults["window_geometry"])
        result["window_geometry"] = geometry if re.fullmatch(r"\d{3,4}x\d{3,4}(?:[+-]\d+){0,2}", geometry) else defaults["window_geometry"]
        return result
    def get_apocalypse_settings(self):
        defaults = {
            "effects": "high", "joy": 100, "motion": True, "hints": True,
            "weather": True, "ambientAudio": True, "infectedCap": 18,
            "eventFrequency": 1.0, "autosaveSeconds": 5,
            "autoSprint": False, "showHydration": True, "survivalDifficulty": "standard", "renderDistance": "normal", "showEnemyHealth": True, "showSurvivalHud": True,
        }
        stored = self.state.get("apocalypse_settings", {})
        if not isinstance(stored, dict):
            stored = {}
        try:
            if APOCALYPSE_CONFIG.is_file():
                disk = json.loads(APOCALYPSE_CONFIG.read_text(encoding="utf-8"))
                if isinstance(disk, dict):
                    stored = {**stored, **disk}
        except (OSError, ValueError, TypeError):
            pass
        result = {**defaults, **stored}
        if result["effects"] not in ("high", "balanced", "low"):
            result["effects"] = "high"
        result["joy"] = max(85, min(135, int(result.get("joy", 100))))
        result["infectedCap"] = max(8, min(24, int(result.get("infectedCap", 18))))
        result["eventFrequency"] = max(0.5, min(1.8, float(result.get("eventFrequency", 1))))
        result["autosaveSeconds"] = int(result.get("autosaveSeconds", 5))
        if result["autosaveSeconds"] not in (5, 10, 15, 30):
            result["autosaveSeconds"] = 5
        if result.get("survivalDifficulty") not in ("easy", "standard", "hard"):
            result["survivalDifficulty"] = "standard"
        if result.get("renderDistance") not in ("near", "normal", "far"):
            result["renderDistance"] = "normal"
        for key in ("motion", "hints", "weather", "ambientAudio", "autoSprint", "showHydration", "showEnemyHealth", "showSurvivalHud"):
            result[key] = bool(result.get(key, defaults[key]))
        return result

    def _save_settings_to_disk(self):
        self.state["primehub_settings"] = self.get_launcher_settings()
        settings = self._settings_form_values if getattr(self, "_settings_form_values", None) else self.get_apocalypse_settings()
        self.state["apocalypse_settings"] = dict(settings)
        ROOT.mkdir(parents=True, exist_ok=True)
        temp = APOCALYPSE_CONFIG.with_suffix(".tmp")
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, APOCALYPSE_CONFIG)
        self.save_state()

    def _nav_style(self, active):
        self.nav_home.configure(bg=COLORS["blue"] if active == "home" else COLORS["panel"], fg="white" if active == "home" else COLORS["muted"])
        self.nav_settings.configure(bg=COLORS["blue"] if active == "settings" else COLORS["panel"], fg="white" if active == "settings" else COLORS["muted"])
        self.nav_channels.configure(bg=COLORS["blue"] if active == "channels" else COLORS["panel"], fg="white" if active == "channels" else COLORS["muted"])
        self.nav_apocalypse.configure(bg=COLORS["panel2"] if active == "apocalypse" else COLORS["panel"], fg="#ffd6d7" if active == "apocalypse" else "#e89a9d")
    def show_home(self):
        if self.settings_view and self.settings_view.winfo_exists():
            self.settings_view.pack_forget()
        if self.channels_view and self.channels_view.winfo_exists():
            self.channels_view.pack_forget()
        self.home_view.pack(fill="both", expand=True)
        self._nav_style("home")
    def show_settings(self):
        self._render_settings("settings")

    def show_apocalypse_settings(self):
        self._render_settings("apocalypse")

    def show_channels(self):
        self._render_channels()

    def _render_settings(self, active_tab="settings"):
        self.home_view.pack_forget()
        if self.channels_view and self.channels_view.winfo_exists():
            self.channels_view.pack_forget()
        if self.settings_view and self.settings_view.winfo_exists():
            self.settings_view.destroy()
        self.settings_view = tk.Frame(self.content, bg=COLORS["bg"])
        self.settings_view.pack(fill="both", expand=True)
        self._nav_style(active_tab)

        title = tk.Label(self.settings_view, text="Настройки PrimeHub" if active_tab == "settings" else "Настройки Apocalypse", font=("Segoe UI", 20, "bold"), fg=COLORS["text"], bg=COLORS["bg"])
        title.pack(anchor="w", padx=28, pady=(24, 5))
        subtitle = "Параметры лаунчера сохраняются в профиле пользователя." if active_tab == "settings" else "Эти параметры передаются в Apocalypse при запуске и синхронизируются с её внутриигровым меню."
        tk.Label(self.settings_view, text=subtitle, font=("Segoe UI", 9), fg=COLORS["muted"], bg=COLORS["bg"]).pack(anchor="w", padx=28, pady=(0, 14))

        canvas_wrap = tk.Frame(self.settings_view, bg=COLORS["bg"])
        canvas_wrap.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        canvas = tk.Canvas(canvas_wrap, bg=COLORS["bg"], highlightthickness=0)
        scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=COLORS["bg"])
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        def _wheel_settings(event):
            if getattr(event, "delta", 0):
                canvas.yview_scroll(int(-event.delta / 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel_settings))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        variables = {}
        if active_tab == "settings":
            values = self.get_launcher_settings()
            rows = [
                ("check_updates_on_start", "Проверять обновления при запуске", "Автоматически проверять включённые каналы при старте.", "bool"),
                ("confirm_updates", "Подтверждать обновление игры", "Спрашивать перед заменой установленной версии.", "bool"),
                ("close_hub_after_launch", "Закрывать PrimeHub после запуска", "Закрывать окно лаунчера после старта игры.", "bool"),
                ("remember_platform", "Запоминать платформу", "Открывать PC или Android как в прошлый раз.", "bool"),
                ("remember_window_size", "Запоминать размер окна", "Сохранять размер и положение окна.", "bool"),
                ("keep_backups", "Хранить резервную копию игры", "Оставлять предыдущую версию после обновления для отката.", "bool"),
                ("clear_cache_after_install", "Очищать кэш после установки", "Удалять временные архивы после успешной установки.", "bool"),
                ("check_skyrealm_channel", "Проверять канал SkyRealm PC", "Официальный релиз игры и отдельного запускателя.", "bool"),
                ("check_apocalypse_channel", "Проверять канал Apocalypse PC", "Самостоятельный Windows-релиз Apocalypse.", "bool"),
                ("check_android_channel", "Проверять канал Android APK", "Мобильный APK в выбранной вкладке Android.", "bool"),
                ("check_primehub_channel", "Проверять обновления PrimeHub", "Отдельный канал самого лаунчера.", "bool"),
            ]
            tk.Label(body, text="ОБЩИЕ ПАРАМЕТРЫ", font=("Segoe UI", 9, "bold"), fg=COLORS["cyan"], bg=COLORS["bg"]).pack(anchor="w", pady=(4, 8))
            for key, label, description, kind in rows:
                card = tk.Frame(body, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
                card.pack(fill="x", pady=5)
                copy = tk.Frame(card, bg=COLORS["panel"])
                copy.pack(side="left", fill="x", expand=True, padx=15, pady=12)
                tk.Label(copy, text=label, font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
                tk.Label(copy, text=description, font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", pady=(3, 0))
                var = tk.BooleanVar(value=bool(values.get(key, False)))
                variables[key] = var
                tk.Checkbutton(card, variable=var, text="ВКЛ", onvalue=True, offvalue=False, bg=COLORS["panel"], fg=COLORS["cyan"], selectcolor=COLORS["panel2"], activebackground=COLORS["panel"], activeforeground=COLORS["text"], font=("Segoe UI", 9, "bold")).pack(side="right", padx=18)

            tk.Label(body, text="СКОРОСТЬ ЗАГРУЗКИ", font=("Segoe UI", 9, "bold"), fg=COLORS["cyan"], bg=COLORS["bg"]).pack(anchor="w", pady=(18, 8))
            speed_card = tk.Frame(body, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
            speed_card.pack(fill="x", pady=5)
            speed_copy = tk.Frame(speed_card, bg=COLORS["panel"])
            speed_copy.pack(side="left", fill="x", expand=True, padx=15, pady=12)
            tk.Label(speed_copy, text="Ограничение скорости", font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
            tk.Label(speed_copy, text="Лимит действует на загрузку игр, APK и обновлений PrimeHub.", font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", pady=(3, 0))
            unlimited_var = tk.BooleanVar(value=bool(values.get("download_unlimited", True)))
            variables["download_unlimited"] = unlimited_var
            tk.Checkbutton(speed_copy, variable=unlimited_var, text="Без ограничений", onvalue=True, offvalue=False, bg=COLORS["panel"], fg=COLORS["green"], selectcolor=COLORS["panel2"], activebackground=COLORS["panel"], activeforeground=COLORS["text"], font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(9, 0))
            speed_controls = tk.Frame(speed_card, bg=COLORS["panel"])
            speed_controls.pack(side="right", padx=18, pady=12)
            tk.Label(speed_controls, text="Лимит, МБ/с", font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w")
            speed_var = tk.StringVar(value=str(values.get("download_limit_mbps", 2.0)))
            variables["download_limit_mbps"] = speed_var
            speed_entry = tk.Entry(speed_controls, textvariable=speed_var, width=10, bg=COLORS["panel2"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Segoe UI", 10))
            speed_entry.pack(anchor="e", pady=(4, 0), ipady=5)
            tk.Label(speed_controls, text="Примеры: 0.5 • 1 • 2 • 5 • 10", font=("Segoe UI", 7), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="e", pady=(4, 0))
            tk.Label(body, text="СЕТЬ И ПОВТОРНЫЕ ПОПЫТКИ", font=("Segoe UI", 9, "bold"), fg=COLORS["cyan"], bg=COLORS["bg"]).pack(anchor="w", pady=(18, 8))
            for key, label, description, options in [
                ("network_retries", "Повторять неудачные запросы", "Повтор при тайм-ауте, ограничении GitHub 429 и временных ошибках сервера.", ["0", "1", "2", "3", "4"]),
                ("network_timeout_seconds", "Тайм-аут сети", "Время ожидания ответа GitHub перед повтором.", ["10", "20", "35", "60", "90", "120"]),
            ]:
                card = tk.Frame(body, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
                card.pack(fill="x", pady=5)
                copy = tk.Frame(card, bg=COLORS["panel"])
                copy.pack(side="left", fill="x", expand=True, padx=15, pady=11)
                tk.Label(copy, text=label, font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
                tk.Label(copy, text=description, font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"], wraplength=500, justify="left").pack(anchor="w", pady=(3, 0))
                variable = tk.StringVar(value=str(values.get(key, 2 if key == "network_retries" else 35)))
                variables[key] = variable
                ttk.Combobox(card, values=options, state="readonly", width=10, textvariable=variable).pack(side="right", padx=16, pady=12)
            tk.Label(body, text="Подробные версии, время последней проверки и полный текст ошибки каждого источника доступны в разделе «Каналы и диагностика».", wraplength=760, justify="left", font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["bg"]).pack(anchor="w", pady=(12, 0))
        else:
            values = self.get_apocalypse_settings()
            self._settings_form_values = {}
            tk.Label(body, text="ГРАФИКА И ПОГОДА", font=("Segoe UI", 9, "bold"), fg=COLORS["cyan"], bg=COLORS["bg"]).pack(anchor="w", pady=(4, 8))
            choices = {
                "effects": ("Качество эффектов", "Количество частиц, дым и атмосферные эффекты.", [("Высокое", "high"), ("Сбалансированное", "balanced"), ("Минимум частиц", "low")]),
                "infectedCap": ("Лимит заражённых", "Максимум активных заражённых одновременно.", [("8", "8"), ("12", "12"), ("18", "18"), ("24", "24")]),
                "eventFrequency": ("Частота событий", "Насколько часто появляются патрули и тревоги.", [("Редко", "0.5"), ("Обычная", "1"), ("Часто", "1.5")]),
                "autosaveSeconds": ("Автосохранение", "Как часто сохраняется игровой мир.", [("5 секунд", "5"), ("10 секунд", "10"), ("15 секунд", "15"), ("30 секунд", "30")]),
                "joy": ("Размер джойстика", "Масштаб сенсорного джойстика на мобильной версии.", [("85%", "85"), ("100%", "100"), ("115%", "115"), ("135%", "135")]),
                "survivalDifficulty": ("Сложность выживания", "Влияет на заражение и переохлаждение.", [("Облегчённая", "easy"), ("Стандартная", "standard"), ("Суровая", "hard")]),
                "renderDistance": ("Дальность прорисовки", "Управляет количеством видимых дальних объектов без ухудшения текстур.", [("Ближе", "near"), ("Стандартная", "normal"), ("Дальняя", "far")]),
            }
            for key, (label, description, options) in choices.items():
                card = tk.Frame(body, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
                card.pack(fill="x", pady=5)
                copy = tk.Frame(card, bg=COLORS["panel"])
                copy.pack(side="left", fill="x", expand=True, padx=15, pady=11)
                tk.Label(copy, text=label, font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
                tk.Label(copy, text=description, font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", pady=(3, 0))
                variable = tk.StringVar(value=str(values.get(key, "")))
                variables[key] = variable
                combo = ttk.Combobox(card, values=[v for _, v in options], state="readonly", width=15)
                combo.set(variable.get())
                combo.pack(side="right", padx=16, pady=12)
                combo.bind("<<ComboboxSelected>>", lambda _e, k=key, c=combo: variables[k].set(c.get()))
            tk.Label(body, text="ИГРОВОЙ ПРОЦЕСС", font=("Segoe UI", 9, "bold"), fg=COLORS["cyan"], bg=COLORS["bg"]).pack(anchor="w", pady=(18, 8))
            for key, label, description in [
                ("weather", "Погодные эффекты", "Дождь, гроза, туман и пыльные бури."),
                ("ambientAudio", "Звуки окружения", "Отдалённые выстрелы и сигналы выживших."),
                ("autoSprint", "Автоматический бег", "Бежать при движении, пока хватает выносливости."),
                ("showHydration", "Индикатор жажды", "Показывать уровень чистой воды в игровом HUD."),
                ("showEnemyHealth", "Полосы здоровья заражённых", "Показывать оставшееся здоровье противника."),
                ("showSurvivalHud", "Индикаторы выживания", "Показывать инфекцию и температуру тела."),
                ("motion", "Плавные переходы", "Анимации интерфейса и переходов."),
                ("hints", "Подсказки управления", "Показывать подсказки управления в игре."),
            ]:
                card = tk.Frame(body, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
                card.pack(fill="x", pady=5)
                copy = tk.Frame(card, bg=COLORS["panel"])
                copy.pack(side="left", fill="x", expand=True, padx=15, pady=11)
                tk.Label(copy, text=label, font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
                tk.Label(copy, text=description, font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", pady=(3, 0))
                var = tk.BooleanVar(value=bool(values.get(key, True)))
                variables[key] = var
                tk.Checkbutton(card, variable=var, text="ВКЛ", onvalue=True, offvalue=False, bg=COLORS["panel"], fg=COLORS["cyan"], selectcolor=COLORS["panel2"], activebackground=COLORS["panel"], activeforeground=COLORS["text"], font=("Segoe UI", 9, "bold")).pack(side="right", padx=18)

        actions = tk.Frame(self.settings_view, bg=COLORS["bg"])
        actions.pack(fill="x", padx=28, pady=(5, 18))
        status = tk.Label(actions, text="Параметры ещё не сохранены.", font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["bg"])
        status.pack(side="left")

        def save_page():
            try:
                if active_tab == "settings":
                    settings = self.get_launcher_settings()
                    boolean_keys = ("check_updates_on_start", "confirm_updates", "close_hub_after_launch", "remember_platform", "download_unlimited", "remember_window_size", "keep_backups", "clear_cache_after_install", "check_skyrealm_channel", "check_apocalypse_channel", "check_android_channel", "check_primehub_channel")
                    settings.update({k: bool(variables[k].get()) for k in boolean_keys if k in variables})
                    try:
                        limit = float(variables["download_limit_mbps"].get().replace(",", "."))
                        retries = int(variables["network_retries"].get())
                        timeout = int(variables["network_timeout_seconds"].get())
                    except (ValueError, AttributeError):
                        raise ValueError("Проверь скорость загрузки, число повторов и тайм-аут.")
                    if not 0.05 <= limit <= 1000:
                        raise ValueError("Допустимый лимит: от 0.05 до 1000 МБ/с.")
                    if retries not in range(5) or timeout not in (10, 20, 35, 60, 90, 120):
                        raise ValueError("Выбери допустимое значение повторов и тайм-аута.")
                    settings.update({"download_limit_mbps": limit, "network_retries": retries, "network_timeout_seconds": timeout})
                    self.state["primehub_settings"] = settings
                    self.save_state()
                else:
                    defaults = self.get_apocalypse_settings()
                    for key, var in variables.items():
                        raw = var.get()
                        if key in ("joy", "infectedCap", "autosaveSeconds"):
                            defaults[key] = int(raw)
                        elif key == "eventFrequency":
                            defaults[key] = float(raw)
                        else:
                            defaults[key] = raw
                    self._settings_form_values = defaults
                    self.state["apocalypse_settings"] = dict(defaults)
                    ROOT.mkdir(parents=True, exist_ok=True)
                    temp = APOCALYPSE_CONFIG.with_suffix(".tmp")
                    temp.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
                    os.replace(temp, APOCALYPSE_CONFIG)
                    self.save_state()
                status.configure(text="Сохранено. Новые значения применятся при следующем запуске Apocalypse.", fg=COLORS["green"])
            except Exception as exc:
                status.configure(text="Не удалось сохранить: " + str(exc), fg=COLORS["orange"])

        def reset_page():
            if active_tab == "settings":
                self.state["primehub_settings"] = {
                    "check_updates_on_start": True, "confirm_updates": True,
                    "close_hub_after_launch": False, "remember_platform": True,
                    "download_unlimited": True, "download_limit_mbps": 2.0,
                    "check_skyrealm_channel": True, "check_apocalypse_channel": True,
                    "check_android_channel": True, "check_primehub_channel": True,
                    "network_retries": 2, "network_timeout_seconds": 35,
                    "keep_backups": True, "clear_cache_after_install": False,
                    "remember_window_size": True, "window_geometry": "1120x740",
                }
            else:
                self.state["apocalypse_settings"] = {
                    "effects": "high", "joy": 100, "motion": True, "hints": True,
                    "weather": True, "ambientAudio": True, "infectedCap": 18,
                    "eventFrequency": 1.0, "autosaveSeconds": 5,
                    "autoSprint": False, "showHydration": True, "survivalDifficulty": "standard", "renderDistance": "normal", "showEnemyHealth": True, "showSurvivalHud": True,
                }
                settings = self.state["apocalypse_settings"]
                APOCALYPSE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
                APOCALYPSE_CONFIG.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            self.save_state()
            self._render_settings(active_tab)

        save_btn = tk.Button(actions, text="СОХРАНИТЬ", command=save_page, bg=COLORS["blue"], fg="white", activebackground=COLORS["cyan"], activeforeground="#07101d", bd=0, padx=17, pady=10, font=("Segoe UI", 9, "bold"), cursor="hand2")
        save_btn.pack(side="right", padx=(8, 0))
        reset_btn = tk.Button(actions, text="СБРОСИТЬ", command=reset_page, bg=COLORS["panel2"], fg=COLORS["text"], activebackground=COLORS["line"], activeforeground=COLORS["text"], bd=0, padx=15, pady=10, font=("Segoe UI", 9, "bold"), cursor="hand2")
        reset_btn.pack(side="right")

    def _record_channel_status(self, key, ok, message, version=""):
        self.channel_status[key] = {"ok": bool(ok), "message": str(message)[:1200], "version": str(version or ""), "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.state["channel_status"] = self.channel_status

    def _refresh_channels_if_open(self):
        try:
            if self.channels_view and self.channels_view.winfo_exists():
                self._render_channels()
        except tk.TclError:
            pass

    def _render_channels(self):
        self.home_view.pack_forget()
        if self.settings_view and self.settings_view.winfo_exists():
            self.settings_view.pack_forget()
        if self.channels_view and self.channels_view.winfo_exists():
            self.channels_view.destroy()
        self.channels_view = tk.Frame(self.content, bg=COLORS["bg"])
        self.channels_view.pack(fill="both", expand=True)
        self._nav_style("channels")
        tk.Label(self.channels_view, text="КАНАЛЫ И ДИАГНОСТИКА", font=("Segoe UI", 20, "bold"), fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w", padx=28, pady=(24, 4))
        tk.Label(self.channels_view, text="Отдельное состояние каждого источника, версия, время последней проверки и полный текст ошибки.", font=("Segoe UI", 9), fg=COLORS["muted"], bg=COLORS["bg"], wraplength=800, justify="left").pack(anchor="w", padx=28, pady=(0, 15))
        wrap = tk.Frame(self.channels_view, bg=COLORS["bg"])
        wrap.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        canvas = tk.Canvas(wrap, bg=COLORS["bg"], highlightthickness=0)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=COLORS["bg"])
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        settings = self.get_launcher_settings()
        channels = [("skyrealm","SkyRealm PC","check_skyrealm_channel"),("apocalypse_pc","Apocalypse PC","check_apocalypse_channel"),("android","Android APK","check_android_channel"),("primehub","PrimeHub","check_primehub_channel")]
        for index, (key, title, setting_key) in enumerate(channels):
            item = self.channel_status.get(key, {})
            enabled = settings.get(setting_key, True)
            ok = item.get("ok")
            label = "ОТКЛЮЧЁН" if not enabled else ("ДОСТУПЕН" if ok else ("ОШИБКА" if item.get("checked_at") else "НЕ ПРОВЕРЯЛСЯ"))
            color = COLORS["muted"] if not enabled or not item.get("checked_at") else (COLORS["green"] if ok else COLORS["orange"])
            card = tk.Frame(body, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
            card.grid(row=index//2, column=index%2, sticky="nsew", padx=6, pady=6)
            body.grid_columnconfigure(index%2, weight=1)
            tk.Label(card, text=title, font=("Segoe UI", 12, "bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w", padx=15, pady=(13, 4))
            tk.Label(card, text="● " + label, font=("Segoe UI", 8, "bold"), fg=color, bg=COLORS["panel"]).pack(anchor="w", padx=15)
            tk.Label(card, text=item.get("version") or "Версия пока не получена", font=("Segoe UI", 9, "bold"), fg=COLORS["cyan"], bg=COLORS["panel"]).pack(anchor="w", padx=15, pady=(5, 0))
            tk.Label(card, text=item.get("message") or "Нажми «Проверить каналы».", font=("Segoe UI", 8), fg=COLORS["muted"], bg=COLORS["panel"], wraplength=350, justify="left").pack(anchor="w", padx=15, pady=(4, 3))
            tk.Label(card, text="Последняя проверка: " + (item.get("checked_at") or "—"), font=("Segoe UI", 7), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", padx=15, pady=(2, 13))
        actions = tk.Frame(self.channels_view, bg=COLORS["bg"])
        actions.pack(fill="x", padx=28, pady=(4, 16))
        for label, command, color in [("ПРОВЕРИТЬ КАНАЛЫ",self.check_updates_async,COLORS["blue"]),("ЖУРНАЛ",self.open_update_log,COLORS["panel2"]),("ПАПКА ИГР",self.open_games_folder,COLORS["panel2"]),("ОЧИСТИТЬ КЭШ",self.clear_download_cache,COLORS["panel2"]),("ОТКАТ APOCALYPSE",self.restore_apocalypse_backup,"#68404a")]:
            tk.Button(actions, text=label, command=command, bg=color, fg="white", activebackground=COLORS["cyan"], activeforeground="#07101d", bd=0, padx=10, pady=9, font=("Segoe UI", 8, "bold"), cursor="hand2").pack(side="left", padx=(0, 6))

    def open_update_log(self):
        path = ROOT / "update-check.log"
        if not path.is_file():
            messagebox.showinfo("PrimeHub", "Журнал ещё пуст. Сначала проверь каналы.", parent=self.root)
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("PrimeHub", "Не удалось открыть журнал: " + str(exc), parent=self.root)

    def open_games_folder(self):
        GAMES.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(GAMES))
        except Exception as exc:
            messagebox.showerror("PrimeHub", "Не удалось открыть папку игр: " + str(exc), parent=self.root)

    def clear_download_cache(self):
        if self.busy:
            messagebox.showinfo("PrimeHub", "Дождись завершения текущей загрузки.", parent=self.root)
            return
        cache = ROOT / "cache"
        if not cache.exists():
            messagebox.showinfo("PrimeHub", "Кэш уже пуст.", parent=self.root)
            return
        if not messagebox.askyesno("Очистка кэша", "Удалить только временные архивы? Игры, миры, настройки и резервные копии не затрагиваются.", parent=self.root):
            return
        try:
            shutil.rmtree(cache)
            messagebox.showinfo("PrimeHub", "Временный кэш очищен.", parent=self.root)
        except OSError as exc:
            messagebox.showerror("PrimeHub", "Не удалось очистить кэш: " + str(exc), parent=self.root)

    def restore_apocalypse_backup(self):
        if self.busy:
            messagebox.showinfo("PrimeHub", "Дождись завершения текущей операции.", parent=self.root)
            return
        backup = ROOT / "backups" / "Apocalypse.previous"
        dest = self.installed_dir("Apocalypse")
        if not backup.is_dir() or not (backup / "SkyRealmApocalypse.exe").is_file():
            messagebox.showinfo("Откат Apocalypse", "Резервная копия не найдена. Включи её хранение перед следующим обновлением.", parent=self.root)
            return
        if not messagebox.askyesno("Откат Apocalypse", "Вернуть предыдущую версию? Текущая версия станет резервной копией.", parent=self.root):
            return
        temp = ROOT / "staging" / "Apocalypse-current"
        try:
            temp.parent.mkdir(parents=True, exist_ok=True)
            if temp.exists():
                shutil.rmtree(temp)
            if dest.exists():
                dest.rename(temp)
            try:
                backup.rename(dest)
            except Exception:
                if temp.exists() and not dest.exists():
                    temp.rename(dest)
                raise
            if temp.exists():
                temp.rename(backup)
            edition_path = dest / "edition.json"
            edition = json.loads(edition_path.read_text(encoding="utf-8")) if edition_path.is_file() else {}
            self.state["Apocalypse"] = {"version": edition.get("version", "backup"), "game_version": "mobile-apocalypse", "edition": "apocalypse-mobile", "installed": int(time.time())}
            self.save_state()
            self.set_status("Apocalypse восстановлена из резервной копии", COLORS["green"])
            self.refresh_cards()
            self._refresh_channels_if_open()
        except Exception as exc:
            messagebox.showerror("Откат Apocalypse", "Не удалось восстановить копию: " + str(exc), parent=self.root)

    def set_platform(self, platform):
        self.platform = platform
        for b,p in ((self.pc_btn,"PC"),(self.android_btn,"Android")):
            active = p == platform
            b.configure(bg=COLORS["blue"] if active else COLORS["panel"], fg="white" if active else COLORS["muted"])
        if self.get_launcher_settings().get("remember_platform", True):
            self.state["last_platform"] = platform
            try:
                self.save_state()
            except OSError:
                pass
        self.refresh_cards()


    def installed_dir(self, game):
        return GAMES / game

    def needs_update(self, game, tag):
        if not self.is_installed(game) or not tag:
            return False
        installed = self.state.get(game, {})
        if installed.get("version") != tag:
            return True
        # The old Hub trusted only the saved release tag. If a stale or partial EXE
        # was recorded under the current tag, the card incorrectly showed Launch.
        # Compare the actual Apocalypse binary against GitHub's published SHA-256.
        if game == "Apocalypse":
            exe = self.installed_dir("Apocalypse") / "SkyRealmApocalypse.exe"
            if not exe.is_file():
                return True
            release = self.releases.get("apocalypse_pc") or {}
            asset = self.find_asset(release, "SkyRealmApocalypse.exe")
            if asset:
                digest = str(asset.get("digest") or "").lower()
                if digest.startswith("sha256:"):
                    digest = digest.split(":", 1)[1]
                    actual = hashlib.sha256()
                    with exe.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            actual.update(chunk)
                    return actual.hexdigest().lower() != digest
                try:
                    expected_size = int(asset.get("size") or 0)
                    if expected_size:
                        return exe.stat().st_size != expected_size
                except (TypeError, ValueError, OSError):
                    pass
        return False

    def is_installed(self, game):
        p = self.installed_dir(game)
        if game == "SkyRealm":
            return (p / "game" / "index.html").is_file() and (p / "runtime" / "SkyRealmGame.exe").is_file()
        if game == "Apocalypse":
            exe = p / "SkyRealmApocalypse.exe"
            return exe.is_file() and exe.stat().st_size >= 1_000_000
        if game == "PrimeLauncher":
            return (p / "PrimeLauncher.exe").exists()
        if game == "PrimeLauncher Mobile":
            return (p / "SkyRealm-Hub.apk").exists() or (p / "PrimeLauncher-Mobile.apk").exists()
        return False

    def card(self, parent, title, subtitle, version, description, accent, button_text, action, installed=False, available=True):
        box = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        box.pack(side="left", fill="both", expand=True, padx=(0,14))
        art = tk.Frame(box, bg=accent, height=142)
        art.pack(fill="x")
        art.pack_propagate(False)
        tk.Label(art, text=title.upper(), font=("Segoe UI",21,"bold"), fg="white", bg=accent).place(relx=.08, rely=.32, anchor="w")
        tk.Label(art, text=subtitle, font=("Segoe UI",9,"bold"), fg="#ffffff", bg=accent).place(relx=.08, rely=.60, anchor="w")
        body = tk.Frame(box, bg=COLORS["panel"])
        body.pack(fill="both", expand=True, padx=17, pady=15)
        tk.Label(body, text=version, font=("Segoe UI",9,"bold"), fg=COLORS["cyan"], bg=COLORS["panel"]).pack(anchor="w")
        tk.Label(body, text=description, justify="left", wraplength=300, font=("Segoe UI",9), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", pady=(7,14))
        label = ("УСТАНОВЛЕНО" if installed else "ДОСТУПНО ДЛЯ УСТАНОВКИ") if available else "ПОКА НЕДОСТУПНО"
        tk.Label(body, text="● "+label, font=("Segoe UI",8,"bold"), fg=COLORS["green"] if installed else (COLORS["orange"] if available else COLORS["muted"]), bg=COLORS["panel"]).pack(anchor="w", pady=(0,10))
        btn = tk.Button(body, text=button_text, command=action if available else None, state="normal" if available else "disabled", bg=COLORS["blue"] if available else COLORS["panel2"], fg="white" if available else COLORS["muted"], activebackground=COLORS["cyan"], activeforeground="#07101d", disabledforeground=COLORS["muted"], bd=0, font=("Segoe UI",9,"bold"), padx=15, pady=10, cursor="hand2" if available else "arrow")
        btn.pack(fill="x", side="bottom")
        return box

    def refresh_cards(self):
        for w in self.cards.winfo_children(): w.destroy()
        if self.platform == "PC":
            self.count_label.configure(text="3 игры")
            sky_tag=str((self.releases.get("sky") or {}).get("tag_name") or "").strip()
            sky_installed=self.is_installed("SkyRealm")
            sky_installed_tag=str((self.state.get("SkyRealm") or {}).get("version") or "неизвестно").strip()
            # Prominent update banner is reserved for Apocalypse. SkyRealm updates stay on its own card.
            sky_update=bool(sky_installed and sky_tag and sky_installed_tag.lower() != sky_tag.lower())
            self.update_banner.pack_forget()
            sky_version_label=("ДОСТУПНО ОБНОВЛЕНИЕ: " + str(sky_tag) + " • УСТАНОВЛЕНО: " + sky_installed_tag) if sky_update else ("PC • " + str(sky_tag or "Windows"))
            self.card(self.cards,"SkyRealm","OPEN WORLD • ADVENTURE", sky_version_label, "Обычный открытый мир SkyRealm. Устанавливается отдельно от Apocalypse.", "#285f83", ("ОБНОВИТЬ ДО " + str(sky_tag)) if sky_update else ("ЗАПУСТИТЬ" if sky_installed else "УСТАНОВИТЬ"), (lambda:self.install_game("SkyRealm")) if sky_update or not sky_installed else (lambda:self.launch_game("SkyRealm")), sky_installed)
            prime_update=self.needs_update("PrimeLauncher",sky_tag)
            prime_installed=self.is_installed("PrimeLauncher")
            self.card(self.cards,"PrimeLauncher","ONLINE • ARENA", "PC • Windows", "Отдельная соревновательная игра PrimeLauncher.", "#59428f", "ОБНОВИТЬ" if prime_update else ("ЗАПУСТИТЬ" if prime_installed else "УСТАНОВИТЬ"), (lambda:self.install_game("PrimeLauncher")) if prime_update or not prime_installed else (lambda:self.launch_game("PrimeLauncher")), prime_installed)
            apoc_tag=self.releases.get("apocalypse_pc",{}).get("tag_name") or APOCALYPSE_PC_VERSION
            apoc_update=self.needs_update("Apocalypse",apoc_tag)
            apoc_installed=self.is_installed("Apocalypse")
            if apoc_update:
                installed_apoc_tag=str((self.state.get("Apocalypse") or {}).get("version") or "неизвестно")
                self.update_banner_label.configure(text="ДОСТУПНО ОБНОВЛЕНИЕ APOCALYPSE  |  " + installed_apoc_tag + "  →  " + str(apoc_tag) + "   •   Текущая версия сохранится до успешной проверки новой.")
                self.update_banner_button.configure(text="ОБНОВИТЬ APOCALYPSE", command=lambda:self.install_game("Apocalypse"))
                if not self.update_banner.winfo_manager():
                    self.update_banner.pack(fill="x")
            else:
                self.update_banner.pack_forget()
            self.card(self.cards,"Apocalypse","SURVIVAL • LAST STAND", "Windows • " + apoc_tag, "Отдельная Windows-сборка Apocalypse. Обновляется только из канала Apocalypse; обычный SkyRealm не затрагивается.", "#873f49", "ОБНОВИТЬ" if apoc_update else ("ЗАПУСТИТЬ" if apoc_installed else "УСТАНОВИТЬ"), (lambda:self.install_game("Apocalypse")) if apoc_update or not apoc_installed else (lambda:self.launch_apocalypse()), apoc_installed)
        else:
            self.count_label.configure(text="1 игра")
            mobile_tag=self.releases.get("mobile",{}).get("tag_name")
            mobile_update=self.needs_update("PrimeLauncher Mobile",mobile_tag)
            mobile_installed=self.is_installed("PrimeLauncher Mobile")
            self.card(self.cards,"SkyRealm Hub","MOBILE • ACCOUNT", "Android • APK", "Мобильный Hub SkyRealm. APK скачивается из официального репозитория и сохраняется в папке PrimeHub.", "#59428f", "ОБНОВИТЬ APK" if mobile_update else ("СКАЧАТЬ APK" if not mobile_installed else "APK УСТАНОВЛЕН"), lambda:self.install_game("PrimeLauncher Mobile"), mobile_installed)
            note = tk.Frame(self.cards, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
            note.pack(side="left", fill="both", expand=True)
            tk.Label(note, text="SKYREALM", font=("Segoe UI",19,"bold"), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", padx=18, pady=(22,8))
            tk.Label(note, text="Android-версия пока не опубликована. Как только появится официальный APK, она автоматически появится здесь.", wraplength=290, justify="left", font=("Segoe UI",9), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", padx=18)
        self.root.update_idletasks()

    def set_status(self, msg, color=None):
        def apply():
            try:
                if self.root.winfo_exists() and hasattr(self, "status") and self.status.winfo_exists():
                    self.status.configure(text="● " + str(msg), fg=color or COLORS["cyan"])
            except tk.TclError:
                pass
        try:
            self.root.after(0, apply)
        except (tk.TclError, RuntimeError):
            pass
    def set_progress(self, value, msg):
        def apply():
            try:
                if self.root.winfo_exists() and hasattr(self, "progress"):
                    self.progress["value"] = max(0, min(100, int(value)))
                    self.progress_text.configure(text=str(msg))
            except tk.TclError:
                pass
        try:
            self.root.after(0, apply)
        except (tk.TclError, RuntimeError):
            pass
    def _read_response(self, request, timeout=None):
        """Retry temporary network and GitHub rate-limit errors with bounded backoff."""
        settings = self.get_launcher_settings()
        timeout = int(timeout or settings.get("network_timeout_seconds", 35))
        retries = int(settings.get("network_retries", 2))
        last_error = None
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read(), response.geturl()
            except urllib.error.HTTPError as exc:
                last_error = exc
                remaining = (exc.headers or {}).get("X-RateLimit-Remaining", "")
                retryable = exc.code in (408, 425, 429, 500, 502, 503, 504) or (exc.code == 403 and remaining == "0")
                if not retryable or attempt >= retries:
                    raise
                retry_after = (exc.headers or {}).get("Retry-After", "")
                try:
                    delay = max(0.5, min(8.0, float(retry_after)))
                except (TypeError, ValueError):
                    delay = min(4.0, 0.75 * (2 ** attempt))
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt >= retries:
                    raise
                delay = min(4.0, 0.75 * (2 ** attempt))
            self.set_status("Повтор соединения с GitHub: " + str(attempt + 1) + "/" + str(retries))
            time.sleep(delay)
        raise RuntimeError("Сетевой запрос не выполнен: " + str(last_error))

    def fetch_json(self, url):
        """Read GitHub release metadata through REST; tolerate temporary HTML and API failures."""
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc.lower() == "github.com" and "/releases/" in parsed.path:
            repo_path = parsed.path.split("/releases/", 1)[0]
            requested_tag = re.search(r"/releases/tag/([^/?#]+)", parsed.path)
            html_error = None
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PrimeHub/1.3"})
                _, final_url = self._read_response(req)
                final_path = urllib.parse.urlsplit(final_url).path
                tag_match = re.search(r"/releases/tag/([^/?#]+)", final_path)
                if tag_match:
                    tag = urllib.parse.unquote(tag_match.group(1))
                elif requested_tag:
                    tag = urllib.parse.unquote(requested_tag.group(1))
                else:
                    raise RuntimeError("GitHub не вернул номер последнего релиза.")
                assets_url = "https://github.com" + repo_path + "/releases/expanded_assets/" + urllib.parse.quote(tag, safe="")
                assets_req = urllib.request.Request(assets_url, headers={"User-Agent": "Mozilla/5.0 PrimeHub/1.3"})
                assets_bytes, _ = self._read_response(assets_req)
                assets_page = assets_bytes.decode("utf-8", errors="replace")
                assets, seen = [], set()
                for match in re.finditer(r"""href=["']([^"']*/releases/download/[^"']+)["']""", assets_page, re.I):
                    asset_url = urllib.parse.urljoin("https://github.com", html.unescape(match.group(1)))
                    name = urllib.parse.unquote(urllib.parse.urlsplit(asset_url).path.rsplit("/", 1)[-1])
                    if name and name not in seen:
                        seen.add(name)
                        assets.append({"name": name, "browser_download_url": asset_url})
                if assets:
                    return {"tag_name": tag, "html_url": final_url, "assets": assets}
                html_error = RuntimeError("Страница релиза GitHub не вернула список файлов.")
            except Exception as exc:
                html_error = exc
            api_base = "https://api.github.com/repos" + repo_path
            api_url = api_base + ("/releases/tags/" + urllib.parse.quote(urllib.parse.unquote(requested_tag.group(1)), safe="") if requested_tag else "/releases/latest")
            try:
                req = urllib.request.Request(api_url, headers=HEADERS)
                raw, _ = self._read_response(req)
                release = json.loads(raw.decode("utf-8"))
                if not isinstance(release, dict) or not release.get("tag_name"):
                    raise RuntimeError("GitHub API не вернул номер версии.")
                return release
            except Exception as api_error:
                raise RuntimeError("Не удалось получить релиз GitHub. Страница: " + str(html_error) + "; API: " + str(api_error)) from api_error
        req = urllib.request.Request(url, headers=HEADERS)
        raw, _ = self._read_response(req)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("GitHub вернул некорректный JSON для канала: " + str(exc)) from exc
    def fetch_latest_mobile_release(self):
        """Resolve a published Android APK release, validating the actual asset."""
        errors = []
        for url in (API_PRIME_MOBILE, "https://github.com/kisia319-cell/SkyRealm-Hub-Mobile/releases/latest"):
            try:
                release = self.fetch_json(url)
                if not isinstance(release, dict) or not release.get("tag_name"):
                    raise RuntimeError("GitHub не вернул тег Android-релиза.")
                asset = self.find_asset(release, "app-debug.apk") or self.find_asset(release, "PrimeHub-Mobile.apk")
                if not asset or not asset.get("browser_download_url"):
                    raise RuntimeError("В Android-релизе отсутствует скачиваемый APK.")
                return release
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("Не удалось проверить Android-релиз: " + " | ".join(errors))
    def fetch_latest_apocalypse_release(self):
        """Find the newest non-draft Windows Apocalypse release with a real EXE asset."""
        api_error, releases = None, []
        for page in range(1, 4):
            try:
                batch = self.fetch_json(API_APOCALYPSE_PC + "&page=" + str(page))
                if not isinstance(batch, list):
                    raise RuntimeError("GitHub вернул не список релизов Apocalypse.")
                releases.extend(item for item in batch if isinstance(item, dict))
                if len(batch) < 100:
                    break
            except Exception as exc:
                api_error = exc
                break
        matching = [
            item for item in releases
            if str(item.get("tag_name", "")).startswith("apocalypse-pc-v")
            and not item.get("draft", False)
            and any(str(asset.get("name", "")).lower() == "skyrealmapocalypse.exe" and asset.get("browser_download_url") for asset in (item.get("assets") or []))
        ]
        if matching:
            return max(matching, key=lambda item: _version_key(item.get("tag_name")))
        tags, fallback_errors = set(), []
        try:
            req = urllib.request.Request("https://github.com/kisia319-cell/SkyRealm-Hub-Mobile/releases.atom", headers={"User-Agent": "Mozilla/5.0 PrimeHub/1.3", "Accept": "application/atom+xml"})
            raw, _ = self._read_response(req)
            tags.update(re.findall(r'(?:https?://github\.com)?/kisia319-cell/SkyRealm-Hub-Mobile/releases/tag/(apocalypse-pc-v[0-9][A-Za-z0-9._-]*)', html.unescape(raw.decode("utf-8", errors="replace")), re.I))
        except Exception as exc:
            fallback_errors.append("Atom: " + str(exc))
        if not tags:
            try:
                req = urllib.request.Request("https://github.com/kisia319-cell/SkyRealm-Hub-Mobile/releases?q=apocalypse-pc", headers={"User-Agent": "Mozilla/5.0 PrimeHub/1.3"})
                raw, _ = self._read_response(req)
                page = html.unescape(raw.decode("utf-8", errors="replace"))
                tags.update(re.findall(r'(?:https?://github\.com)?/kisia319-cell/SkyRealm-Hub-Mobile/releases/tag/(apocalypse-pc-v[0-9][A-Za-z0-9._-]*)', page, re.I))
                tags.update(re.findall(r'SkyRealm-Hub-Mobile/releases/tag/(apocalypse-pc-v[0-9][A-Za-z0-9._-]*)', page, re.I))
            except Exception as exc:
                fallback_errors.append("Страница релизов: " + str(exc))
        for tag in sorted(tags, key=_version_key, reverse=True):
            try:
                release = self.fetch_json("https://api.github.com/repos/kisia319-cell/SkyRealm-Hub-Mobile/releases/tags/" + urllib.parse.quote(tag, safe=""))
                if isinstance(release, dict) and self.find_asset(release, "SkyRealmApocalypse.exe"):
                    return release
            except Exception as exc:
                fallback_errors.append(tag + ": " + str(exc))
        detail = ("API: " + str(api_error) + ". ") if api_error else ""
        detail += " ".join(fallback_errors)
        raise RuntimeError("Не удалось получить опубликованный Windows-релиз Apocalypse с файлом SkyRealmApocalypse.exe. " + detail[:900])
    def check_updates_async(self):
        if self.busy:
            self.set_status("Дождись завершения текущей операции", COLORS["orange"])
            return
        self.busy = True
        threading.Thread(target=self.check_updates, daemon=True).start()
    def check_updates(self):
        self.busy = True
        errors, checked, skipped = [], [], []
        selected_platform = self.platform
        settings = self.get_launcher_settings()
        self.set_status("Проверяем официальные каналы " + selected_platform + "...")
        def run_channel(key, label, enabled, callback):
            if not enabled:
                self._record_channel_status(key, False, "Проверка отключена в настройках.")
                skipped.append(label)
                return None
            try:
                result = callback()
                tag = str(result.get("tag_name") or "") if isinstance(result, dict) else ""
                self._record_channel_status(key, True, "Канал доступен. Опубликованный релиз: " + tag, tag)
                checked.append(label + " " + tag)
                return result
            except Exception as exc:
                self._record_channel_status(key, False, str(exc))
                errors.append(label + ": " + str(exc))
                return None
        try:
            if selected_platform == "PC":
                def get_sky_release():
                    release = self.fetch_json(API_SKY)
                    if not isinstance(release, dict) or not release.get("tag_name"):
                        raise RuntimeError("GitHub не вернул тег релиза SkyRealm.")
                    missing = [name for name in ("SkyRealm_Game.zip", "SkyRealm_Windows.zip", "PrimeLauncher.exe") if not self.find_asset(release, name)]
                    if missing:
                        raise RuntimeError("В релизе " + str(release["tag_name"]) + " отсутствуют файлы: " + ", ".join(missing))
                    return release
                sky = run_channel("skyrealm", "SkyRealm PC", settings.get("check_skyrealm_channel", True), get_sky_release)
                self.releases["sky"] = sky or {}
                apocalypse = run_channel("apocalypse_pc", "Apocalypse PC", settings.get("check_apocalypse_channel", True), self.fetch_latest_apocalypse_release)
                if apocalypse and self.find_asset(apocalypse, "SkyRealmApocalypse.exe"):
                    self.releases["apocalypse_pc"] = apocalypse
                else:
                    if apocalypse:
                        errors.append("Apocalypse PC: в релизе отсутствует SkyRealmApocalypse.exe.")
                        self._record_channel_status("apocalypse_pc", False, "В релизе отсутствует SkyRealmApocalypse.exe.")
                    self.releases["apocalypse_pc"] = {"tag_name": str((self.state.get("Apocalypse") or {}).get("version") or APOCALYPSE_PC_VERSION), "assets": []}
            elif selected_platform == "Android":
                mobile = run_channel("android", "Android APK", settings.get("check_android_channel", True), self.fetch_latest_mobile_release)
                self.releases["mobile"] = mobile or {}
            else:
                errors.append("Неизвестная платформа: " + str(selected_platform))

            def get_hub_release():
                release = self.fetch_json(API_HUB)
                if not isinstance(release, dict) or not release.get("tag_name"):
                    raise RuntimeError("GitHub не вернул номер версии PrimeHub.")
                asset = self.find_asset(release, "PrimeHub.exe")
                if not asset or not asset.get("browser_download_url"):
                    raise RuntimeError("В последнем релизе отсутствует скачиваемый PrimeHub.exe.")
                return release
            hub = run_channel("primehub", "PrimeHub", settings.get("check_primehub_channel", True), get_hub_release)
            if hub:
                hub_tag = str(hub.get("tag_name") or "")
                if _version_key(hub_tag) > _version_key(APP_VERSION):
                    try:
                        self.check_hub_update(hub)
                    except Exception as exc:
                        errors.append("Обновление PrimeHub: " + str(exc))
                        self._record_channel_status("primehub", True, "Релиз доступен (" + hub_tag + "), но загрузка обновления не завершилась: " + str(exc), hub_tag)
                elif _version_key(hub_tag) < _version_key(APP_VERSION):
                    self.set_status("Установлена тестовая версия PrimeHub " + APP_VERSION, COLORS["muted"])

            self.state["channel_status"] = self.channel_status
            try:
                self.save_state()
            except OSError as exc:
                errors.append("Сохранение диагностики: " + str(exc))
            try:
                ROOT.mkdir(parents=True, exist_ok=True)
                with (ROOT / "update-check.log").open("a", encoding="utf-8") as log:
                    log.write(time.strftime("%Y-%m-%d %H:%M:%S") + " platform=" + str(selected_platform) + " checked=" + " | ".join(checked) + " skipped=" + " | ".join(skipped) + " errors=" + " | ".join(errors) + "\n")
            except OSError:
                pass
            try:
                self.root.after(0, self.refresh_cards)
                self.root.after(0, self._refresh_channels_if_open)
            except (tk.TclError, RuntimeError):
                pass
            if errors:
                self.set_status("Проблема в канале: " + errors[0][:180], COLORS["orange"])
                self.set_progress(100, "Проверено: " + (" • ".join(checked) or "нет каналов") + (" | Отключено: " + ", ".join(skipped) if skipped else "") + " | Ошибки: " + " | ".join(errors)[:1200])
            elif checked:
                self.set_status("Проверка обновлений завершена", COLORS["green"])
                self.set_progress(100, "Проверено: " + " • ".join(checked) + (" | Отключено: " + ", ".join(skipped) if skipped else ""))
            else:
                self.set_status("Все каналы отключены в настройках", COLORS["muted"])
                self.set_progress(100, "Включи нужные источники в Настройки → Каналы.")
        except Exception as exc:
            try:
                ROOT.mkdir(parents=True, exist_ok=True)
                with (ROOT / "update-check.log").open("a", encoding="utf-8") as log:
                    log.write(time.strftime("%Y-%m-%d %H:%M:%S") + " FATAL " + repr(exc) + "\n")
            except OSError:
                pass
            self.set_status("Ошибка проверки обновлений: " + str(exc), COLORS["orange"])
            self.set_progress(100, "Проверка прервана: " + str(exc)[:1000])
        finally:
            self.busy = False
    def check_hub_update(self, release):
        if not getattr(sys, "frozen", False):
            return
        # Do not replace an executable with the same release that is already running.
        if str(release.get("tag_name", "")).lower() == APP_VERSION.lower():
            return
        asset = self.find_asset(release, "PrimeHub.exe")
        if not asset:
            return
        stamp = str(asset.get("updated_at") or asset.get("id") or release.get("tag_name"))
        # A previous attempt may have saved this stamp before Windows allowed
        # the replacement script to finish. Never let that stale marker block
        # a retry when the running executable is still an older version.
        current = Path(sys.executable).resolve()
        update_dir = ROOT / "updates"
        staged = update_dir / "PrimeHub.next.exe"
        script = update_dir / "apply-hub-update.cmd"
        self.set_status("Доступно обновление PrimeHub — загружаем...")
        self.download_asset(asset, staged)
        # Refuse to replace the running Hub with a truncated/non-Windows download.
        if not staged.is_file() or staged.stat().st_size < 1_000_000:
            raise RuntimeError("Обновление PrimeHub скачалось не полностью. Старую версию оставили без изменений.")
        with staged.open("rb") as check:
            if check.read(2) != b"MZ":
                raise RuntimeError("Файл обновления PrimeHub повреждён или не является Windows EXE. Старая версия сохранена.")
        staged_size = staged.stat().st_size
        temp_current = current.with_name(current.name + ".new")
        parent_pid = os.getpid()
        backup = current.with_name(current.name + ".previous")
        lines = [
            "@echo off",
            "setlocal",
            "set \"STAGED=" + str(staged) + "\"",
            "set \"CURRENT=" + str(current) + "\"",
            "set \"WORKDIR=" + str(current.parent) + "\" ",
            "set \"TEMPFILE=" + str(temp_current) + "\"",
            "set \"BACKUP=" + str(backup) + "\"",
            "set \"PARENT_PID=" + str(parent_pid) + "\"",
            ":wait_for_hub_exit",
            "powershell -NoProfile -ExecutionPolicy Bypass -Command \"if (Get-Process -Id %PARENT_PID% -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }\"",
            "if not errorlevel 1 goto install_update",
            "timeout /t 1 /nobreak >nul",
            "goto wait_for_hub_exit",
            ":install_update",
            ":retry_copy",
            "copy /b /y \"%STAGED%\" \"%TEMPFILE%\" >nul 2>&1",
            "if errorlevel 1 (timeout /t 1 /nobreak >nul & goto retry_copy)",
            "for %%A in (\"%STAGED%\") do set \"SOURCE_SIZE=%%~zA\"",
            "for %%A in (\"%TEMPFILE%\") do set \"COPY_SIZE=%%~zA\"",
            "if not \"%SOURCE_SIZE%\"==\"%COPY_SIZE%\" (del /q \"%TEMPFILE%\" >nul 2>&1 & timeout /t 1 /nobreak >nul & goto retry_copy)",
            "if exist \"%CURRENT%\" copy /b /y \"%CURRENT%\" \"%BACKUP%\" >nul 2>&1",
            "move /y \"%TEMPFILE%\" \"%CURRENT%\" >nul 2>&1",
            "if errorlevel 1 (timeout /t 1 /nobreak >nul & goto retry_copy)",
            "start \"\" /D \"%WORKDIR%\" \"%CURRENT%\"",
            "timeout /t 2 /nobreak >nul",
            "del /q \"%STAGED%\" >nul 2>&1",
            'del "%~f0"'
        ]
        script.write_text("\r\n".join(lines), encoding="utf-8")
        self.state["hub_asset_stamp"] = stamp
        self.save_state()
        subprocess.Popen(["cmd.exe", "/c", "start", "/min", "", str(script)], creationflags=0x08000000)
        self.root.after(1200, self.root.destroy)

    def find_asset(self, release, name):
        for a in release.get("assets",[]):
            if a.get("name","").lower()==name.lower(): return a
        return None

    def download(self, url, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "PrimeHub/1.3", "Accept": "*/*"})
        settings = self.get_launcher_settings()
        retries = int(settings.get("network_retries", 2))
        timeout = int(settings.get("network_timeout_seconds", 35))
        unlimited = bool(settings.get("download_unlimited", True))
        limit_mbps = float(settings.get("download_limit_mbps", 2.0))
        bytes_per_second = None if unlimited else max(0.05, min(1000.0, limit_mbps)) * 1024 * 1024
        last_error = None
        for attempt in range(retries + 1):
            started, done, total = time.monotonic(), 0, 0
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response, target.open("wb") as out:
                    total = int(response.headers.get("Content-Length", 0) or 0)
                    while True:
                        chunk = response.read(1024 * 512)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if bytes_per_second:
                            expected_elapsed = done / bytes_per_second
                            remaining = expected_elapsed - (time.monotonic() - started)
                            while remaining > 0:
                                time.sleep(min(0.2, remaining))
                                remaining = expected_elapsed - (time.monotonic() - started)
                        pct = int(done * 100 / total) if total else 0
                        mode = "без ограничений" if not bytes_per_second else f"лимит {limit_mbps:g} МБ/с"
                        self.set_progress(pct, f"Загрузка: {target.name} • {done // 1048576} МБ • {mode}")
                    out.flush()
                    os.fsync(out.fileno())
                if total and done != total:
                    raise RuntimeError(f"Загрузка оборвалась: получено {done} из {total} байт.")
                if done == 0:
                    raise RuntimeError("Сервер вернул пустой файл: " + target.name)
                return target
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code in (408, 425, 429, 500, 502, 503, 504)
            except Exception as exc:
                last_error, retryable = exc, True
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            if not retryable or attempt >= retries:
                raise RuntimeError("Не удалось загрузить " + target.name + ": " + str(last_error)) from last_error
            self.set_status("Повтор загрузки " + target.name + " (" + str(attempt + 1) + "/" + str(retries) + ")", COLORS["orange"])
            time.sleep(min(4.0, 0.75 * (2 ** attempt)))
        raise RuntimeError("Загрузка не завершилась: " + str(last_error))

    def download_asset(self, asset, target):
        url = str((asset or {}).get("browser_download_url") or "")
        if not url:
            raise RuntimeError("GitHub не предоставил ссылку на файл " + target.name + ".")
        self.download(url, target)
        expected_size = int((asset or {}).get("size") or 0)
        if expected_size and target.stat().st_size != expected_size:
            target.unlink(missing_ok=True)
            raise RuntimeError("Размер " + target.name + " не совпадает с опубликованным размером GitHub.")
        digest = str((asset or {}).get("digest") or "").lower()
        if digest.startswith("sha256:"):
            actual = hashlib.sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    actual.update(chunk)
            if actual.hexdigest().lower() != digest.split(":", 1)[1]:
                target.unlink(missing_ok=True)
                raise RuntimeError("SHA-256 " + target.name + " не совпадает с контрольной суммой GitHub.")
        return target
    def install_game(self, game):
        if self.busy:
            return
        installed = self.is_installed(game)
        if game == "Apocalypse":
            release_tag = (self.releases.get("apocalypse_pc") or {}).get("tag_name")
        elif game in ("SkyRealm", "PrimeLauncher"):
            release_tag = (self.releases.get("sky") or {}).get("tag_name")
        else:
            release_tag = (self.releases.get("mobile") or {}).get("tag_name")
        updating = installed and self.needs_update(game, release_tag)
        if updating and self.get_launcher_settings().get("confirm_updates", True):
            accepted = messagebox.askyesno(
                "Подтверждение обновления",
                "Установить обновление " + game + "?\n\nТекущая версия будет заменена только после успешной проверки загруженных файлов.",
                parent=self.root,
            )
            if not accepted:
                return
        self.busy = True
        threading.Thread(target=self._install_game, args=(game,), daemon=True).start()

    def _install_updates_sequential(self, games):
        """Install every detected update one by one so the shared busy flag stays safe."""
        for game in games:
            while self.busy:
                time.sleep(0.25)
            self._install_game(game)

    def _safe_extract_zip(self, archive_path, destination):
        root = destination.resolve()
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as bundle:
            for member in bundle.infolist():
                name = member.filename.replace("\\", "/")
                relative = Path(name)
                if relative.is_absolute() or any(part in ("..", "") for part in relative.parts):
                    raise RuntimeError("В архиве найден недопустимый путь: " + member.filename)
                target = (root / relative).resolve()
                if target != root and root not in target.parents:
                    raise RuntimeError("Архив пытается записать файл за пределами папки установки.")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError("В архиве обнаружена символическая ссылка: " + member.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

    def _install_skyrealm_mode(self, game):
        rel = self.releases.get("sky") or self.fetch_json(API_SKY)
        self.releases["sky"] = rel
        if game == "Apocalypse":
            game_asset_name = "SkyRealm_Apocalypse_Game.zip"
            runtime_asset_name = "SkyRealm_Apocalypse_Windows.zip"
            runner_name = "SkyRealmApocalypse.exe"
        else:
            game_asset_name = "SkyRealm_Game.zip"
            runtime_asset_name = "SkyRealm_Windows.zip"
            runner_name = "SkyRealmGame.exe"
        game_asset = self.find_asset(rel, game_asset_name)
        runtime_asset = self.find_asset(rel, runtime_asset_name)
        if not game_asset or not runtime_asset:
            raise RuntimeError(
                "В последнем релизе не найдены отдельные пакеты " +
                game_asset_name + " и " + runtime_asset_name +
                ". Проверь обновление PrimeHub и повтори попытку."
            )
        safe_tag = re.sub(r"[^A-Za-z0-9_.-]", "_", str(rel.get("tag_name") or "latest"))
        cache = ROOT / "cache"
        game_archive = cache / (game + "_Game_" + safe_tag + ".zip")
        runtime_archive = cache / (game + "_Windows_" + safe_tag + ".zip")
        self.set_status("Скачиваем отдельное издание " + game + "...")
        self.download_asset(game_asset, game_archive)
        self.set_progress(0, "Загружаем отдельный запускатель " + game + "...")
        self.download_asset(runtime_asset, runtime_archive)

        staging_root = ROOT / "staging" / (game + "-install")
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        game_dir = staging_root / "game"
        runtime_extract = staging_root / "runtime-extract"
        self.set_progress(0, "Распаковываем независимую сборку " + game + "...")
        self._safe_extract_zip(game_archive, game_dir)
        self._safe_extract_zip(runtime_archive, runtime_extract)
        runner_candidates = [p for p in runtime_extract.rglob(runner_name) if p.is_file()]
        if len(runner_candidates) != 1:
            raise RuntimeError("В пакете " + game + " не найден отдельный файл " + runner_name + ".")
        runtime_dir = staging_root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runner = runtime_dir / runner_name
        shutil.copy2(runner_candidates[0], runner)
        shutil.rmtree(runtime_extract, ignore_errors=True)

        index = game_dir / "index.html"
        script = game_dir / "game.js"
        version_file = game_dir / "version.txt"
        if not index.is_file() or not script.is_file() or not version_file.is_file():
            raise RuntimeError("Архив " + game + " неполный: отсутствует index.html, game.js или version.txt.")
        if game == "Apocalypse":
            marker = game_dir / "APOCALYPSE_EDITION.json"
            if not marker.is_file():
                raise RuntimeError("Это не отдельный пакет Apocalypse: отсутствует APOCALYPSE_EDITION.json.")
            try:
                edition = json.loads(marker.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                raise RuntimeError("Маркер Apocalypse повреждён: " + str(exc))
            game_source = script.read_text(encoding="utf-8")
            html_source = index.read_text(encoding="utf-8")
            required_game = ("IS_APOCALYPSE_MODE", "apocalypseInfected", "drawApocalypseRuins", "skyrealm_apocalypse_worlds_v1")
            required_html = ("apocalypse-intro-scene", "scene-apocalypse", "APOCALYPSE")
            if (edition.get("edition") != "apocalypse" or edition.get("mode") != "apocalypse"
                    or edition.get("launcher") != "SkyRealmApocalypse.exe"
                    or any(token not in game_source for token in required_game)
                    or any(token not in html_source for token in required_html)):
                raise RuntimeError("В архиве нет полноценной сборки Apocalypse. Текущая установленная версия не изменена.")
        with runner.open("rb") as stream:
            if stream.read(2) != b"MZ" or runner.stat().st_size < 1_000_000:
                raise RuntimeError("Игровой запускатель " + runner_name + " повреждён или не является Windows EXE.")
        game_version = version_file.read_text(encoding="utf-8").strip()
        dest = self.installed_dir(game)
        dest.parent.mkdir(parents=True, exist_ok=True)
        backup_root = ROOT / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / (game + ".previous")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        moved_old = False
        if dest.exists():
            dest.rename(backup)
            moved_old = True
        try:
            staging_root.rename(dest)
        except Exception:
            if moved_old and backup.exists() and not dest.exists():
                backup.rename(dest)
            raise
        if backup.exists() and not self.get_launcher_settings().get("keep_backups", True):
            shutil.rmtree(backup, ignore_errors=True)
        self.state[game] = {
            "version": rel.get("tag_name"), "game_version": game_version,
            "edition": "apocalypse" if game == "Apocalypse" else "normal",
            "installed": int(time.time())
        }
        self.save_state()
        self.set_status(game + " установлен • " + game_version, COLORS["green"])
        self.set_progress(100, game + " готов. Запускатель: " + runner_name)

    def _install_apocalypse_pc(self):
        rel = self.releases.get("apocalypse_pc") or self.fetch_latest_apocalypse_release()
        self.releases["apocalypse_pc"] = rel
        tag = str(rel.get("tag_name") or APOCALYPSE_PC_VERSION)
        asset = self.find_asset(rel, "SkyRealmApocalypse.exe")
        if not asset:
            raise RuntimeError("В отдельном релизе мобильной Apocalypse не найден SkyRealmApocalypse.exe.")
        safe_tag = re.sub(r"[^A-Za-z0-9_.-]", "_", tag)
        staging = ROOT / "staging" / ("Apocalypse-" + safe_tag)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        exe = staging / "SkyRealmApocalypse.exe"
        self.set_status("Скачиваем мобильную Apocalypse для Windows...")
        self.download_asset(asset, exe)
        if not exe.is_file() or exe.stat().st_size < 1_000_000:
            raise RuntimeError("SkyRealmApocalypse.exe скачался не полностью.")
        with exe.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise RuntimeError("Файл мобильной Apocalypse повреждён: это не Windows EXE.")
        expected_digest = str(asset.get("digest") or "").lower()
        installed_digest = hashlib.sha256(exe.read_bytes()).hexdigest()
        if expected_digest.startswith("sha256:") and installed_digest != expected_digest.split(":", 1)[1]:
            raise RuntimeError("SHA-256 Apocalypse не совпадает с опубликованным релизом. Старая версия сохранена.")
        expected_size = int(asset.get("size") or 0)
        if expected_size and exe.stat().st_size != expected_size:
            raise RuntimeError("Размер Apocalypse не совпадает с опубликованным релизом. Старая версия сохранена.")
        (staging / "edition.json").write_text(
            json.dumps({"edition": "apocalypse-mobile", "version": tag}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        dest = self.installed_dir("Apocalypse")
        dest.parent.mkdir(parents=True, exist_ok=True)
        backup = ROOT / "backups" / "Apocalypse.previous"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        moved_old = False
        if dest.exists():
            dest.rename(backup)
            moved_old = True
        try:
            staging.rename(dest)
        except Exception:
            if moved_old and backup.exists() and not dest.exists():
                backup.rename(dest)
            raise
        if backup.exists() and not self.get_launcher_settings().get("keep_backups", True):
            shutil.rmtree(backup, ignore_errors=True)
        self.state["Apocalypse"] = {
            "version": tag, "game_version": "mobile-apocalypse",
            "edition": "apocalypse-mobile", "sha256": installed_digest,
            "installed": int(time.time())
        }
        self.save_state()
        self.set_status("Мобильная Apocalypse установлена • " + tag, COLORS["green"])
        self.set_progress(100, "Готово. Установлен самостоятельный SkyRealmApocalypse.exe.")

    def _install_game(self, game):
        self.busy=True
        try:
            GAMES.mkdir(parents=True,exist_ok=True)
            if game == "SkyRealm":
                self._install_skyrealm_mode(game)
            elif game == "Apocalypse":
                self._install_apocalypse_pc()
            elif game=="PrimeLauncher":
                rel=self.releases.get("sky") or self.fetch_json(API_SKY)
                asset=self.find_asset(rel,"PrimeLauncher.exe")
                if not asset: raise RuntimeError("В последнем релизе не найден PrimeLauncher.exe")
                dest=self.installed_dir("PrimeLauncher")
                dest.mkdir(parents=True,exist_ok=True)
                target=dest/"PrimeLauncher.exe"
                self.set_status("Устанавливаем PrimeLauncher...")
                self.download_asset(asset, target)
                with target.open("rb") as stream:
                    if stream.read(2) != b"MZ" or target.stat().st_size < 1_000_000:
                        target.unlink(missing_ok=True)
                        raise RuntimeError("PrimeLauncher.exe скачан не полностью или повреждён.")
                self.state["PrimeLauncher"]={"version":rel.get("tag_name"),"installed":int(time.time())}
                self.save_state()
                self.set_status("PrimeLauncher установлен",COLORS["green"])
                self.set_progress(100,"PrimeLauncher установлен.")
            else:
                rel=self.releases.get("mobile") or self.fetch_json(API_PRIME_MOBILE)
                asset=self.find_asset(rel,"app-debug.apk") or self.find_asset(rel,"PrimeHub-Mobile.apk") or self.find_asset(rel,"PrimeLauncher-Mobile.apk")
                if not asset: raise RuntimeError("В последнем мобильном релизе не найден APK")
                dest=self.installed_dir("PrimeLauncher Mobile")
                dest.mkdir(parents=True,exist_ok=True)
                target=dest/"SkyRealm-Hub.apk"
                self.set_status("Скачиваем Android APK...")
                self.download_asset(asset, target)
                self.state["PrimeLauncher Mobile"]={"version":rel.get("tag_name"),"installed":int(time.time())}
                self.save_state()
                self.set_status("APK скачан",COLORS["green"])
                self.set_progress(100,"SkyRealm Hub APK сохранён в "+str(target)+" — открой его на Android для установки.")
            if self.get_launcher_settings().get("clear_cache_after_install", False):
                shutil.rmtree(ROOT / "cache", ignore_errors=True)
            self.root.after(0, self.refresh_cards)
            self.root.after(0, self._refresh_channels_if_open)
        except Exception as e:
            self.set_status("Не удалось завершить установку",COLORS["orange"])
            self.set_progress(0,"Ошибка загрузки: " + str(e))
            # Restore the library after a failed GitHub request/download.
            self.root.after(0, self.refresh_cards)
            self.root.after(0,lambda:messagebox.showerror("PrimeHub — ошибка обновления", "Не удалось скачать или проверить обновление.\nСтарая версия и сохранения оставлены без изменений.\n\n" + str(e)))
        finally: self.busy=False


    def save_auth_session(self):
        """Persist only the rotating refresh token, encrypted for this Windows user."""
        token = (self.session or {}).get("refresh_token", "")
        if not token:
            return
        try:
            ROOT.mkdir(parents=True, exist_ok=True)
            encrypted = _dpapi_transform(token.encode("utf-8"), True)
            temp = AUTH_SESSION.with_suffix(".tmp")
            temp.write_bytes(encrypted)
            os.replace(temp, AUTH_SESSION)
        except Exception:
            # Never fall back to writing an unencrypted token to disk.
            try:
                AUTH_SESSION.unlink(missing_ok=True)
            except Exception:
                pass

    def clear_auth_session(self):
        try:
            AUTH_SESSION.unlink(missing_ok=True)
        except Exception:
            pass

    def restore_auth_session_async(self):
        """Refresh a saved session in the background so Hub startup stays responsive."""
        if os.name != "nt" or not AUTH_SESSION.is_file():
            return
        def worker():
            try:
                encrypted = AUTH_SESSION.read_bytes()
                refresh_token = _dpapi_transform(encrypted, False).decode("utf-8")
                if not refresh_token or len(refresh_token) > 4096:
                    raise ValueError("Invalid saved refresh token")
                refreshed = self.auth_api("/api/auth/refresh", {"refresh_token": refresh_token}, use_auth=False)
                if not refreshed.get("access_token") or not refreshed.get("refresh_token") or not refreshed.get("user"):
                    raise RuntimeError("Invalid refresh response")
                refreshed["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600))
                # Store the rotated token before publishing the session to the UI.
                encrypted_next = _dpapi_transform(refreshed["refresh_token"].encode("utf-8"), True)
                temp = AUTH_SESSION.with_suffix(".tmp")
                temp.write_bytes(encrypted_next)
                os.replace(temp, AUTH_SESSION)
                self.root.after(0, lambda data=refreshed: self._restore_auth_session_complete(data))
            except urllib.error.URLError:
                # Keep the saved token when offline; the next start can retry.
                return
            except Exception:
                # A corrupt or revoked local token must not be treated as signed in.
                try:
                    AUTH_SESSION.unlink(missing_ok=True)
                except Exception:
                    pass
        threading.Thread(target=worker, daemon=True).start()

    def _restore_auth_session_complete(self, data):
        self.session = dict(data)
        self.update_account_button()

    def auth_api(self, route, payload=None, use_auth=True):
        if use_auth and self.session and route != "/api/auth/refresh":
            if self.session.get("expires_at", 0) <= time.time() + 60:
                try:
                    refreshed = self.auth_api("/api/auth/refresh", {"refresh_token": self.session.get("refresh_token", "")}, use_auth=False)
                    self.session.update(refreshed)
                    self.session["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600))
                    self.save_auth_session()
                except Exception:
                    self.session = None
                    raise RuntimeError("Сессия истекла. Войди в аккаунт снова.")
        url = API_AUTH + "?route=" + urllib.parse.quote(route, safe="/")
        headers = {"User-Agent": "PrimeHub/1.0", "Accept": "application/json", "apikey": API_KEY}
        headers["Authorization"] = "Bearer " + (self.session.get("access_token") if use_auth and self.session and self.session.get("access_token") else API_KEY)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if use_auth and self.session and self.session.get("access_token"):
            headers["Authorization"] = "Bearer " + self.session["access_token"]
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8") if payload is not None else None, headers=headers, method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            detail = data.get("detail", {}) if isinstance(data, dict) else {}
            raise RuntimeError(detail.get("message") or data.get("message") or ("Ошибка сервера: " + str(exc.code)))
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            raise RuntimeError("Сервер вернул некорректный ответ.")

    def update_account_button(self):
        if not hasattr(self, "account_btn"):
            return
        user = (self.session or {}).get("user") or {}
        label = user.get("username") or user.get("email") or ""
        self.account_btn.configure(text=("● " + label) if label else "Войти / Регистрация")

    def open_account(self):
        if self.account_window and self.account_window.winfo_exists():
            self.account_window.lift()
            return
        win = tk.Toplevel(self.root)
        self.account_window = win
        win.title("Аккаунт PrimeHub")
        win.geometry("470x520")
        win.resizable(False, False)
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self.account_body = tk.Frame(win, bg=COLORS["bg"])
        self.account_body.pack(fill="both", expand=True, padx=28, pady=24)
        self.show_account_profile() if self.session else self.show_auth_form("login")

    def auth_heading(self, title, subtitle):
        tk.Label(self.account_body, text=title, font=("Segoe UI",20,"bold"), fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w")
        tk.Label(self.account_body, text=subtitle, font=("Segoe UI",9), fg=COLORS["muted"], bg=COLORS["bg"], wraplength=405, justify="left").pack(anchor="w", pady=(7,18))

    def auth_field(self, label, secret=False, value=""):
        tk.Label(self.account_body, text=label, font=("Segoe UI",9,"bold"), fg=COLORS["muted"], bg=COLORS["bg"]).pack(anchor="w", pady=(8,5))
        entry = tk.Entry(self.account_body, width=48, takefocus=True, exportselection=False, font=("Segoe UI",11), bg=COLORS["panel"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", bd=0, show="●" if secret else "")
        entry.pack(fill="x", ipady=10)
        entry.configure(state="normal", justify="left")
        if value:
            entry.insert(0, value)
        return entry

    def auth_button(self, label, command, secondary=False):
        btn = tk.Button(self.account_body, text=label, command=command, bg=COLORS["panel2"] if secondary else COLORS["blue"], fg=COLORS["text"] if secondary else "white", activebackground=COLORS["line"] if secondary else COLORS["cyan"], activeforeground=COLORS["text"] if secondary else "#07101d", bd=0, font=("Segoe UI",9,"bold"), padx=14, pady=11, cursor="hand2")
        btn.pack(fill="x", pady=(12,0))
        return btn

    def auth_switch(self, text, mode):
        tk.Button(self.account_body, text=text, command=lambda:self.show_auth_form(mode), bg=COLORS["bg"], fg=COLORS["cyan"], activebackground=COLORS["bg"], activeforeground=COLORS["blue"], bd=0, font=("Segoe UI",9,"underline"), cursor="hand2").pack(pady=(12,0))

    def show_auth_form(self, mode):
        for child in self.account_body.winfo_children():
            child.destroy()
        if mode == "register":
            self.auth_heading("Создать аккаунт", "Регистрация открыта для всех. Приглашение или специальный код не нужны.")
            self.reg_username = self.auth_field("Имя игрока (3–20 символов)")
            self.reg_email = self.auth_field("Электронная почта")
            self.reg_password = self.auth_field("Пароль (не менее 8 символов)", True)
            self.account_window.after_idle(self.reg_username.focus_set)
            self.auth_button("Зарегистрироваться", self.submit_register)
            self.auth_switch("Уже есть аккаунт? Войти", "login")
        else:
            self.auth_heading("Вход в PrimeHub", "Войди по имени игрока или адресу электронной почты.")
            self.login_identifier = self.auth_field("Имя игрока или почта")
            self.login_password = self.auth_field("Пароль", True)
            self.account_window.after_idle(self.login_identifier.focus_set)
            self.auth_button("Войти", self.submit_login)
            self.auth_switch("Создать новый аккаунт", "register")

    def show_verify_form(self, email):
        for child in self.account_body.winfo_children():
            child.destroy()
        self.auth_heading("Подтверждение почты", "Мы отправили одноразовый код на " + email + ". Введи код из письма, чтобы завершить регистрацию.")
        self.verify_code = self.auth_field("Код из письма")
        self.auth_button("Подтвердить и войти", self.submit_verify)
        self.auth_button("Отправить код ещё раз", self.resend_code, secondary=True)
        self.auth_switch("Назад ко входу", "login")

    def accept_session(self, data):
        self.session = dict(data)
        self.session["expires_at"] = time.time() + int(data.get("expires_in", 3600))
        self.save_auth_session()
        self.update_account_button()
        if self.account_window and self.account_window.winfo_exists():
            self.account_window.destroy()
        messagebox.showinfo("PrimeHub", "Ты вошёл в аккаунт " + str((data.get("user") or {}).get("username") or "") + ".", parent=self.root)

    def submit_register(self):
        username = self.reg_username.get().strip()
        email = self.reg_email.get().strip()
        password = self.reg_password.get()
        if len(username) < 3 or len(username) > 20:
            messagebox.showwarning("Регистрация", "Имя игрока должно содержать от 3 до 20 символов.", parent=self.account_window); return
        if not email or len(password) < 8:
            messagebox.showwarning("Регистрация", "Укажи почту и пароль не короче 8 символов.", parent=self.account_window); return
        try:
            result = self.auth_api("/api/auth/register", {"username": username, "email": email, "password": password}, use_auth=False)
            self.pending_email = result.get("email") or email
            self.show_verify_form(self.pending_email)
        except Exception as exc:
            messagebox.showerror("Регистрация", str(exc), parent=self.account_window)

    def submit_verify(self):
        code = self.verify_code.get().strip()
        try:
            result = self.auth_api("/api/auth/verify", {"email": self.pending_email, "code": code}, use_auth=False)
            self.accept_session(result)
        except Exception as exc:
            messagebox.showerror("Подтверждение почты", str(exc), parent=self.account_window)

    def resend_code(self):
        try:
            result = self.auth_api("/api/auth/resend", {"email": self.pending_email}, use_auth=False)
            messagebox.showinfo("PrimeHub", result.get("message", "Если аккаунт ожидает подтверждения, новый код отправлен."), parent=self.account_window)
        except Exception as exc:
            messagebox.showerror("PrimeHub", str(exc), parent=self.account_window)

    def submit_login(self):
        identifier = self.login_identifier.get().strip()
        password = self.login_password.get()
        if not identifier or not password:
            messagebox.showwarning("Вход", "Введи имя игрока/почту и пароль.", parent=self.account_window); return
        try:
            result = self.auth_api("/api/auth/login", {"identifier": identifier, "password": password}, use_auth=False)
            self.accept_session(result)
        except Exception as exc:
            messagebox.showerror("Вход", str(exc), parent=self.account_window)

    def show_account_profile(self):
        for child in self.account_body.winfo_children():
            child.destroy()
        user = (self.session or {}).get("user") or {}
        self.auth_heading("Твой аккаунт", "Аккаунт PrimeHub подключён.")
        tk.Label(self.account_body, text=user.get("username") or "Игрок", font=("Segoe UI",15,"bold"), fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w", pady=(8,3))
        tk.Label(self.account_body, text=user.get("email") or "", font=("Segoe UI",9), fg=COLORS["muted"], bg=COLORS["bg"]).pack(anchor="w")
        self.auth_button("Выйти из аккаунта", self.logout_account)
        self.auth_button("Закрыть", self.account_window.destroy, secondary=True)

    def logout_account(self):
        try:
            self.auth_api("/api/auth/logout", {}, use_auth=True)
        except Exception:
            pass
        self.session = None
        self.clear_auth_session()
        self.update_account_button()
        self.account_window.destroy()

    def save_apocalypse_settings(self, settings=None):
        value = self.get_apocalypse_settings() if settings is None else dict(settings)
        self.state["apocalypse_settings"] = value
        ROOT.mkdir(parents=True, exist_ok=True)
        temp = APOCALYPSE_CONFIG.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, APOCALYPSE_CONFIG)
        self.save_state()
        return value

    def close_hub_after_launch(self):
        if self.get_launcher_settings().get("close_hub_after_launch", False):
            self.root.after(450, self.root.destroy)

    def game_auth_environment(self):
        """Pass the active PrimeHub account to child games without writing access tokens to disk."""
        env = os.environ.copy()
        try:
            settings = self.save_apocalypse_settings(self.get_apocalypse_settings())
            env["SKYREALM_APOCALYPSE_SETTINGS_JSON"] = json.dumps(settings, ensure_ascii=False)
        except Exception as exc:
            self.set_status("Настройки Apocalypse не сохранены: " + str(exc), COLORS["orange"])
        if not self.session:
            return env
        if self.session.get("expires_at", 0) <= time.time() + 90:
            try:
                refreshed = self.auth_api("/api/auth/refresh", {"refresh_token": self.session.get("refresh_token", "")}, use_auth=False)
                self.session.update(refreshed)
                self.session["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600))
                self.save_auth_session()
            except Exception:
                self.session = None
                self.update_account_button()
                return env
        user = self.session.get("user") or {}
        access_token = self.session.get("access_token") or ""
        if access_token:
            # SkyRealm and PrimeLauncher already consume this short-lived bearer
            # through their native WebView bridge. Apocalypse PC also receives the
            # structured session below for its co-op sign-in.
            env["SKYREALM_SESSION_TOKEN"] = access_token
            env["SKYREALM_PRIMEHUB_SESSION"] = json.dumps(
                {"access_token": access_token, "user": user}, ensure_ascii=False
            )
        return env

    def launch_apocalypse(self):
        self.launch_game("Apocalypse")

    def launch_game(self, game):
        if game == "Apocalypse":
            base = self.installed_dir("Apocalypse")
            exe = base / "SkyRealmApocalypse.exe"
            if not exe.is_file():
                messagebox.showerror("PrimeHub", "Мобильная Apocalypse для Windows не установлена. Нажми «УСТАНОВИТЬ» на карточке игры.")
                return
            try:
                env = self.game_auth_environment()
                subprocess.Popen([str(exe)], cwd=str(base), env=env)
                account_state = "с аккаунтом PrimeHub" if env.get("SKYREALM_PRIMEHUB_SESSION") else "без входа в PrimeHub"
                self.set_status("Apocalypse запущена " + account_state, COLORS["green"])
                self.close_hub_after_launch()
            except Exception as exc:
                messagebox.showerror("PrimeHub", "Не удалось запустить Apocalypse: " + str(exc))
            return
        if game == "SkyRealm":
            base = self.installed_dir(game)
            runner_name = "SkyRealmApocalypse.exe" if game == "Apocalypse" else "SkyRealmGame.exe"
            exe = base / "runtime" / runner_name
            index = base / "game" / "index.html"
            if not exe.is_file() or not index.is_file():
                messagebox.showinfo("PrimeHub", "Сначала установи " + game + " через соответствующую карточку.")
                return
            try:
                env = self.game_auth_environment()
                if game == "Apocalypse":
                    env["SKYREALM_GAME_MODE"] = "apocalypse"
                else:
                    env.pop("SKYREALM_GAME_MODE", None)
                mode = "apocalypse" if game == "Apocalypse" else "normal"
                if game == "Apocalypse":
                    marker = base / "game" / "APOCALYPSE_EDITION.json"
                    try:
                        edition = json.loads(marker.read_text(encoding="utf-8-sig"))
                    except Exception:
                        messagebox.showerror("Apocalypse", "Установка не является отдельной сборкой Apocalypse. Переустанови Apocalypse через Hub.")
                        return
                    if edition.get("edition") != "apocalypse" or edition.get("launcher") != runner_name:
                        messagebox.showerror("Apocalypse", "Маркер издания не совпадает с отдельным запускателем. Переустанови Apocalypse.")
                        return
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
                subprocess.Popen([str(exe), "--skyrealm-game", str(index), "--mode", mode],
                                 cwd=str(index.parent), env=env, close_fds=True, creationflags=flags)
                self.close_hub_after_launch()
            except Exception as exc:
                messagebox.showerror("Не удалось запустить " + game, str(exc))
            return
        base=self.installed_dir(game)
        exe=base/"PrimeLauncher.exe"
        if not exe.exists():
            messagebox.showinfo("PrimeHub","Игра ещё не установлена. Нажми «Установить».")
            return
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), env=self.game_auth_environment())
            self.close_hub_after_launch()
        except Exception as e:
            messagebox.showerror("Не удалось запустить", str(e))


def _write_startup_error_log(error_text):
    """Persist a startup traceback so launch failures can be diagnosed on the user's PC."""
    candidates = [ROOT / "logs" / "startup.log", Path(os.environ.get("TEMP", str(Path.home()))) / "PrimeHub-startup.log"]
    for log_path in candidates:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write("\n" + "=" * 72 + "\n" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + error_text + "\n")
            return str(log_path)
        except Exception:
            continue
    return "не удалось создать файл журнала"


def main():
    app = None
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        app = tk.Tk()
        PrimeHub(app)
        app.mainloop()
    except Exception:
        details = traceback.format_exc()
        log_path = _write_startup_error_log(details)
        message = "PrimeHub не удалось запустить.\n\nПодробности записаны сюда:\n" + log_path + "\n\n" + details[-1800:]
        try:
            if app is not None and app.winfo_exists():
                messagebox.showerror("Ошибка запуска PrimeHub", message, parent=app)
            elif os.name == "nt":
                ctypes.windll.user32.MessageBoxW(None, message, "Ошибка запуска PrimeHub", 0x10)
        except Exception:
            pass
        raise


if __name__=="__main__":
    if os.name == "nt":
        try:
            import multiprocessing
            multiprocessing.freeze_support()
        except Exception:
            pass
    main()