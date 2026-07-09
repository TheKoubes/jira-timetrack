"""System tray icon, context menu and the global hotkey (Win32 via ctypes).

One hidden native window on a background thread receives both WM_HOTKEY and
tray callbacks; everything is forwarded as action strings through
``on_action`` (called on this thread — hand off to a queue, don't touch Tk).
"""

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from timetrack.hotkey import MOD_NOREPEAT, parse_hotkey

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
wtsapi32 = ctypes.windll.wtsapi32

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011  # odhlaseni / vypnuti Windows
WM_CONTEXTMENU = 0x007B
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_POWERBROADCAST = 0x0218  # zmena napajeni (uspani/hibernace)
WM_WTSSESSION_CHANGE = 0x02B1  # zamceni/odemceni relace
WM_HOTKEY = 0x0312
WM_TRAY_CALLBACK = 0x8001  # WM_APP + 1
WM_TRAY_RELOAD = 0x8002  # WM_APP + 2 — přenačtení nastavení na tray vlákně
WM_TRAY_BALLOON = 0x8003  # WM_APP + 3 — zobrazení bubliny (upozornění na aktualizaci)

WTS_SESSION_LOCK = 0x7
PBT_APMSUSPEND = 0x4  # systém se uspává (sleep i hibernace posílají totéž)
NOTIFY_FOR_THIS_SESSION = 0


@dataclass
class AutoStopFlags:
    """Při kterých systémových událostech automaticky ukončit běžící aktivitu."""

    lock: bool = False  # zamčení obrazovky
    suspend: bool = False  # uspání / hibernace
    logoff: bool = False  # odhlášení / vypnutí

    @property
    def any(self) -> bool:
        return self.lock or self.suspend or self.logoff

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0x0, 0x1, 0x2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1  # ikonka „i“ v bublině
MF_STRING, MF_SEPARATOR = 0x0, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
IDI_APPLICATION = 32512

UPDATE_CMD_ID = 100  # dynamická položka „Aktualizovat…“ (mimo rozsah MENU_ITEMS)

# (menu id, action, label); None = separator
MENU_ITEMS = [
    (1, "show", "Zadat aktivitu"),
    (2, "summary", "Dnešní sumář"),
    (3, "week", "Týdenní přehled"),
    (6, "edit", "Upravit záznamy…"),
    (5, "jira", "Odeslat do Jiry…"),
    (7, "settings", "Nastavení…"),
    None,
    (4, "quit", "Konec"),
]

def _icon_path() -> Path:
    # V PyInstaller buildu jsou data rozbalena do sys._MEIPASS, ne vedle kodu.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / "timetrack.ico"


ICON_PATH = _icon_path()

WINDOW_CLASS = "TimeTrackTray"


def request_quit() -> bool:
    """Ask a running instance to shut down cleanly; True if one was found.

    Closing the tray window takes the whole app down with it (see
    ``WM_DESTROY`` handling), so this is what ``python -m timetrack quit``
    uses from a terminal or a script.
    """
    hwnd = user32.FindWindowW(WINDOW_CLASS, None)
    if not hwnd:
        return False
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return True

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadIconW.restype = wintypes.HICON
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int


def menu_action(cmd_id: int) -> str | None:
    """Map a TrackPopupMenu result to an action name (0/unknown = nothing)."""
    for item in MENU_ITEMS:
        if item and item[0] == cmd_id:
            return item[1]
    return None


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


class TrayThread:
    def __init__(
        self,
        hotkey_spec: str,
        on_action: Callable[[str], None],
        on_error: Callable[[str], None],
        on_autostop: Callable[[], None] = lambda: None,
        flags: AutoStopFlags | None = None,
        on_warn: Callable[[str], None] = lambda _m: None,
    ):
        self.modifiers, self.vk = parse_hotkey(hotkey_spec)
        self.hotkey_label = "+".join(part.capitalize() for part in hotkey_spec.split("+"))
        self.hotkey_spec = hotkey_spec
        self.on_action = on_action
        self.on_error = on_error
        # on_autostop runs on this (tray) thread — it only writes storage,
        # never touches Tk, so the queue hand-off rule does not apply.
        self.on_autostop = on_autostop
        self.on_warn = on_warn
        self.flags = flags or AutoStopFlags()
        self.hwnd: int | None = None
        self._session_registered = False
        self._pending: tuple[str, AutoStopFlags] | None = None
        # Dostupná aktualizace: verze pro položku menu + text bubliny k zobrazení.
        self.update_version: str | None = None
        self._balloon: tuple[str, str] | None = None
        # The WNDPROC wrapper must outlive the window, or ctypes frees it
        # and Windows calls into released memory.
        self._wndproc = WNDPROC(self._handle_message)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def apply_settings(self, hotkey_spec: str, flags: AutoStopFlags) -> None:
        """Re-apply hotkey + auto-stop live (from any thread; runs on tray thread)."""
        if not self.hwnd:
            return
        self._pending = (hotkey_spec, flags)
        user32.PostMessageW(self.hwnd, WM_TRAY_RELOAD, 0, 0)

    def notify_update(self, version: str, title: str, text: str) -> None:
        """Zobraz bublinu o nové verzi a přidej do menu „Aktualizovat…“.

        Volá se z hlavního vlákna přes queue; samotné Win32 volání běží až na
        tray vlákně (přes ``WM_TRAY_BALLOON``), aby se nemíchala vlákna.
        """
        if not self.hwnd:
            return
        self.update_version = version
        self._balloon = (title, text)
        user32.PostMessageW(self.hwnd, WM_TRAY_BALLOON, 0, 0)

    def _reload(self) -> None:
        if not self._pending:
            return
        hotkey_spec, flags = self._pending
        self._pending = None

        if hotkey_spec != self.hotkey_spec:
            try:
                modifiers, vk = parse_hotkey(hotkey_spec)
            except ValueError as error:
                self.on_warn(f"Neplatná zkratka {hotkey_spec!r}: {error}")
                modifiers = vk = None
            if vk is not None:
                user32.UnregisterHotKey(self.hwnd, 1)
                if user32.RegisterHotKey(self.hwnd, 1, modifiers | MOD_NOREPEAT, vk):
                    self.modifiers, self.vk, self.hotkey_spec = modifiers, vk, hotkey_spec
                    self.hotkey_label = "+".join(p.capitalize() for p in hotkey_spec.split("+"))
                    self._update_tip()
                else:
                    # Konflikt — vrať starou zkratku, ať uživatel nezůstane bez ní.
                    user32.RegisterHotKey(self.hwnd, 1, self.modifiers | MOD_NOREPEAT, self.vk)
                    self.on_warn(
                        f"Zkratku {hotkey_spec!r} nelze zaregistrovat (už ji někdo používá)."
                        " Ponechávám původní."
                    )

        # Zapnutí/vypnutí hlídání zamčení relace za běhu.
        if flags.lock and not self._session_registered:
            self._session_registered = bool(
                wtsapi32.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
            )
        elif not flags.lock and self._session_registered:
            wtsapi32.WTSUnRegisterSessionNotification(self.hwnd)
            self._session_registered = False
        self.flags = flags

    def _run(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = WINDOW_CLASS
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(
            0, WINDOW_CLASS, "TimeTrack", 0, 0, 0, 0, 0, None, None, hinstance, None
        )
        if not user32.RegisterHotKey(self.hwnd, 1, self.modifiers | MOD_NOREPEAT, self.vk):
            self.on_error(
                f"Zkratku {self.hotkey_spec!r} se nepodařilo zaregistrovat.\n"
                "Nejspíš ji už používá jiná aplikace (nebo běží druhý TimeTrack)."
            )
            return
        # Zamčení relace chodí jen po registraci; uspání i konec session
        # dostává každé top-level okno samo.
        if self.flags.lock:
            self._session_registered = bool(
                wtsapi32.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
            )
        self._add_icon()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _handle_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            self.on_action("show")
            return 0
        if msg == WM_TRAY_RELOAD:
            self._reload()
            return 0
        if msg == WM_TRAY_BALLOON:
            self._show_balloon()
            return 0
        if msg == WM_TRAY_CALLBACK:
            if lparam == WM_LBUTTONUP:
                self.on_action("show")
            elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu(hwnd)
            return 0
        if msg == WM_DESTROY:
            if self._session_registered:
                wtsapi32.WTSUnRegisterSessionNotification(hwnd)
                self._session_registered = False
            self._remove_icon()
            user32.PostQuitMessage(0)
            # Whatever closed the window (menu quit, `timetrack quit`, system
            # shutdown) — make sure the Tk side exits too. During a menu quit
            # the queue is already drained, so the extra event is harmless.
            self.on_action("quit")
            return 0
        if msg == WM_WTSSESSION_CHANGE:
            if self.flags.lock and wparam == WTS_SESSION_LOCK:
                self.on_autostop()
            return 0
        if msg == WM_POWERBROADCAST:
            if self.flags.suspend and wparam == PBT_APMSUSPEND:
                self.on_autostop()
            return 1  # TRUE
        if msg == WM_QUERYENDSESSION:
            if self.flags.logoff:
                self.on_autostop()
            return 1  # TRUE = povolit ukončení session
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        menu = user32.CreatePopupMenu()
        for item in MENU_ITEMS:
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            cmd_id, action, label = item
            if action == "show":
                label = f"{label}\t{self.hotkey_label}"
            user32.AppendMenuW(menu, MF_STRING, cmd_id, label)
        if self.update_version:
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, UPDATE_CMD_ID,
                               f"Aktualizovat na {self.update_version}…")
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        # Without making our window foreground the menu would not close on
        # an outside click (documented TrackPopupMenu quirk).
        user32.SetForegroundWindow(hwnd)
        cmd_id = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, point.x, point.y, 0, hwnd, None
        )
        user32.PostMessageW(hwnd, 0, 0, 0)  # WM_NULL, doporučený úklid po menu
        user32.DestroyMenu(menu)
        if cmd_id == UPDATE_CMD_ID:
            self.on_action("update_run")
            return
        action = menu_action(cmd_id)
        if action:
            self.on_action(action)

    def _notify_data(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _add_icon(self) -> None:
        nid = self._notify_data()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY_CALLBACK
        nid.hIcon = self._load_icon()
        nid.szTip = f"TimeTrack – {self.hotkey_label}"
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _update_tip(self) -> None:
        nid = self._notify_data()
        nid.uFlags = NIF_TIP
        nid.szTip = f"TimeTrack – {self.hotkey_label}"
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _show_balloon(self) -> None:
        if not self._balloon:
            return
        title, text = self._balloon
        nid = self._notify_data()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _remove_icon(self) -> None:
        nid = self._notify_data()
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def _load_icon(self):
        if ICON_PATH.exists():
            hicon = user32.LoadImageW(None, str(ICON_PATH), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if hicon:
                return hicon
        return user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
