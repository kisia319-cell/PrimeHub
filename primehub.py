import os, sys, json, time, shutil, threading, urllib.request, urllib.error, urllib.parse, zipfile, subprocess, re, html, ctypes, hashlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "PrimeHub"
APP_VERSION = "v1.2.2"
APOCALYPSE_PC_VERSION = "apocalypse-pc-v1.1.1"
ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PrimeHub"
GAMES = ROOT / "Games"
DATA = ROOT / "hub-state.json"
AUTH_SESSION = ROOT / "auth-session.bin"
API_SKY = "https://github.com/kisia319-cell/SkyRealm-PC-Launcher/releases/latest"
API_APOCALYPSE_PC = "https://api.github.com/repos/kisia319-cell/SkyRealm-Hub-Mobile/releases?per_page=100"
API_PRIME_MOBILE = "https://github.com/kisia319-cell/SkyRealm-Hub-Mobile/releases/latest"
API_HUB = "https://github.com/kisia319-cell/PrimeHub/releases/latest"
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

COLORS = {"bg":"#0b1020","panel":"#121a2d","panel2":"#18243b","line":"#263650","text":"#eef4ff","muted":"#91a3bf","blue":"#4d8dff","cyan":"#55d5e8","green":"#54d69a","orange":"#ffbd66"}

class PrimeHub:
    def __init__(self, root):
        self.root = root
        self.root.title("PrimeHub")
        self.root.geometry("1120x740")
        self.root.minsize(900, 620)
        self.root.configure(bg=COLORS["bg"])
        self.platform = "PC"
        self.releases = {}
        self.busy = False
        self.state = self.load_state()
        self.session = None  # Only the rotating refresh token is persisted, encrypted with Windows DPAPI.
        self.pending_email = ""
        self.account_window = None
        self.build_ui()
        self.refresh_cards()
        self.root.after(250, self.restore_auth_session_async)
        self.root.after(700, self.check_updates_async)

    def load_state(self):
        try: return json.loads(DATA.read_text("utf-8"))
        except: return {}

    def save_state(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), "utf-8")

    def build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Hub.Horizontal.TProgressbar", troughcolor=COLORS["panel2"], background=COLORS["blue"], bordercolor=COLORS["panel2"], lightcolor=COLORS["blue"], darkcolor=COLORS["blue"])
        header = tk.Frame(self.root, bg=COLORS["bg"])
        header.pack(fill="x", padx=34, pady=(25,12))
        brand = tk.Frame(header, bg=COLORS["bg"])
        brand.pack(side="left")
        tk.Label(brand, text="PRIME", font=("Segoe UI", 24, "bold"), fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        tk.Label(brand, text="HUB", font=("Segoe UI", 24, "bold"), fg=COLORS["blue"], bg=COLORS["bg"]).pack(side="left", padx=(7,0))
        tk.Label(brand, text="  GAME CENTER", font=("Segoe UI", 9, "bold"), fg=COLORS["muted"], bg=COLORS["bg"]).pack(side="left", padx=(12,0), pady=(10,0))
        self.platform_box = tk.Frame(header, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        self.platform_box.pack(side="right")
        self.pc_btn = tk.Button(self.platform_box, text="▣  PC", command=lambda:self.set_platform("PC"), bd=0, padx=22, pady=11, font=("Segoe UI",10,"bold"), cursor="hand2")
        self.android_btn = tk.Button(self.platform_box, text="▣  ANDROID", command=lambda:self.set_platform("Android"), bd=0, padx=22, pady=11, font=("Segoe UI",10,"bold"), cursor="hand2")
        self.pc_btn.pack(side="left")
        self.android_btn.pack(side="left")
        self.account_btn = tk.Button(header, text="Войти / Регистрация", command=self.open_account, bg=COLORS["panel2"], fg=COLORS["text"], activebackground=COLORS["line"], activeforeground=COLORS["text"], bd=0, padx=15, pady=11, font=("Segoe UI",9,"bold"), cursor="hand2")
        self.account_btn.pack(side="right", padx=(0,12))
        hero = tk.Frame(self.root, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        hero.pack(fill="x", padx=34, pady=(8,20))
        hero_inner = tk.Frame(hero, bg=COLORS["panel"])
        hero_inner.pack(fill="x", padx=25, pady=20)
        tk.Label(hero_inner, text="ТВОИ ИГРЫ. В ОДНОМ МЕСТЕ.", font=("Segoe UI",20,"bold"), fg=COLORS["text"], bg=COLORS["panel"]).pack(anchor="w")
        tk.Label(hero_inner, text="Выбирай игру — PrimeHub проверит обновления, установит недостающие файлы и запустит её.", font=("Segoe UI",10), fg=COLORS["muted"], bg=COLORS["panel"]).pack(anchor="w", pady=(7,0))
        row = tk.Frame(hero_inner, bg=COLORS["panel"])
        row.pack(fill="x", pady=(14,0))
        self.status = tk.Label(row, text="● Проверка каталога...", font=("Segoe UI",9,"bold"), fg=COLORS["cyan"], bg=COLORS["panel"])
        self.status.pack(side="left")
        self.refresh_btn = tk.Button(row, text="Проверить обновления", command=self.check_updates_async, bg=COLORS["panel2"], fg=COLORS["text"], activebackground=COLORS["line"], activeforeground=COLORS["text"], bd=0, padx=14, pady=8, cursor="hand2")
        self.refresh_btn.pack(side="right")
        section = tk.Frame(self.root, bg=COLORS["bg"])
        section.pack(fill="x", padx=34, pady=(0,10))
        tk.Label(section, text="БИБЛИОТЕКА", font=("Segoe UI",11,"bold"), fg=COLORS["muted"], bg=COLORS["bg"]).pack(side="left")
        self.count_label = tk.Label(section, text="", font=("Segoe UI",9), fg=COLORS["muted"], bg=COLORS["bg"])
        self.count_label.pack(side="right")
        self.cards = tk.Frame(self.root, bg=COLORS["bg"])
        self.cards.pack(fill="both", expand=True, padx=34, pady=(0,10))
        bottom = tk.Frame(self.root, bg=COLORS["bg"])
        bottom.pack(fill="x", padx=34, pady=(0,20))
        self.progress = ttk.Progressbar(bottom, style="Hub.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.progress_text = tk.Label(bottom, text="Игры устанавливаются в папку PrimeHub, не на рабочий стол.", font=("Segoe UI",8), fg=COLORS["muted"], bg=COLORS["bg"])
        self.progress_text.pack(anchor="w", pady=(7,0))
        self.set_platform("PC")

    def set_platform(self, platform):
        self.platform = platform
        for b,p in ((self.pc_btn,"PC"),(self.android_btn,"Android")):
            active = p == platform
            b.configure(bg=COLORS["blue"] if active else COLORS["panel"], fg="white" if active else COLORS["muted"])
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
            sky_tag=self.releases.get("sky",{}).get("tag_name")
            sky_update=self.needs_update("SkyRealm",sky_tag)
            sky_installed=self.is_installed("SkyRealm")
            self.card(self.cards,"SkyRealm","OPEN WORLD • ADVENTURE", "PC • Windows", "Обычный открытый мир SkyRealm. Устанавливается отдельно от Apocalypse.", "#285f83", "ОБНОВИТЬ" if sky_update else ("ЗАПУСТИТЬ" if sky_installed else "УСТАНОВИТЬ"), (lambda:self.install_game("SkyRealm")) if sky_update or not sky_installed else (lambda:self.launch_game("SkyRealm")), sky_installed)
            prime_update=self.needs_update("PrimeLauncher",sky_tag)
            prime_installed=self.is_installed("PrimeLauncher")
            self.card(self.cards,"PrimeLauncher","ONLINE • ARENA", "PC • Windows", "Отдельная соревновательная игра PrimeLauncher.", "#59428f", "ОБНОВИТЬ" if prime_update else ("ЗАПУСТИТЬ" if prime_installed else "УСТАНОВИТЬ"), (lambda:self.install_game("PrimeLauncher")) if prime_update or not prime_installed else (lambda:self.launch_game("PrimeLauncher")), prime_installed)
            apoc_tag=self.releases.get("apocalypse_pc",{}).get("tag_name") or APOCALYPSE_PC_VERSION
            apoc_update=self.needs_update("Apocalypse",apoc_tag)
            apoc_installed=self.is_installed("Apocalypse")
            self.card(self.cards,"Apocalypse","SURVIVAL • LAST STAND", "Windows • " + apoc_tag, "Отдельная Windows-сборка Apocalypse. PrimeHub проверяет её релиз независимо от обычного SkyRealm; при новой версии появится кнопка «ОБНОВИТЬ».", "#873f49", "ОБНОВИТЬ" if apoc_update else ("ЗАПУСТИТЬ" if apoc_installed else "УСТАНОВИТЬ"), (lambda:self.install_game("Apocalypse")) if apoc_update or not apoc_installed else (lambda:self.launch_apocalypse()), apoc_installed)
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
        self.root.after(0, lambda:self.status.configure(text="● "+msg, fg=color or COLORS["cyan"]))

    def set_progress(self, value, msg):
        def apply():
            self.progress["value"] = value
            self.progress_text.configure(text=msg)
        self.root.after(0, apply)

    def fetch_json(self, url):
        # Prefer public GitHub release pages over the unauthenticated REST API.
        # The REST API is rate-limited (403) and is frequently unavailable to users
        # behind shared or regional NAT addresses.
        parsed = urllib.parse.urlsplit(url)
        release_prefix = "/releases/"
        if parsed.netloc.lower() == "github.com" and release_prefix in parsed.path:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PrimeHub/1.1"})
            with urllib.request.urlopen(req, timeout=30) as response:
                page = response.read().decode("utf-8", errors="replace")
                final_url = response.geturl()

            final_path = urllib.parse.urlsplit(final_url).path
            tag_match = re.search(r"/releases/tag/([^/?#]+)", final_path)
            if tag_match:
                tag = urllib.parse.unquote(tag_match.group(1))
            else:
                requested_tag = re.search(r"/releases/tag/([^/?#]+)", parsed.path)
                if not requested_tag:
                    raise RuntimeError("GitHub не вернул страницу последнего релиза: " + url)
                tag = urllib.parse.unquote(requested_tag.group(1))

            repo_path = parsed.path.split(release_prefix, 1)[0]
            assets_page_url = "https://github.com" + repo_path + "/releases/expanded_assets/" + urllib.parse.quote(tag, safe="")
            assets_req = urllib.request.Request(assets_page_url, headers={"User-Agent": "Mozilla/5.0 PrimeHub/1.1"})
            with urllib.request.urlopen(assets_req, timeout=30) as asset_response:
                assets_page = asset_response.read().decode("utf-8", errors="replace")

            assets = []
            seen = set()
            for match in re.finditer(r'href="([^"]*/releases/download/[^"]+)"', assets_page, re.I):
                href = html.unescape(match.group(1))
                asset_url = urllib.parse.urljoin("https://github.com", href)
                asset_name = urllib.parse.unquote(urllib.parse.urlsplit(asset_url).path.rsplit("/", 1)[-1])
                if asset_name and asset_name not in seen:
                    seen.add(asset_name)
                    assets.append({"name": asset_name, "browser_download_url": asset_url})

            return {"tag_name": tag, "html_url": final_url, "assets": assets}

        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch_latest_apocalypse_release(self):
        """Resolve the newest Windows Apocalypse release, not a permanently pinned tag."""
        releases = None
        try:
            response = self.fetch_json(API_APOCALYPSE_PC)
            if isinstance(response, list):
                releases = response
        except Exception:
            # GitHub REST can be rate-limited on shared/regional networks.
            releases = None

        matching = [
            item for item in (releases or [])
            if str(item.get("tag_name", "")).startswith("apocalypse-pc-v")
            and not item.get("draft", False)
            and any(
                str(asset.get("name", "")).lower() == "skyrealmapocalypse.exe"
                for asset in (item.get("assets") or [])
            )
        ]
        if matching:
            release = max(
                matching,
                key=lambda item: tuple(int(part) for part in re.findall(r"\d+", str(item.get("tag_name", ""))))
            )
            return {
                "tag_name": release.get("tag_name", ""),
                "html_url": release.get("html_url", ""),
                "assets": [
                    {
                        "name": asset.get("name", ""),
                        "browser_download_url": asset.get("browser_download_url", ""),
                        "updated_at": asset.get("updated_at"),
                        "id": asset.get("id"),
                        "digest": asset.get("digest"),
                        "size": asset.get("size"),
                    }
                    for asset in release.get("assets", [])
                ],
            }

        # Fallback to the public releases page when the REST API is unavailable.
        page_url = "https://github.com/kisia319-cell/SkyRealm-Hub-Mobile/releases?q=apocalypse-pc"
        request = urllib.request.Request(
            page_url, headers={"User-Agent": "Mozilla/5.0 PrimeHub/1.2"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            page = response.read().decode("utf-8", errors="replace")
        tags = set(re.findall(
            r'href="/kisia319-cell/SkyRealm-Hub-Mobile/releases/tag/(apocalypse-pc-v[0-9][A-Za-z0-9._-]*)"',
            page,
            re.I,
        ))
        if not tags:
            raise RuntimeError("Не удалось найти опубликованный релиз Apocalypse для Windows.")

        # A matching tag is not enough: some Apocalypse prereleases/metadata
        # entries do not contain the Windows executable. Try newest tags first
        # and select only a release that actually publishes the required EXE.
        ordered_tags = sorted(
            tags,
            key=lambda tag: tuple(int(part) for part in re.findall(r"\d+", tag)),
            reverse=True,
        )
        for candidate_tag in ordered_tags:
            release = self.fetch_json(
                "https://github.com/kisia319-cell/SkyRealm-Hub-Mobile/releases/tag/"
                + urllib.parse.quote(candidate_tag, safe="")
            )
            if self.find_asset(release, "SkyRealmApocalypse.exe"):
                return release
        raise RuntimeError(
            "Найдены версии Apocalypse, но ни в одной не опубликован SkyRealmApocalypse.exe."
        )

    def check_updates_async(self):
        if self.busy: return
        threading.Thread(target=self.check_updates,daemon=True).start()

    def check_updates(self):
        self.busy=True
        auto_updates=[]
        self.set_status("Проверяем официальные версии...")
        try:
            sky=self.fetch_json(API_SKY)
            self.releases["sky"]=sky
            mob=self.fetch_json(API_PRIME_MOBILE)
            self.releases["mobile"]=mob
            apocalypse_pc=self.fetch_latest_apocalypse_release()
            self.releases["apocalypse_pc"]=apocalypse_pc
            try:
                hub=self.fetch_json(API_HUB)
                self.check_hub_update(hub)
            except Exception:
                pass
            # Updates are user-triggered from each game card. Never start a
            # background install immediately after a check; keep the Update
            # button visible so the player can choose when Apocalypse is replaced.
            self.root.after(0,self.refresh_cards)
            self.set_status("Каталог обновлён • "+sky.get("tag_name","")+" / "+mob.get("tag_name","")+" / "+apocalypse_pc.get("tag_name",""),COLORS["green"])
            self.set_progress(0,"Проверка завершена. Установщики и игры сохраняются внутри папки PrimeHub.")
        except Exception as e:
            self.set_status("Нет соединения с сервером обновлений",COLORS["orange"])
            self.set_progress(0,"Не удалось проверить обновления: "+str(e))
        finally:
            self.busy=False

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
        if self.state.get("hub_asset_stamp") == stamp:
            return
        current = Path(sys.executable).resolve()
        update_dir = ROOT / "updates"
        staged = update_dir / "PrimeHub.next.exe"
        script = update_dir / "apply-hub-update.cmd"
        self.set_status("Доступно обновление PrimeHub — загружаем...")
        self.download(asset["browser_download_url"], staged)
        # Refuse to replace the running Hub with a truncated/non-Windows download.
        if not staged.is_file() or staged.stat().st_size < 1_000_000:
            raise RuntimeError("Обновление PrimeHub скачалось не полностью. Старую версию оставили без изменений.")
        with staged.open("rb") as check:
            if check.read(2) != b"MZ":
                raise RuntimeError("Файл обновления PrimeHub повреждён или не является Windows EXE. Старая версия сохранена.")
        staged_size = staged.stat().st_size
        temp_current = current.with_name(current.name + ".new")
        lines = [
            "@echo off",
            "setlocal",
            "set \"STAGED=" + str(staged) + "\"",
            "set \"CURRENT=" + str(current) + "\"",
            "set \"TEMPFILE=" + str(temp_current) + "\"",
            ":retry",
            "copy /b /y \"%STAGED%\" \"%TEMPFILE%\" >nul 2>&1",
            "if errorlevel 1 (timeout /t 1 /nobreak >nul & goto retry)",
            "for %%A in (\"%STAGED%\") do set \"SOURCE_SIZE=%%~zA\"",
            "for %%A in (\"%TEMPFILE%\") do set \"COPY_SIZE=%%~zA\"",
            "if not \"%SOURCE_SIZE%\"==\"%COPY_SIZE%\" (del /q \"%TEMPFILE%\" >nul 2>&1 & timeout /t 1 /nobreak >nul & goto retry)",
            "move /y \"%TEMPFILE%\" \"%CURRENT%\" >nul 2>&1",
            "if errorlevel 1 (timeout /t 1 /nobreak >nul & goto retry)",
            "start \"\" \"%CURRENT%\"",
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
        target.parent.mkdir(parents=True,exist_ok=True)
        req=urllib.request.Request(url,headers={"User-Agent":"PrimeHub/1.0"})
        try:
            with urllib.request.urlopen(req,timeout=90) as response, open(target,"wb") as out:
                total=int(response.headers.get("Content-Length",0)); done=0
                while True:
                    chunk=response.read(1024*512)
                    if not chunk: break
                    out.write(chunk); done+=len(chunk)
                    pct=int(done*100/total) if total else 0
                    self.set_progress(pct,f"Загрузка: {target.name} • {done//1048576} МБ")
                out.flush()
                os.fsync(out.fileno())
            if total and done != total:
                raise RuntimeError(f"Загрузка оборвалась: получено {done} из {total} байт.")
        except Exception:
            try: target.unlink(missing_ok=True)
            except Exception: pass
            raise
        return target

    def install_game(self, game):
        if self.busy: return
        threading.Thread(target=self._install_game,args=(game,),daemon=True).start()

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
        self.download(game_asset["browser_download_url"], game_archive)
        self.set_progress(0, "Загружаем отдельный запускатель " + game + "...")
        self.download(runtime_asset["browser_download_url"], runtime_archive)

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
        if backup.exists():
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
        self.download(asset["browser_download_url"], exe)
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
        if backup.exists():
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
                self.download(asset["browser_download_url"],target)
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
                asset=self.find_asset(rel,"app-debug.apk") or self.find_asset(rel,"PrimeLauncher-Mobile.apk")
                if not asset: raise RuntimeError("В последнем мобильном релизе не найден APK")
                dest=self.installed_dir("PrimeLauncher Mobile")
                dest.mkdir(parents=True,exist_ok=True)
                target=dest/"SkyRealm-Hub.apk"
                self.set_status("Скачиваем Android APK...")
                self.download(asset["browser_download_url"],target)
                self.state["PrimeLauncher Mobile"]={"version":rel.get("tag_name"),"installed":int(time.time())}
                self.save_state()
                self.set_status("APK скачан",COLORS["green"])
                self.set_progress(100,"SkyRealm Hub APK сохранён в "+str(target)+" — открой его на Android для установки.")
            self.root.after(0,self.refresh_cards)
        except Exception as e:
            self.set_status("Не удалось завершить установку",COLORS["orange"])
            self.set_progress(0,str(e))
            self.root.after(0,lambda:messagebox.showerror("PrimeHub",str(e)))
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

    def game_auth_environment(self):
        """Pass the active PrimeHub account to child games without writing access tokens to disk."""
        env = os.environ.copy()
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
            except Exception as exc:
                messagebox.showerror("Не удалось запустить " + game, str(exc))
            return
        base=self.installed_dir(game)
        exe=base/"PrimeLauncher.exe"
        if not exe.exists():
            messagebox.showinfo("PrimeHub","Игра ещё не установлена. Нажми «Установить».")
            return
        try: subprocess.Popen([str(exe)],cwd=str(exe.parent),env=self.game_auth_environment())
        except Exception as e: messagebox.showerror("Не удалось запустить",str(e))


if __name__=="__main__":
    ROOT.mkdir(parents=True,exist_ok=True)
    app=tk.Tk()
    PrimeHub(app)
    app.mainloop()