"""Application information and acknowledgments."""

import tkinter as tk
import webbrowser
from tkinter import ttk

from usbc_average_lookup import __version__
from usbc_average_lookup.theme import INK, TEAL
from usbc_average_lookup.ui import Dialog

PROJECT_URL = "https://github.com/TheIlluminate92/usbc-average-lookup"
CREDITS = """Created by Erik Boettcher (TheIlluminate92)
Development assistance: OpenAI Codex

Save bowlers and average history. Prepare BTM26+ and general spreadsheet exports.

Data and compatibility
Member information and averages: BOWL.com / United States Bowling Congress (USBC).
BTM compatibility: Bowling Tournament Manager by CDE Software.

Built with
Python • Tcl/Tk • SQLite
openpyxl — Excel files
pywebview and Microsoft Edge WebView2 — sign-in window
PyInstaller — Windows application packaging

Thanks to these projects' maintainers and contributors, and to our bowler testers.
"""


class AboutDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, "About Average Assistant", "640x560")
        footer = ttk.Frame(self.content)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(
            footer, text="Project on GitHub", command=lambda: webbrowser.open(PROJECT_URL)
        ).pack(side="left")
        ttk.Button(footer, text="Close", command=self.destroy, style="Primary.TButton").pack(
            side="right"
        )
        ttk.Label(self.content, text="Average Assistant", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.content, text=f"Version {__version__}").pack(anchor="w", pady=(4, 14))
        body = ttk.Frame(self.content)
        body.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        credits = tk.Text(
            body,
            wrap="word",
            font=("Segoe UI", 10),
            background="white",
            foreground=INK,
            selectbackground=TEAL,
            selectforeground="white",
            relief="flat",
            padx=14,
            pady=12,
            yscrollcommand=scroll.set,
            width=45,
            height=10,
        )
        credits.pack(fill="both", expand=True)
        scroll.configure(command=credits.yview)
        credits.insert("1.0", CREDITS)
        credits.configure(state="disabled")
