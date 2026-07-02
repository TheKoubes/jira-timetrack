"""The quick-entry mini window (tkinter). Knows nothing about storage."""

import ctypes
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

WIDTH = 520
GHOST_COLOR = "#9aa0a6"
MAX_LIST_ROWS = 6


def ticket_matches(text: str, tickets: list[str]) -> list[str]:
    """Ticket keys that the typed *text* is a case-insensitive prefix of.

    Suggestions only while typing the first token (no space yet); an already
    fully typed key (exact case) yields nothing, so commands like ``stop`` or
    a finished key don't keep a dropdown open.
    """
    if not text or " " in text:
        return []
    upper = text.upper()
    return [t for t in tickets if t.upper().startswith(upper) and t != text]


def ghost_suffix(text: str, match: str) -> str:
    """The not-yet-typed tail of *match* (assumes *text* is its prefix)."""
    if not match.upper().startswith(text.upper()):
        return ""
    return match[len(text):]


class Popup:
    def __init__(
        self,
        root: tk.Tk,
        on_submit: Callable[[str], None],
        get_status: Callable[[], str],
        get_tickets: Callable[[], list[str]] = lambda: [],
    ):
        self.on_submit = on_submit
        self.get_status = get_status
        self.get_tickets = get_tickets
        self.tickets: list[str] = []
        self.matches: list[str] = []
        self.match_index = 0
        self._list_visible = False  # winfo_ismapped je u staženého okna vždy False

        self.window = tk.Toplevel(root)
        self.window.title("TimeTrack")
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.withdraw()
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        self.status = tk.Label(self.window, anchor="w", font=("Segoe UI", 10))
        self.status.pack(fill="x", padx=10, pady=(10, 4))

        self.entry_font = tkfont.Font(family="Segoe UI", size=13)
        self.entry = tk.Entry(self.window, font=self.entry_font)
        self.entry.pack(fill="x", padx=10, ipady=4)

        # Gray inline completion drawn over the entry, just after the caret.
        self.ghost = tk.Label(
            self.entry, font=self.entry_font, fg=GHOST_COLOR, bg=self.entry.cget("background"), bd=0
        )

        self.listbox = tk.Listbox(
            self.window, font=("Segoe UI", 11), activestyle="none", highlightthickness=0, height=0
        )

        self.hint = tk.Label(
            self.window,
            text="Tab doplní ticket · ↑↓ vybírá · Enter = start (text // poznámka) · stop · ? · týden · Esc",
            anchor="w",
            font=("Segoe UI", 8),
            fg="#888888",
        )
        self.hint.pack(fill="x", padx=10, pady=(4, 8))

        self.entry.bind("<Return>", self._submit)
        self.entry.bind("<Tab>", self._accept_suggestion)
        self.entry.bind("<Right>", self._accept_at_end)
        self.entry.bind("<Down>", lambda _e: self._move_selection(1))
        self.entry.bind("<Up>", lambda _e: self._move_selection(-1))
        self.entry.bind("<KeyRelease>", self._on_key_release)
        self.listbox.bind("<ButtonRelease-1>", self._on_list_click)
        self.window.bind("<Escape>", self._on_escape)
        self.entry.bind("<FocusOut>", self._maybe_hide)
        self.window.bind("<Key>", self._redirect_key)

    def show(self) -> None:
        self.status.config(text=self.get_status())
        self.entry.delete(0, "end")
        self.tickets = self.get_tickets()
        self._clear_suggestions()
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        self.window.geometry(f"{WIDTH}x100+{(screen_w - WIDTH) // 2}+{screen_h // 6}")
        self.window.deiconify()
        self.window.update_idletasks()
        self.window.lift()
        self._force_foreground()
        self.entry.focus_set()
        self.window.after(50, self.entry.focus_set)

    def hide(self) -> None:
        self._clear_suggestions()
        self.window.withdraw()

    # --- suggestions -------------------------------------------------------

    def _on_key_release(self, event) -> None:
        # Navigation keys keep their own handling; only real edits refilter.
        if event.keysym in ("Up", "Down", "Tab", "Return", "Escape"):
            return
        self._refresh_suggestions()

    def _refresh_suggestions(self) -> None:
        text = self.entry.get()
        self.matches = ticket_matches(text, self.tickets)
        self.match_index = 0
        self._render_suggestions()

    def _render_suggestions(self) -> None:
        text = self.entry.get()
        if not self.matches:
            self._clear_suggestions()
            return
        current = self.matches[self.match_index]
        suffix = ghost_suffix(text, current)
        if suffix:
            x = self.entry_font.measure(text) + 5  # ~ entry vnitřní odsazení
            self.ghost.config(text=suffix)
            self.ghost.place(x=x, rely=0.5, anchor="w")
        else:
            self.ghost.place_forget()

        self.listbox.delete(0, "end")
        for ticket in self.matches:
            self.listbox.insert("end", ticket)
        self.listbox.config(height=min(len(self.matches), MAX_LIST_ROWS))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self.match_index)
        self.listbox.see(self.match_index)
        if not self._list_visible:
            self.listbox.pack(fill="x", padx=10, pady=(0, 4), before=self.hint)
            self._list_visible = True
        self._resize()

    def _clear_suggestions(self) -> None:
        self.matches = []
        self.match_index = 0
        self.ghost.place_forget()
        if self._list_visible:
            self.listbox.pack_forget()
            self._list_visible = False
            self._resize()

    def _move_selection(self, delta: int) -> str:
        if not self.matches:
            return "break"
        self.match_index = (self.match_index + delta) % len(self.matches)
        self._render_suggestions()
        return "break"

    def _accept_suggestion(self, _event) -> str:
        if self.matches:
            self._apply(self.matches[self.match_index])
        return "break"  # nikdy nepřeskakuj fokus Tabem

    def _accept_at_end(self, _event):
        # Right doplní jen na konci textu (jinak normálně posune kurzor).
        if self.matches and self.entry.index("insert") == len(self.entry.get()):
            self._apply(self.matches[self.match_index])
            return "break"
        return None

    def _on_list_click(self, _event) -> None:
        selection = self.listbox.curselection()
        if selection:
            self._apply(self.matches[selection[0]])
        self.entry.focus_set()

    def _apply(self, ticket: str) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, ticket)
        self.entry.icursor("end")
        self._clear_suggestions()

    def _on_escape(self, _event) -> str:
        # Nejdřív zavři našeptávač, teprve podruhé celé okno.
        if self.matches:
            self._clear_suggestions()
            return "break"
        self.hide()
        return "break"

    def _resize(self) -> None:
        self.window.update_idletasks()
        x, y = self.window.winfo_x(), self.window.winfo_y()
        self.window.geometry(f"{WIDTH}x{self.window.winfo_reqheight()}+{x}+{y}")

    # --- window plumbing ---------------------------------------------------

    def _submit(self, _event) -> None:
        text = self.entry.get().strip()
        self.hide()
        if text:
            self.on_submit(text)

    def _redirect_key(self, event):
        # Right after the popup opens, the first keystroke can land on the
        # window before the entry gains focus and would be lost — catch it
        # and route it into the entry.
        if event.widget is self.entry or event.widget is self.listbox:
            return None
        if event.char and event.char.isprintable():
            self.entry.focus_set()
            self.entry.insert("end", event.char)
            self._refresh_suggestions()
        return "break"

    def _maybe_hide(self, _event) -> None:
        # FocusOut also fires when focus moves within the window; hide only
        # when the whole app lost focus (user clicked/switched elsewhere).
        self.window.after(120, lambda: self.hide() if self.window.focus_get() is None else None)

    def _force_foreground(self) -> None:
        # Windows blocks focus stealing by background processes. Attaching to
        # the input queue of the current foreground thread lifts that
        # restriction without simulating any keystrokes (an Alt-tap trick
        # would put the window into menu mode and swallow the next key).
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = int(self.window.wm_frame(), 16)
        foreground = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        current_thread = kernel32.GetCurrentThreadId()
        attached = target_thread and target_thread != current_thread
        if attached:
            user32.AttachThreadInput(current_thread, target_thread, True)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(current_thread, target_thread, False)
        self.window.focus_force()
