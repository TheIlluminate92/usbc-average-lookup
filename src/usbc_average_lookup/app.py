from __future__ import annotations

import tkinter as tk
from collections import Counter
from collections.abc import Callable
from multiprocessing import freeze_support
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus, Member
from usbc_average_lookup.registration_ui import RegistrationDesk
from usbc_average_lookup.services.auth import (
    AuthSession,
    AuthState,
    SignInCancelledError,
    WebViewAuthenticator,
    clear_legacy_sign_in_data,
)
from usbc_average_lookup.services.bowl_api import HttpBowlApi
from usbc_average_lookup.services.exports import ExportSubset, export_results, select_results
from usbc_average_lookup.services.input_parser import (
    parse_input_file,
    workbook_sheet_names,
)
from usbc_average_lookup.services.lookup import (
    look_up_all,
    look_up_bowler,
    resolve_selected_member,
)
from usbc_average_lookup.services.registration import (
    RegistrationDataError,
    RegistrationStore,
)
from usbc_average_lookup.workspace import LeagueWorkspaceContext, ScoreSheetEditLocks

COLORS = {
    "navy": "#0C2744",
    "navy_soft": "#153252",
    "canvas": "#13191F",
    "surface": "#1D252C",
    "surface_raised": "#263139",
    "line": "#3A4852",
    "text": "#EDF4FA",
    "muted": "#9FB0BF",
    "wood": "#E6A260",
    "green": "#72D6A5",
    "green_bg": "#183B2D",
    "red": "#FF9999",
    "red_bg": "#472525",
    "gold": "#F1C76D",
    "gold_bg": "#40341C",
}


class AverageLookupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bowling Manager")
        self.geometry("1080x720")
        self.minsize(820, 580)
        self.configure(background=COLORS["canvas"])
        self.results: list[LookupResult] = []
        self.bowlers: list[InputBowler] = []
        self.lookup_generation = 0
        self.selected_path: Path | None = None
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.signing_in = False
        clear_legacy_sign_in_data()
        self.authenticator = WebViewAuthenticator()
        self.api: HttpBowlApi | None = None
        self.registration_data_error = ""
        try:
            self.registration_store: RegistrationStore | None = RegistrationStore()
        except RegistrationDataError as error:
            self.registration_store = None
            self.registration_data_error = str(error)
        self.workspace_context = LeagueWorkspaceContext()
        self.score_edit_locks = ScoreSheetEditLocks()
        self.detached_desks: dict[tk.Toplevel, RegistrationDesk] = {}
        self.workspace_tab_desks: dict[ttk.Frame, RegistrationDesk] = {}
        self.workspace_tab_kinds: dict[ttk.Frame, str] = {}
        self.workspace_tab_unsubscribers: dict[ttk.Frame, Callable[[], None]] = {}
        self._refresh_pending = False
        self._configure_style()
        self._build_ui()
        self._unsubscribe_store = (
            self.registration_store.add_change_listener(self._store_changed)
            if self.registration_store is not None
            else None
        )
        self._render_results()
        if self.registration_data_error:
            self.after(
                0,
                messagebox.showerror,
                "Registration data needs attention",
                self.registration_data_error
                + "\n\nThe file was left unchanged. Registration is disabled until it is repaired.",
            )
        self.protocol("WM_DELETE_WINDOW", self._close_app)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=COLORS["canvas"], foreground=COLORS["text"])
        style.configure("App.TFrame", background=COLORS["canvas"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure(
            "Title.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Segoe UI", 24, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Surface.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["canvas"],
            foreground=COLORS["muted"],
        )
        style.configure(
            "Status.TLabel",
            background=COLORS["green_bg"],
            foreground=COLORS["green"],
            padding=(12, 7),
        )
        style.configure(
            "ToolbarStatus.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            padding=(6, 4),
        )
        style.configure(
            "TButton",
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            padding=(12, 8),
        )
        style.map("TButton", background=[("active", COLORS["navy_soft"])])
        style.configure(
            "Toolbar.TButton",
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            padding=(9, 5),
        )
        style.configure(
            "Toolbar.TMenubutton",
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            padding=(9, 5),
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["navy_soft"],
            foreground=COLORS["text"],
            bordercolor=COLORS["navy_soft"],
        )
        style.map("Primary.TButton", background=[("active", COLORS["navy"])])
        style.configure(
            "Warm.TButton",
            background=COLORS["wood"],
            foreground="#1B120A",
            bordercolor=COLORS["wood"],
        )
        style.map("Warm.TButton", background=[("active", "#C98447")])
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface_raised"],
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["text"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", COLORS["surface_raised"]),
                ("disabled", COLORS["surface"]),
            ],
            foreground=[
                ("readonly", COLORS["text"]),
                ("disabled", COLORS["muted"]),
            ],
            selectbackground=[("readonly", COLORS["navy_soft"])],
            selectforeground=[("readonly", COLORS["text"])],
        )
        style.configure(
            "TNotebook",
            background=COLORS["canvas"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            padding=(18, 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["navy_soft"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "Workspace.TNotebook",
            background=COLORS["canvas"],
            borderwidth=0,
            tabmargins=(10, 7, 0, 0),
        )
        style.configure(
            "Workspace.TNotebook.Tab",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            padding=(22, 10),
        )
        style.map(
            "Workspace.TNotebook.Tab",
            background=[("selected", COLORS["navy_soft"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            rowheight=34,
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["navy_soft"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["surface_raised"],
            foreground=COLORS["muted"],
            bordercolor=COLORS["line"],
            padding=(8, 8),
        )
        style.map("Treeview.Heading", background=[("active", COLORS["surface_raised"])])
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface_raised"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
        )

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Surface.TFrame", padding=(14, 8))
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Bowling Manager",
            style="Surface.TLabel",
            font=("Segoe UI", 12, "bold"),
        ).grid(
            row=0, column=0, sticky="w"
        )
        self.auth_status = ttk.Label(
            header, text="BOWL.com: signed out", style="ToolbarStatus.TLabel"
        )
        self.auth_status.grid(row=0, column=1, padx=(14, 0), sticky="e")
        self.sign_in_button = ttk.Button(
            header,
            text="Sign in to BOWL.com",
            command=self._start_sign_in,
            style="Toolbar.TButton",
        )
        self.sign_in_button.grid(row=0, column=2, padx=(7, 0), sticky="e")
        self.sign_out_button = ttk.Button(
            header,
            text="Sign out",
            command=self._sign_out,
            state=tk.DISABLED,
            style="Toolbar.TButton",
        )
        self.sign_out_button.grid(row=0, column=3, padx=(7, 0), sticky="e")

        self.workspace = ttk.Notebook(self, style="Workspace.TNotebook")
        self.workspace.pack(fill=tk.BOTH, expand=True)
        self.lookup_workspace = ttk.Frame(self.workspace, style="App.TFrame")
        self.league_workspace = ttk.Frame(self.workspace, style="App.TFrame")
        self.registration_workspace = ttk.Frame(self.workspace, style="App.TFrame")
        self.workspace.add(self.registration_workspace, text="Registration")
        self.workspace.add(self.league_workspace, text="League Manager")
        self.workspace.add(self.lookup_workspace, text="Average lookup")
        self.workspace.enable_traversal()
        self.workspace.bind(
            "<<NotebookTabChanged>>", lambda _event: self._workspace_tab_changed()
        )
        self.workspace.bind("<Button-1>", self._workspace_tab_clicked, add=True)
        self.workspace.bind("<Button-2>", self._workspace_tab_middle_clicked)
        self.workspace.bind("<Button-3>", self._show_workspace_tab_menu)
        self.bind("<Control-t>", self._new_tab_shortcut)
        self.bind("<Control-w>", self._close_tab_shortcut)

        main = ttk.Frame(
            self.lookup_workspace, style="App.TFrame", padding=(28, 20, 28, 24)
        )
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        filebar = ttk.Frame(main, style="Surface.TFrame", padding=14)
        filebar.grid(row=0, column=0, sticky="ew")
        filebar.columnconfigure(0, weight=1)
        self.file_label = ttk.Label(
            filebar,
            text="No roster selected",
            style="Surface.TLabel",
            font=("Segoe UI", 10, "bold"),
        )
        self.file_label.grid(row=0, column=0, sticky="w")
        self.file_detail = ttk.Label(
            filebar,
            text="CSV, TSV, text, JSON, or Excel",
            style="Subtitle.TLabel",
        )
        self.file_detail.grid(row=1, column=0, sticky="w", pady=(2, 0))
        controls = ttk.Frame(filebar, style="Surface.TFrame")
        controls.grid(row=0, column=1, rowspan=2, sticky="e", padx=(14, 0))
        self.single_button = ttk.Button(
            controls,
            text="Single lookup",
            command=self._start_single_lookup,
            state=tk.DISABLED,
        )
        self.single_button.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(controls, text="Choose roster", command=self._choose_file).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        self.clear_button = ttk.Button(
            controls, text="Clear results", command=self._clear_results, state=tk.DISABLED
        )
        self.clear_button.pack(side=tk.LEFT, padx=(0, 8))
        self.lookup_button = ttk.Button(
            controls,
            text="Look up averages",
            command=self._start_lookup,
            state=tk.DISABLED,
            style="Primary.TButton",
        )
        self.lookup_button.pack(side=tk.LEFT)

        self.summary = ttk.Label(main, text="No current results", style="Muted.TLabel")
        self.summary.grid(row=1, column=0, sticky="ew", pady=(16, 8))

        self.notebook = ttk.Notebook(main)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self._update_fix_button())
        self.all_tab = ttk.Frame(self.notebook, style="Surface.TFrame")
        self.fixes_tab = ttk.Frame(self.notebook, style="Surface.TFrame")
        self.notebook.add(self.all_tab, text="All results")
        self.notebook.add(self.fixes_tab, text="Fixes needed (0)")
        self.all_table = self._make_result_table(self.all_tab)
        self.fixes_table = self._make_result_table(self.fixes_tab)

        footer = ttk.Frame(main, style="App.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        self.help_label = ttk.Label(
            footer,
            text="Double-click a highlighted row to fix it.",
            style="Muted.TLabel",
        )
        self.help_label.pack(side=tk.LEFT)
        self.save_button = ttk.Button(
            footer,
            text="Save results",
            command=self._save_results,
            state=tk.DISABLED,
            style="Warm.TButton",
        )
        self.save_button.pack(side=tk.RIGHT)
        self.player_list_button = ttk.Button(
            footer,
            text="Add to player list",
            command=self._add_results_to_player_list,
            state=tk.DISABLED,
        )
        self.player_list_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.fix_button = ttk.Button(
            footer,
            text="Fix selected",
            command=self._fix_selected,
            state=tk.DISABLED,
        )
        self.fix_button.pack(side=tk.RIGHT, padx=(0, 8))

        self.registration_desk = RegistrationDesk(
            self.league_workspace,
            self.registration_store,
            lambda: self.api,
            self._set_status,
            registration_parent=self.registration_workspace,
            workspace_context=self.workspace_context,
            open_registration_callback=self._show_registration,
            detach_callback=lambda section: self._open_management_tab(
                section, self.workspace_context.competition_id
            ),
            popout_callback=self._open_management_window,
            score_edit_locks=self.score_edit_locks,
        )
        self.registration_desk.pack(fill=tk.BOTH, expand=True)

    def _set_status(self, text: str) -> None:
        self.auth_status.configure(text=text)

    def _workspace_tab_changed(self) -> None:
        selected = self.workspace.select()
        label = self.workspace.tab(selected, "text") if selected else "Bowling Manager"
        self.title(f"{label} — Bowling Manager")

    def _show_workspace_tab_menu(self, event: tk.Event) -> None:
        try:
            index = self.workspace.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        self.workspace.select(index)
        page = self._workspace_page(index)
        label = str(self.workspace.tab(index, "text"))
        menu = tk.Menu(self, tearoff=False)
        if page in self.workspace_tab_desks:
            menu.add_command(
                label="Pop out into separate window",
                command=lambda: self._pop_out_workspace_tab(page),
            )
            menu.add_separator()
            menu.add_command(
                label="Close tab", command=lambda: self._close_workspace_tab(page)
            )
        elif label == "Registration":
            menu.add_command(
                label="Open another Registration tab",
                command=self._open_registration_tab,
            )
            menu.add_command(
                label="Pop out into separate window",
                command=self._open_registration_window,
            )
        elif label == "League Manager":
            menu.add_command(
                label="Open current view in another tab",
                command=self._open_current_workspace_tab,
            )
            menu.add_command(
                label="Pop out current view",
                command=lambda: self._open_management_window(
                    self._current_management_section()
                ),
            )
        else:
            menu.add_command(
                label="Average lookup stays in the main window", state=tk.DISABLED
            )
        menu.tk_popup(event.x_root, event.y_root)

    def _workspace_page(self, index: int) -> ttk.Frame:
        return self.nametowidget(self.workspace.tabs()[index])

    def _workspace_tab_clicked(self, event: tk.Event) -> str | None:
        try:
            index = self.workspace.index(f"@{event.x},{event.y}")
            page = self._workspace_page(index)
        except (IndexError, KeyError, tk.TclError):
            return None
        if page in self.workspace_tab_desks and self._near_tab_right_edge(
            index, event.x, event.y
        ):
            self.after_idle(self._close_workspace_tab, page)
            return "break"
        return None

    def _near_tab_right_edge(self, index: int, x: int, y: int) -> bool:
        for offset in range(1, 29):
            try:
                if self.workspace.index(f"@{x + offset},{y}") != index:
                    return True
            except tk.TclError:
                return True
        return False

    def _workspace_tab_middle_clicked(self, event: tk.Event) -> str | None:
        try:
            index = self.workspace.index(f"@{event.x},{event.y}")
            page = self._workspace_page(index)
        except (IndexError, KeyError, tk.TclError):
            return None
        if page in self.workspace_tab_desks:
            self._close_workspace_tab(page)
            return "break"
        return None

    def _new_tab_shortcut(self, _event: tk.Event) -> str:
        self._open_current_workspace_tab()
        return "break"

    def _close_tab_shortcut(self, _event: tk.Event) -> str | None:
        selected = self.workspace.select()
        if not selected:
            return None
        page = self.nametowidget(selected)
        if page in self.workspace_tab_desks:
            self._close_workspace_tab(page)
            return "break"
        return None

    def _show_registration(self) -> None:
        self.workspace.select(self.registration_workspace)

    def _current_management_section(self) -> str:
        selected_tab = self.registration_desk.section_tabs.select()
        return (
            str(self.registration_desk.section_tabs.tab(selected_tab, "text"))
            if selected_tab
            else "League home"
        )

    def _open_current_workspace_tab(self) -> None:
        selected = self.workspace.select()
        if selected == str(self.registration_workspace):
            self._open_registration_tab()
        elif selected == str(self.league_workspace):
            self._open_management_tab(self._current_management_section())
        elif selected:
            page = self.nametowidget(selected)
            desk = self.workspace_tab_desks.get(page)
            if desk is None:
                self._open_registration_tab()
            elif self.workspace_tab_kinds.get(page) == "registration":
                self._open_registration_tab()
            else:
                current_tab = desk.section_tabs.select()
                section = (
                    str(desk.section_tabs.tab(current_tab, "text"))
                    if current_tab
                    else "League home"
                )
                self._open_management_tab(
                    section, desk.workspace_context.competition_id
                )

    def _open_registration_tab(self) -> None:
        page = ttk.Frame(self.workspace, style="App.TFrame")
        hidden_management_host = ttk.Frame(page, style="App.TFrame")
        context = LeagueWorkspaceContext(self.workspace_context.competition_id)
        desk = RegistrationDesk(
            hidden_management_host,
            self.registration_store,
            lambda: self.api,
            self._set_status,
            registration_parent=page,
            workspace_context=context,
            detach_callback=lambda section: self._open_management_tab(
                section, context.competition_id
            ),
            popout_callback=self._open_management_window,
            score_edit_locks=self.score_edit_locks,
        )
        self.workspace_tab_desks[page] = desk
        self.workspace_tab_kinds[page] = "registration"
        self.workspace.add(page, text="Registration  ×")
        self.workspace.select(page)

    def _open_management_tab(
        self, section: str = "", competition_id: str = ""
    ) -> None:
        page = ttk.Frame(self.workspace, style="App.TFrame")
        hidden_registration_host = ttk.Frame(page, style="App.TFrame")
        context = LeagueWorkspaceContext(
            competition_id or self.workspace_context.competition_id
        )
        desk = RegistrationDesk(
            page,
            self.registration_store,
            lambda: self.api,
            self._set_status,
            registration_parent=hidden_registration_host,
            workspace_context=context,
            open_registration_callback=self._open_registration_tab,
            detach_callback=lambda next_section: self._open_management_tab(
                next_section, context.competition_id
            ),
            popout_callback=self._open_management_window,
            score_edit_locks=self.score_edit_locks,
        )
        desk.pack(fill=tk.BOTH, expand=True)
        desk.select_section(section or "League home")
        self.workspace_tab_desks[page] = desk
        self.workspace_tab_kinds[page] = "management"
        self.workspace.add(page, text="League Manager  ×")
        desk.section_tabs.bind(
            "<<NotebookTabChanged>>",
            lambda _event, selected_page=page: self._update_workspace_tab_title(
                selected_page
            ),
            add=True,
        )
        self.workspace_tab_unsubscribers[page] = context.subscribe(
            lambda _competition_id, selected_page=page: self.after_idle(
                self._update_workspace_tab_title, selected_page
            )
        )
        self._update_workspace_tab_title(page)
        self.workspace.select(page)

    def _update_workspace_tab_title(self, page: ttk.Frame) -> None:
        desk = self.workspace_tab_desks.get(page)
        if desk is None or not page.winfo_exists():
            return
        selected = desk.section_tabs.select()
        section = (
            str(desk.section_tabs.tab(selected, "text"))
            if selected
            else "League home"
        )
        competition = next(
            (
                item
                for item in (
                    self.registration_store.competitions
                    if self.registration_store
                    else []
                )
                if item.id == desk.workspace_context.competition_id
            ),
            None,
        )
        prefix = competition.name if competition is not None else "League"
        title = f"{prefix} · {section}"
        if len(title) > 38:
            title = title[:35].rstrip() + "…"
        self.workspace.tab(page, text=f"{title}  ×")

    def _close_workspace_tab(self, page: ttk.Frame) -> None:
        unsubscribe = self.workspace_tab_unsubscribers.pop(page, None)
        if unsubscribe is not None:
            unsubscribe()
        desk = self.workspace_tab_desks.pop(page, None)
        self.workspace_tab_kinds.pop(page, None)
        if desk is not None:
            desk.close()
        if page.winfo_exists():
            self.workspace.forget(page)
            page.destroy()

    def _pop_out_workspace_tab(self, page: ttk.Frame) -> None:
        desk = self.workspace_tab_desks.get(page)
        if desk is None:
            return
        competition_id = desk.workspace_context.competition_id
        if self.workspace_tab_kinds.get(page) == "registration":
            self._open_registration_window(competition_id)
        else:
            selected = desk.section_tabs.select()
            section = (
                str(desk.section_tabs.tab(selected, "text"))
                if selected
                else "League home"
            )
            self._open_management_window(section, competition_id)
        self._close_workspace_tab(page)

    def _open_registration_window(self, competition_id: str = "") -> None:
        window = tk.Toplevel(self)
        window.title("Registration — Bowling Manager")
        window.geometry("1100x720")
        window.minsize(860, 580)
        window.configure(background=COLORS["canvas"])
        registration_host = ttk.Frame(window, style="App.TFrame")
        registration_host.pack(fill=tk.BOTH, expand=True)
        hidden_management_host = ttk.Frame(window, style="App.TFrame")
        context = LeagueWorkspaceContext(
            competition_id or self.workspace_context.competition_id
        )
        desk = RegistrationDesk(
            hidden_management_host,
            self.registration_store,
            lambda: self.api,
            self._set_status,
            registration_parent=registration_host,
            workspace_context=context,
            detach_callback=lambda section: self._open_management_tab(
                section, context.competition_id
            ),
            popout_callback=self._open_management_window,
            score_edit_locks=self.score_edit_locks,
            reattach_callback=lambda section, competition_id: self._reattach_detached(
                window, section, competition_id
            ),
        )
        self._register_detached_window(window, desk)

    def _open_management_window(
        self, section: str = "", competition_id: str = ""
    ) -> None:
        window = tk.Toplevel(self)
        window.title("League Manager — Bowling Manager")
        window.geometry("1180x760")
        window.minsize(900, 620)
        window.configure(background=COLORS["canvas"])
        hidden_registration_host = ttk.Frame(window, style="App.TFrame")
        context = LeagueWorkspaceContext(
            competition_id or self.workspace_context.competition_id
        )
        desk = RegistrationDesk(
            window,
            self.registration_store,
            lambda: self.api,
            self._set_status,
            registration_parent=hidden_registration_host,
            workspace_context=context,
            open_registration_callback=self._open_registration_tab,
            detach_callback=lambda next_section: self._open_management_tab(
                next_section, context.competition_id
            ),
            popout_callback=self._open_management_window,
            score_edit_locks=self.score_edit_locks,
            reattach_callback=lambda selected_section, competition_id: (
                self._reattach_detached(window, selected_section, competition_id)
            ),
        )
        desk.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        desk.select_section(section)
        self._register_detached_window(window, desk)

    def _register_detached_window(
        self, window: tk.Toplevel, desk: RegistrationDesk
    ) -> None:
        self.detached_desks[window] = desk

        window.protocol("WM_DELETE_WINDOW", lambda: self._close_detached_window(window))

    def _reattach_detached(
        self, window: tk.Toplevel, section: str, competition_id: str
    ) -> None:
        if competition_id:
            self.workspace_context.select(competition_id)
        if section == "Registration":
            self.workspace.select(self.registration_workspace)
        else:
            self.registration_desk.select_section(section)
            self.workspace.select(self.league_workspace)
        self.deiconify()
        self.lift()
        self.focus_force()
        self._close_detached_window(window)

    def _close_detached_window(self, window: tk.Toplevel) -> None:
        detached = self.detached_desks.pop(window, None)
        if detached is not None:
            detached.close()
        if window.winfo_exists():
            window.destroy()

    def _store_changed(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self.after_idle(self._refresh_open_desks)

    def _refresh_open_desks(self) -> None:
        self._refresh_pending = False
        self.registration_desk.refresh()
        for page, desk in tuple(self.workspace_tab_desks.items()):
            if page.winfo_exists():
                desk.refresh()
                if self.workspace_tab_kinds.get(page) == "management":
                    self._update_workspace_tab_title(page)
        for window, desk in tuple(self.detached_desks.items()):
            if window.winfo_exists():
                desk.refresh()

    def _make_result_table(self, parent: ttk.Frame) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        table = ttk.Treeview(
            parent,
            columns=("name", "member_id", "average", "status", "notes"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("name", "Name", 205, True),
            ("member_id", "Member ID", 125, False),
            ("average", "Average", 75, False),
            ("status", "Status", 125, False),
            ("notes", "Notes", 310, True),
        ):
            table.heading(column, text=label)
            table.column(column, width=width, minwidth=70, stretch=stretch, anchor="w")
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        table.tag_configure("ready", foreground=COLORS["green"])
        table.tag_configure("issue", foreground=COLORS["red"])
        table.tag_configure("inactive", foreground=COLORS["gold"])
        table.bind("<Double-1>", lambda _event: self._fix_selected())
        table.bind("<<TreeviewSelect>>", lambda _event: self._update_fix_button())
        return table

    def _start_sign_in(self) -> None:
        self.authenticator.sign_out()
        self.signing_in = True
        self.sign_in_button.configure(state=tk.DISABLED)
        self.sign_out_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="BOWL.com: finish signing in…")
        Thread(target=self._sign_in_worker, daemon=True).start()

    def _sign_in_worker(self) -> None:
        try:
            session = self.authenticator.sign_in()
        except SignInCancelledError:
            self.after(0, self._sign_in_cancelled)
            return
        except Exception as error:
            self.after(0, self._sign_in_failed, str(error))
            return
        self.after(0, self._signed_in, session)

    def _signed_in(self, session: AuthSession) -> None:
        self.signing_in = False
        self.auth_session = session
        self.api = HttpBowlApi(lambda: self.auth_session.bearer_token)
        self.auth_status.configure(text="BOWL.com: ready")
        self.sign_in_button.configure(text="Sign in again", state=tk.NORMAL)
        self.sign_out_button.configure(state=tk.NORMAL)
        self._update_action_states()
        self._refresh_desk_auth_states()

    def _sign_in_failed(self, message: str) -> None:
        self._restore_sign_in_controls()
        messagebox.showerror("Could not sign in", message)

    def _sign_in_cancelled(self) -> None:
        self._restore_sign_in_controls()

    def _restore_sign_in_controls(self) -> None:
        self.signing_in = False
        signed_in = self.api is not None
        self.auth_status.configure(
            text="BOWL.com: ready" if signed_in else "BOWL.com: signed out"
        )
        self.sign_in_button.configure(
            text="Sign in again" if signed_in else "Sign in to BOWL.com",
            state=tk.NORMAL,
        )
        self.sign_out_button.configure(state=tk.NORMAL if signed_in else tk.DISABLED)
        self._update_action_states()
        self._refresh_desk_auth_states()

    def _refresh_desk_auth_states(self) -> None:
        self.registration_desk.refresh_auth_state()
        for desk in self.workspace_tab_desks.values():
            desk.refresh_auth_state()
        for desk in self.detached_desks.values():
            desk.refresh_auth_state()

    def _sign_out(self) -> None:
        self.authenticator.sign_out()
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.api = None
        self.auth_status.configure(text="BOWL.com: signed out")
        self.sign_in_button.configure(text="Sign in to BOWL.com", state=tk.NORMAL)
        self.sign_out_button.configure(state=tk.DISABLED)
        self._update_action_states()
        self._refresh_desk_auth_states()

    def _close_app(self) -> None:
        if self._unsubscribe_store is not None:
            self._unsubscribe_store()
        for page in tuple(self.workspace_tab_desks):
            self._close_workspace_tab(page)
        for window, desk in tuple(self.detached_desks.items()):
            desk.close()
            window.destroy()
        self.detached_desks.clear()
        self.registration_desk.close()
        self.authenticator.sign_out()
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.api = None
        self.destroy()

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose bowler roster",
            filetypes=(
                ("Supported rosters", "*.csv *.tsv *.txt *.json *.xlsx"),
                ("Excel workbook", "*.xlsx"),
                ("JSON file", "*.json"),
                ("Delimited text", "*.csv *.tsv *.txt"),
                ("All files", "*.*"),
            ),
        )
        if not selected:
            return
        path = Path(selected)
        sheet_name = None
        try:
            if path.suffix.casefold() == ".xlsx":
                sheets = workbook_sheet_names(path)
                if len(sheets) > 1:
                    sheet_name = SheetPickerDialog(self, sheets).show()
                    if sheet_name is None:
                        return
            bowlers = parse_input_file(path, sheet_name)
            if not bowlers:
                raise ValueError("The selected file does not contain any bowlers")
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror("Could not read roster", str(error))
            return
        self.selected_path = path
        self.lookup_generation += 1
        self._close_issue_dialogs()
        self.bowlers = bowlers
        self.results = []
        self.file_label.configure(text=path.name)
        detail = f"{len(bowlers)} bowlers loaded"
        if sheet_name:
            detail += f" from {sheet_name}"
        self.file_detail.configure(text=detail)
        self._render_results()
        self._update_action_states()

    def _start_lookup(self) -> None:
        if not self.bowlers:
            messagebox.showwarning("No roster", "Choose a bowler roster first.")
            return
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        self.lookup_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="Looking up averages…")
        self.lookup_generation += 1
        generation = self.lookup_generation
        Thread(
            target=self._lookup_worker,
            args=(self.api, generation, list(self.bowlers)),
            daemon=True,
        ).start()

    def _lookup_worker(
        self,
        api: HttpBowlApi,
        generation: int,
        bowlers: list[InputBowler],
    ) -> None:
        results = look_up_all(api, bowlers)
        self.after(0, self._lookup_finished, generation, results)

    def _lookup_finished(
        self, generation: int, results: list[LookupResult]
    ) -> None:
        if generation != self.lookup_generation:
            return
        self.results = results
        self._render_results()
        self.auth_status.configure(text="Lookup complete")
        self._update_action_states()

    def _start_single_lookup(self) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        replace_roster = False
        if self.bowlers and len(self.bowlers) != len(self.results):
            replace_roster = messagebox.askyesno(
                "Roster not processed",
                "The selected roster has not been looked up. Start a separate single lookup?",
            )
            if not replace_roster:
                return
        bowler = SingleLookupDialog(self).show()
        if bowler is None:
            return
        if replace_roster:
            self.bowlers = []
            self.results = []
            self.selected_path = None
            self._close_issue_dialogs()
        self.single_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="Looking up one bowler…")
        self.lookup_generation += 1
        generation = self.lookup_generation
        Thread(
            target=self._single_lookup_worker,
            args=(self.api, generation, bowler),
            daemon=True,
        ).start()

    def _single_lookup_worker(
        self, api: HttpBowlApi, generation: int, bowler: InputBowler
    ) -> None:
        result = look_up_bowler(api, bowler)
        self.after(0, self._single_lookup_finished, generation, bowler, result)

    def _single_lookup_finished(
        self, generation: int, bowler: InputBowler, result: LookupResult
    ) -> None:
        if generation != self.lookup_generation:
            return
        self.bowlers.append(bowler)
        self.results.append(result)
        if self.selected_path is None:
            self.file_label.configure(text="Manual lookups")
            self.file_detail.configure(text=f"{len(self.bowlers)} bowlers added individually")
        else:
            self.file_detail.configure(
                text=f"{len(self.bowlers)} total bowlers, including manual lookups"
            )
        self._render_results()
        self.auth_status.configure(text="Single lookup complete")
        self._update_action_states()
        if result.needs_attention:
            index = len(self.results) - 1
            self.notebook.select(self.fixes_tab)
            self.fixes_table.selection_set(str(index))
            self.fixes_table.focus(str(index))
            self.fixes_table.see(str(index))

    def _clear_results(self) -> None:
        self.lookup_generation += 1
        self._close_issue_dialogs()
        self.results = []
        self._render_results()
        self.auth_status.configure(
            text="Signed in — ready" if self.api is not None else "Not signed in"
        )
        self._update_action_states()

    def _render_results(self) -> None:
        for table in (self.all_table, self.fixes_table):
            table.delete(*table.get_children())
        for index, result in enumerate(self.results):
            values = (
                result.input_name,
                result.membership_id or "—",
                result.average if result.average is not None else "—",
                result.status.value,
                result.note,
            )
            tag = self._result_tag(result)
            self.all_table.insert("", tk.END, iid=str(index), values=values, tags=(tag,))
            if result.needs_attention:
                self.fixes_table.insert(
                    "", tk.END, iid=str(index), values=values, tags=(tag,)
                )
        issue_count = sum(result.needs_attention for result in self.results)
        self.notebook.tab(self.fixes_tab, text=f"Fixes needed ({issue_count})")
        if not self.results:
            self.summary.configure(text="No current results")
        else:
            counts = Counter(result.status for result in self.results)
            ready = counts[LookupStatus.FOUND]
            inactive = sum(result.confirmed_inactive for result in self.results)
            self.summary.configure(
                text=(
                    f"{len(self.results)} processed   •   {ready} ready   •   "
                    f"{issue_count} need attention   •   {inactive} inactive"
                )
            )
        self._update_fix_button()

    @staticmethod
    def _result_tag(result: LookupResult) -> str:
        if result.status is LookupStatus.FOUND:
            return "ready"
        if result.status is LookupStatus.INACTIVE_MEMBER:
            return "inactive"
        return "issue"

    def _active_table(self) -> ttk.Treeview:
        return self.fixes_table if self.notebook.select() == str(self.fixes_tab) else self.all_table

    def _selected_result_index(self) -> int | None:
        table = self._active_table()
        selected = table.selection()
        return int(selected[0]) if selected else None

    def _update_fix_button(self) -> None:
        index = self._selected_result_index()
        can_fix = index is not None and self.results[index].needs_attention
        self.fix_button.configure(state=tk.NORMAL if can_fix else tk.DISABLED)

    def _fix_selected(self) -> None:
        index = self._selected_result_index()
        if index is None or not self.results[index].needs_attention:
            return
        IssueDialog(
            self,
            self.results[index],
            on_retry=lambda bowler, move_next: self._retry_issue(
                index, bowler, move_next
            ),
            on_member=lambda bowler, member, move_next: self._resolve_issue_member(
                index, bowler, member, move_next
            ),
        )

    def _retry_issue(
        self, index: int, bowler: InputBowler, move_next: bool
    ) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        self.auth_status.configure(text=f"Retrying {bowler.name}…")
        self.lookup_generation += 1
        generation = self.lookup_generation
        Thread(
            target=self._fix_worker,
            args=(self.api, generation, index, bowler, None, move_next),
            daemon=True,
        ).start()

    def _resolve_issue_member(
        self, index: int, bowler: InputBowler, member: Member, move_next: bool
    ) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        self.auth_status.configure(text=f"Updating {bowler.name}…")
        self.lookup_generation += 1
        generation = self.lookup_generation
        Thread(
            target=self._fix_worker,
            args=(self.api, generation, index, bowler, member, move_next),
            daemon=True,
        ).start()

    def _fix_worker(
        self,
        api: HttpBowlApi,
        generation: int,
        index: int,
        bowler: InputBowler,
        member: Member | None,
        move_next: bool,
    ) -> None:
        result = (
            resolve_selected_member(api, bowler, member)
            if member is not None
            else look_up_bowler(api, bowler)
        )
        self.after(
            0,
            self._fix_finished,
            generation,
            index,
            bowler,
            result,
            move_next,
        )

    def _fix_finished(
        self,
        generation: int,
        index: int,
        bowler: InputBowler,
        result: LookupResult,
        move_next: bool,
    ) -> None:
        if generation != self.lookup_generation:
            return
        self.bowlers[index] = bowler
        self.results[index] = result
        self._close_issue_dialogs()
        self._render_results()
        self.auth_status.configure(text="Result updated")
        self._update_action_states()
        if move_next:
            self.after(100, self._open_next_issue, index)

    def _close_issue_dialogs(self) -> None:
        for child in self.winfo_children():
            if isinstance(child, IssueDialog):
                child.destroy()

    def _open_next_issue(self, after_index: int) -> None:
        unresolved = [
            index for index, result in enumerate(self.results) if result.needs_attention
        ]
        if not unresolved:
            messagebox.showinfo("All fixed", "No results currently need attention.")
            return
        index = next((item for item in unresolved if item > after_index), unresolved[0])
        self.notebook.select(self.fixes_tab)
        self.fixes_table.selection_set(str(index))
        self.fixes_table.focus(str(index))
        self.fixes_table.see(str(index))
        self._fix_selected()

    def _save_results(self) -> None:
        if not self.results:
            messagebox.showwarning("No results", "Look up a bowler roster first.")
            return
        choice = SaveDialog(self, self.results).show()
        if choice is None:
            return
        subset, extension = choice
        selected_count = len(select_results(self.results, subset))
        unresolved = sum(result.needs_attention for result in self.results)
        if subset is ExportSubset.FULL and unresolved:
            proceed = messagebox.askyesno(
                "Unresolved bowlers",
                f"{unresolved} bowlers still need attention. Save the full roster anyway?",
            )
            if not proceed:
                return
        filetypes = {
            ".json": (("JSON file", "*.json"),),
            ".xlsx": (("Excel workbook", "*.xlsx"),),
            ".csv": (("CSV file", "*.csv"),),
            ".tsv": (("Tab-separated text", "*.tsv"),),
            ".txt": (("Text file", "*.txt"),),
        }
        selected = filedialog.asksaveasfilename(
            title=f"Save {subset.value.lower()}",
            defaultextension=extension,
            initialfile=f"bowler-averages{extension}",
            filetypes=filetypes[extension],
        )
        if not selected:
            return
        try:
            exported = export_results(Path(selected), self.results, subset)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not save results", str(error))
            return
        messagebox.showinfo(
            "Results saved",
            f"Saved {exported or selected_count} bowlers to {Path(selected).name}.",
        )

    def _add_results_to_player_list(self) -> None:
        if not self.results:
            messagebox.showwarning("No results", "Look up a bowler roster first.")
            return
        if self.registration_store is None:
            messagebox.showerror(
                "Player list unavailable",
                "The registration database could not be opened.",
            )
            return
        unresolved = sum(result.needs_attention for result in self.results)
        if unresolved and not messagebox.askyesno(
            "Unresolved players",
            f"{unresolved} player{'s' if unresolved != 1 else ''} do not have a "
            "confirmed match. Add them to the permanent player list anyway?",
        ):
            return
        players = [
            InputBowler(result.input_name, result.membership_id)
            for result in self.results
        ]
        try:
            added, reused = self.registration_store.import_players(players)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update player list", str(error))
            return
        self.registration_desk.refresh()
        messagebox.showinfo(
            "Player list updated",
            f"Added {added} new player{'s' if added != 1 else ''}; "
            f"{reused} existing player{'s were' if reused != 1 else ' was'} reused.",
        )

    def _update_action_states(self) -> None:
        self.single_button.configure(
            state=tk.NORMAL if self.api is not None else tk.DISABLED
        )
        self.lookup_button.configure(
            state=tk.NORMAL if self.bowlers and self.api is not None else tk.DISABLED
        )
        has_results = bool(self.results)
        self.clear_button.configure(state=tk.NORMAL if has_results else tk.DISABLED)
        self.save_button.configure(state=tk.NORMAL if has_results else tk.DISABLED)
        self.player_list_button.configure(
            state=(
                tk.NORMAL
                if has_results and self.registration_store is not None
                else tk.DISABLED
            )
        )


class SingleLookupDialog(tk.Toplevel):
    def __init__(self, parent: AverageLookupApp) -> None:
        super().__init__(parent)
        self.choice: InputBowler | None = None
        self.title("Single bowler lookup")
        self.geometry("520x310")
        self.resizable(False, False)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text="Look up one bowler",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            content,
            text="Enter a full name, a membership ID, or both.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 18))
        ttk.Label(content, text="Bowler name", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=6
        )
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(content, text="Member ID", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=6
        )
        self.id_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.id_var).grid(
            row=3, column=1, sticky="ew", pady=6
        )
        ttk.Label(
            content,
            text="Example: 1234-567890",
            style="Muted.TLabel",
        ).grid(row=4, column=1, sticky="w")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(28, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Look up bowler",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        membership_id = self.id_var.get().strip()
        if not name and not membership_id:
            messagebox.showwarning(
                "Name or ID needed",
                "Enter a bowler name or membership ID.",
                parent=self,
            )
            return
        self.choice = InputBowler(name, membership_id)
        self.destroy()

    def show(self) -> InputBowler | None:
        self.wait_window()
        return self.choice


class IssueDialog(tk.Toplevel):
    def __init__(
        self,
        parent: AverageLookupApp,
        result: LookupResult,
        on_retry: Callable[[InputBowler, bool], None],
        on_member: Callable[[InputBowler, Member, bool], None],
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.on_retry = on_retry
        self.on_member = on_member
        self.title("Fix bowler")
        self.geometry("720x500")
        self.minsize(620, 430)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(4, weight=1)
        ttk.Label(
            content,
            text=f"Fix: {self.result.input_name}",
            style="Muted.TLabel",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            content,
            text=self.result.note or self.result.status.value,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 18))

        ttk.Label(content, text="Bowler name", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.name_var = tk.StringVar(value=self.result.input_name)
        ttk.Entry(content, textvariable=self.name_var).grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Label(content, text="Member ID", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.id_var = tk.StringVar(value=self.result.membership_id)
        ttk.Entry(content, textvariable=self.id_var).grid(row=3, column=1, sticky="ew", pady=5)

        candidate_frame = ttk.Frame(content, style="Surface.TFrame", padding=8)
        candidate_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(14, 12))
        candidate_frame.columnconfigure(0, weight=1)
        candidate_frame.rowconfigure(1, weight=1)
        self.candidate_search_var = tk.StringVar()
        candidate_search_bar = ttk.Frame(candidate_frame, style="Surface.TFrame")
        candidate_search_bar.grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )
        candidate_search_bar.columnconfigure(1, weight=1)
        ttk.Label(
            candidate_search_bar,
            text="Filter matches",
            style="Surface.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        candidate_search = ttk.Entry(
            candidate_search_bar,
            textvariable=self.candidate_search_var,
        )
        candidate_search.grid(row=0, column=1, sticky="ew")
        candidate_search.bind("<KeyRelease>", lambda _event: self._render_candidates())
        self.candidate_table = ttk.Treeview(
            candidate_frame,
            columns=("name", "id", "association", "active"),
            show="headings",
            height=6,
        )
        for column, label, width in (
            ("name", "Member", 180),
            ("id", "Member ID", 120),
            ("association", "Association", 230),
            ("active", "Status", 75),
        ):
            self.candidate_table.heading(column, text=label)
            self.candidate_table.column(column, width=width, anchor="w")
        self.candidate_table.grid(row=1, column=0, sticky="nsew")
        candidate_scrollbar = ttk.Scrollbar(
            candidate_frame,
            orient=tk.VERTICAL,
            command=self.candidate_table.yview,
        )
        self.candidate_table.configure(yscrollcommand=candidate_scrollbar.set)
        candidate_scrollbar.grid(row=1, column=1, sticky="ns")

        self.next_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            content,
            text="Open the next item that needs attention",
            variable=self.next_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 12))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Retry search", command=self._retry).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.use_button = ttk.Button(
            buttons,
            text="Use selected member",
            command=self._use_member,
            style="Primary.TButton",
            state=tk.NORMAL if self.result.candidates else tk.DISABLED,
        )
        self.use_button.pack(side=tk.LEFT, padx=(8, 0))
        self._render_candidates()

    def _render_candidates(self) -> None:
        self.candidate_table.delete(*self.candidate_table.get_children())
        query = " ".join(self.candidate_search_var.get().split()).casefold()
        visible_ids: list[str] = []
        for index, member in enumerate(self.result.candidates):
            member_id = f"{member.prefix}-{member.suffix}"
            association = ", ".join(
                part for part in (member.association, member.association_state) if part
            )
            searchable = f"{member.display_name} {member_id} {association}".casefold()
            if query and query not in searchable:
                continue
            item_id = str(index)
            visible_ids.append(item_id)
            self.candidate_table.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    member.display_name,
                    member_id,
                    association or "—",
                    "Active" if member.active else "Inactive",
                ),
            )
        if visible_ids:
            self.candidate_table.selection_set(visible_ids[0])
            self.candidate_table.focus(visible_ids[0])
        else:
            guidance = (
                "No matches for this filter"
                if self.result.candidates
                else (
                    "Enter a member ID above and retry"
                    if self.result.status is LookupStatus.API_ERROR
                    and not self.result.membership_id
                    else "Edit above and retry"
                )
            )
            self.candidate_table.insert(
                "", tk.END, values=("No selectable matches", "—", guidance, "—")
            )
        if hasattr(self, "use_button"):
            self.use_button.configure(
                state=tk.NORMAL if visible_ids else tk.DISABLED
            )

    def _bowler(self) -> InputBowler | None:
        name = self.name_var.get().strip()
        membership_id = self.id_var.get().strip()
        if not name and not membership_id:
            messagebox.showwarning(
                "Name or ID needed",
                "Enter the bowler's name or membership ID.",
                parent=self,
            )
            return None
        return InputBowler(name, membership_id)

    def _retry(self) -> None:
        bowler = self._bowler()
        if bowler:
            self.on_retry(bowler, self.next_var.get())

    def _use_member(self) -> None:
        bowler = self._bowler()
        selected = self.candidate_table.selection()
        if bowler is None or not selected:
            return
        member = self.result.candidates[int(selected[0])]
        chosen = InputBowler(bowler.name, f"{member.prefix}-{member.suffix}")
        self.on_member(chosen, member, self.next_var.get())


class SaveDialog(tk.Toplevel):
    FORMATS = {
        "JSON — complete structured details": ".json",
        "Excel — easy to review": ".xlsx",
        "CSV — works almost anywhere": ".csv",
        "Tab-separated text": ".tsv",
        "Plain text": ".txt",
    }

    def __init__(self, parent: AverageLookupApp, results: list[LookupResult]) -> None:
        super().__init__(parent)
        self.results = results
        self.choice: tuple[ExportSubset, str] | None = None
        self.title("Save results")
        self.geometry("500x320")
        self.resizable(False, False)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            content,
            text="Save results",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(content, text="Which bowlers should be included?", style="Muted.TLabel").pack(
            anchor="w", pady=(18, 5)
        )
        self.subset_var = tk.StringVar(value=ExportSubset.FULL.value)
        subset_box = ttk.Combobox(
            content,
            textvariable=self.subset_var,
            values=[subset.value for subset in ExportSubset],
            state="readonly",
        )
        subset_box.pack(fill=tk.X)
        subset_box.bind("<<ComboboxSelected>>", lambda _event: self._update_count())
        ttk.Label(content, text="File type", style="Muted.TLabel").pack(
            anchor="w", pady=(14, 5)
        )
        self.format_var = tk.StringVar(value=next(iter(self.FORMATS)))
        ttk.Combobox(
            content,
            textvariable=self.format_var,
            values=list(self.FORMATS),
            state="readonly",
        ).pack(fill=tk.X)
        self.count_label = ttk.Label(content, text="", style="Muted.TLabel")
        self.count_label.pack(anchor="w", pady=(14, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.pack(side=tk.BOTTOM, anchor="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        self.continue_button = ttk.Button(
            buttons, text="Continue", command=self._accept, style="Warm.TButton"
        )
        self.continue_button.pack(side=tk.LEFT, padx=(8, 0))
        self._update_count()

    def _update_count(self) -> None:
        subset = ExportSubset(self.subset_var.get())
        count = len(select_results(self.results, subset))
        self.count_label.configure(text=f"{count} bowlers will be written")
        self.continue_button.configure(state=tk.NORMAL if count else tk.DISABLED)

    def _accept(self) -> None:
        self.choice = (
            ExportSubset(self.subset_var.get()),
            self.FORMATS[self.format_var.get()],
        )
        self.destroy()

    def show(self) -> tuple[ExportSubset, str] | None:
        self.wait_window()
        return self.choice


class SheetPickerDialog(tk.Toplevel):
    def __init__(self, parent: AverageLookupApp, sheets: list[str]) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.title("Choose Excel sheet")
        self.geometry("420x210")
        self.resizable(False, False)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            content,
            text="This workbook has more than one roster.",
            style="Muted.TLabel",
        ).pack(anchor="w")
        self.value = tk.StringVar(value=sheets[0])
        ttk.Combobox(
            content,
            textvariable=self.value,
            values=sheets,
            state="readonly",
        ).pack(fill=tk.X, pady=(14, 18))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.pack(anchor="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Use this sheet", command=self._accept).pack(
            side=tk.LEFT, padx=(8, 0)
        )

    def _accept(self) -> None:
        self.choice = self.value.get()
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.choice


def main() -> None:
    freeze_support()
    AverageLookupApp().mainloop()
