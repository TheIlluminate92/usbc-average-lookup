from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ButtonHint:
    """Non-focusing help for compact controls, by hover or keyboard focus."""

    def __init__(self, widget: tk.Misc, text: str) -> None:
        self.widget = widget
        self.text = text
        self.pending: str | None = None
        self.window: tk.Toplevel | None = None
        for event in ("<Enter>", "<FocusIn>"):
            widget.bind(event, self._schedule, add="+")
        for event in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<Escape>", "<Destroy>"):
            widget.bind(event, self._hide, add="+")

    def _schedule(self, _event: object = None) -> None:
        self._hide()
        self.pending = self.widget.after(500, self._show)

    def _hide(self, _event: object = None) -> None:
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None

    def _show(self) -> None:
        self.pending = None
        if not self.widget.winfo_exists():
            return
        window = tk.Toplevel(self.widget)
        window.withdraw()
        window.overrideredirect(True)
        ttk.Label(window, text=self.text, padding=8, wraplength=320).pack()
        window.update_idletasks()
        x = min(
            self.widget.winfo_rootx(),
            self.widget.winfo_screenwidth() - window.winfo_reqwidth() - 8,
        )
        y = min(
            self.widget.winfo_rooty() + self.widget.winfo_height() + 4,
            self.widget.winfo_screenheight() - window.winfo_reqheight() - 8,
        )
        window.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.window = window
        window.deiconify()
