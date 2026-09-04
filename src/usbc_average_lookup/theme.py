"""Shared navy and teal desktop colors."""

from tkinter import ttk

BACKGROUND = "#EDF3F7"
NAVY = "#15354D"
TEAL = "#087F8C"
INK = "#203D50"
BORDER = "#CAD9E3"


def apply_theme(window):
    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure(".", font=("Segoe UI", 10), background=BACKGROUND, foreground=INK)
    style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=NAVY)
    style.configure("Header.TFrame", background=NAVY)
    style.configure("Header.TLabel", background=NAVY, foreground="#D9EBF4")
    style.configure(
        "HeaderTitle.TLabel", background=NAVY, foreground="white", font=("Segoe UI", 18, "bold")
    )
    style.configure("Count.TLabel", background="#D7EAF0", foreground=NAVY, padding=(9, 4))
    style.configure(
        "TButton",
        padding=(10, 7),
        background="white",
        foreground=NAVY,
        bordercolor=BORDER,
        lightcolor="white",
        darkcolor=BORDER,
    )
    style.map(
        "TButton",
        background=[("disabled", "#E3EAF0"), ("pressed", "#C6DDE7"), ("active", "#E0EEF3")],
        foreground=[("disabled", "#647887")],
    )
    for name, color, hover in [("Primary", TEAL, "#066773"), ("Navy", NAVY, "#244C69")]:
        style.configure(
            f"{name}.TButton",
            background=color,
            foreground="white",
            bordercolor=color,
            lightcolor=color,
            darkcolor=color,
        )
        style.map(
            f"{name}.TButton",
            background=[("disabled", "#DDE7ED"), ("pressed", hover), ("active", hover)],
            foreground=[("disabled", "#647887"), ("!disabled", "white")],
            bordercolor=[("disabled", BORDER), ("!disabled", color)],
        )
    style.configure(
        "Danger.TButton", background="#FFF0F0", foreground="#A12A36", bordercolor="#E8C4C8"
    )
    style.map(
        "Danger.TButton",
        background=[("disabled", "#E3EAF0"), ("active", "#FADFE3")],
        foreground=[("disabled", "#647887"), ("!disabled", "#A12A36")],
    )
    for widget in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(
            widget,
            fieldbackground="white",
            bordercolor=BORDER,
            selectbackground=TEAL,
            selectforeground="white",
            padding=4,
        )
        style.map(
            widget,
            bordercolor=[("focus", TEAL)],
            fieldbackground=[("readonly", "white"), ("disabled", "#E3EAF0")],
        )
    style.configure(
        "Treeview",
        background="white",
        fieldbackground="white",
        foreground=INK,
        rowheight=32,
        bordercolor=BORDER,
    )
    style.configure(
        "Treeview.Heading",
        font=("Segoe UI", 10, "bold"),
        padding=7,
        background=NAVY,
        foreground="white",
        bordercolor=NAVY,
        lightcolor=NAVY,
        darkcolor=NAVY,
    )
    style.map("Treeview.Heading", background=[("active", "#244C69")])
    style.map("Treeview", background=[("selected", TEAL)], foreground=[("selected", "white")])
    style.configure("TNotebook", background=BACKGROUND, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background="#DCE7EF", foreground=NAVY, padding=(9, 6))
    style.map(
        "TNotebook.Tab",
        background=[("selected", TEAL), ("active", "#CADFE8")],
        foreground=[("selected", "white")],
    )
    style.configure(
        "Horizontal.TProgressbar",
        background=TEAL,
        troughcolor="#DCE7EF",
        bordercolor=BORDER,
        lightcolor=TEAL,
        darkcolor=TEAL,
    )
    style.configure(
        "TScrollbar",
        background="#C7DCE5",
        troughcolor=BACKGROUND,
        bordercolor=BACKGROUND,
        arrowcolor=NAVY,
    )
    window.configure(background=BACKGROUND)


def color_table(view):
    for tag, background, foreground in [
        ("ready", "#E6F4EE", "#195840"),
        ("attention", "#FFF3D9", "#754F10"),
        ("error", "#FCE9EC", "#932B3A"),
        ("muted", "#F0F4F7", "#526978"),
        ("stripe", "#F3F8FB", INK),
    ]:
        view.tag_configure(tag, background=background, foreground=foreground)


def status_tag(status):
    if status == "Refreshed":
        return "ready"
    if status in ("Refresh failed", "Rate limited", "Sign in again"):
        return "error"
    if status in ("Choose member", "Partial refresh", "Not found"):
        return "attention"
    return "muted"
