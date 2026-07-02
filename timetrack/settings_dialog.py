"""Settings window (ttk.Notebook). Knows nothing about storage or the network.

Persistence, token encryption, autostart and the connection test are done by
the ``on_save`` / ``on_test`` callbacks the app passes in; the dialog only
collects values. Token fields stay blank when a token is already stored
(empty on save = keep it), so secrets are never shown back.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, ttk

FONT = ("Segoe UI", 10)

# (config key, label, kind) — kind: text | int | bool | choice:<a,b>
GENERAL = [("hotkey", "Klávesová zkratka", "text")]
TIME = [
    ("rounding_minutes", "Zaokrouhlení součtů (min, 0 = vypnuto)", "int"),
    ("rounding_mode", "Režim zaokrouhlení", "choice:nearest,up"),
    ("round_times", "Zaokrouhlovat i časy v ose", "bool"),
    ("auto_stop_on_lock", "Auto-stop při zamčení obrazovky", "bool"),
    ("auto_stop_on_suspend", "Auto-stop při uspání / hibernaci", "bool"),
    ("auto_stop_on_logoff", "Auto-stop při odhlášení / vypnutí", "bool"),
]
INTEGRATION = [
    ("jira_base_url", "Jira base URL", "text"),
    ("jira_email", "Atlassian e-mail", "text"),
    ("jira_account_field", "Pole accountu (prázdné = automaticky)", "text"),
]


class SettingsDialog:
    def __init__(
        self,
        root: tk.Tk,
        values: dict,
        tokens_present: dict,
        autostart_on: bool,
        version: str,
        on_save: Callable[[dict, dict, bool], str | None],
        on_test: Callable[[dict, dict], None],
        on_open_log: Callable[[str], None] = lambda _k: None,
    ):
        self.on_save = on_save
        self.on_test = on_test
        self.on_open_log = on_open_log
        self.vars: dict[str, tk.Variable] = {}

        self.window = tk.Toplevel(root)
        self.window.title("TimeTrack — nastavení")
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)

        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_fields(notebook, "Obecné", GENERAL, values, extra_general=autostart_on)
        self._build_fields(notebook, "Vykazování času", TIME, values)
        self._build_integration(notebook, values, tokens_present)
        self._build_data(notebook, values)
        self._build_about(notebook, version)

        self.error = tk.Label(self.window, anchor="w", font=(FONT[0], 9), fg="#bb2222")
        self.error.pack(fill="x", padx=12)

        buttons = tk.Frame(self.window)
        buttons.pack(fill="x", padx=12, pady=(4, 10))
        tk.Button(buttons, text="Uložit", width=12, command=self._save).pack(side="right")
        tk.Button(buttons, text="Zrušit", width=12, command=self.window.destroy).pack(
            side="right", padx=(0, 8)
        )

        self.window.bind("<Escape>", lambda _e: self.window.destroy())
        self._center()

    # --- tab builders ------------------------------------------------------

    def _build_fields(self, notebook, title, fields, values, extra_general=None):
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text=title)
        row = 0
        if extra_general is not None:
            self.vars["_autostart"] = tk.BooleanVar(self.window, value=extra_general)
            ttk.Checkbutton(
                frame, text="Spouštět po přihlášení do Windows", variable=self.vars["_autostart"]
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
            row += 1
        for key, label, kind in fields:
            self._field(frame, row, key, label, kind, values.get(key))
            row += 1

    def _field(self, frame, row, key, label, kind, value) -> None:
        if kind == "bool":
            self.vars[key] = tk.BooleanVar(self.window, value=bool(value))
            ttk.Checkbutton(frame, text=label, variable=self.vars[key]).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=3
            )
            return
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        if kind.startswith("choice:"):
            options = kind.split(":", 1)[1].split(",")
            self.vars[key] = tk.StringVar(self.window, value=str(value))
            ttk.Combobox(
                frame, textvariable=self.vars[key], values=options, state="readonly", width=18
            ).grid(row=row, column=1, sticky="w", pady=3)
        else:
            self.vars[key] = tk.StringVar(self.window, value="" if value is None else str(value))
            ttk.Entry(frame, textvariable=self.vars[key], width=34, font=FONT).grid(
                row=row, column=1, sticky="w", pady=3
            )

    def _build_integration(self, notebook, values, tokens_present):
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="Integrace (Jira/Tempo)")
        row = 0
        for key, label, kind in INTEGRATION:
            self._field(frame, row, key, label, kind, values.get(key))
            row += 1
        for key, label, present in (
            ("jira_token", "Jira API token", tokens_present.get("jira")),
            ("tempo_token", "Tempo API token", tokens_present.get("tempo")),
        ):
            state = "uloženo ✓" if present else "nenastaveno"
            ttk.Label(frame, text=f"{label} ({state})").grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=3
            )
            self.vars[key] = tk.StringVar(self.window, value="")
            ttk.Entry(frame, textvariable=self.vars[key], width=34, show="•", font=FONT).grid(
                row=row, column=1, sticky="w", pady=3
            )
            row += 1
        ttk.Label(
            frame, text="(prázdné = ponechat stávající token)", foreground="#888888"
        ).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Button(frame, text="Otestovat připojení", command=self._test).grid(
            row=row, column=0, sticky="w", pady=(8, 0)
        )
        self.test_label = ttk.Label(frame, text="", foreground="#666666")
        self.test_label.grid(row=row, column=1, sticky="w", pady=(8, 0))

    def _build_data(self, notebook, values):
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="Data")
        ttk.Label(frame, text="Složka s daty").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.vars["data_dir"] = tk.StringVar(self.window, value=values.get("data_dir", ""))
        ttk.Entry(frame, textvariable=self.vars["data_dir"], width=40, font=FONT).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Button(frame, text="Procházet…", command=self._browse_data_dir).grid(
            row=1, column=1, sticky="w", pady=(4, 0)
        )
        ttk.Button(frame, text="Otevřít složku s daty", command=lambda: self.on_open_log("data")).grid(
            row=2, column=1, sticky="w", pady=(4, 0)
        )

    def _build_about(self, notebook, version):
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="O aplikaci")
        ttk.Label(frame, text=f"TimeTrack {version}", font=(FONT[0], 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Button(frame, text="Otevřít log chyb API", command=lambda: self.on_open_log("api")).grid(
            row=1, column=0, sticky="w", pady=2
        )
        ttk.Button(frame, text="Otevřít log při startu", command=lambda: self.on_open_log("startup")).grid(
            row=2, column=0, sticky="w", pady=2
        )

    # --- actions -----------------------------------------------------------

    def collect(self) -> tuple[dict, dict, bool]:
        values, tokens = {}, {}
        for key, var in self.vars.items():
            if key in ("jira_token", "tempo_token"):
                text = var.get().strip()
                tokens[key.split("_")[0]] = text if text else None  # None = ponechat
            elif key == "_autostart":
                pass
            else:
                values[key] = var.get()
        return values, tokens, self.vars["_autostart"].get()

    def _save(self) -> None:
        values, tokens, autostart_on = self.collect()
        error = self.on_save(values, tokens, autostart_on)
        if error:
            self.error.config(text=error)
            return
        self.window.destroy()

    def _test(self) -> None:
        values, tokens, _ = self.collect()
        self.test_label.config(text="testuji…", foreground="#666666")
        self.on_test(values, tokens)

    def test_result(self, ok: bool, message: str) -> None:
        self.test_label.config(text=message, foreground="#227722" if ok else "#bb2222")

    def _browse_data_dir(self) -> None:
        chosen = filedialog.askdirectory(parent=self.window, initialdir=self.vars["data_dir"].get())
        if chosen:
            self.vars["data_dir"].set(chosen.replace("/", "\\"))

    def _center(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        x = (self.window.winfo_screenwidth() - width) // 2
        y = self.window.winfo_screenheight() // 5
        self.window.geometry(f"+{x}+{y}")
        self.window.lift()
        self.window.focus_force()
