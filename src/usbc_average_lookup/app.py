from __future__ import annotations

import tkinter as tk
from collections import Counter
from collections.abc import Callable
from multiprocessing import freeze_support
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from usbc_average_lookup.models import (
    AverageCondition,
    AverageOption,
    AverageSource,
    InputBowler,
    LookupResult,
    LookupStatus,
    Member,
)
from usbc_average_lookup.services.auth import (
    AuthSession,
    AuthState,
    WebViewAuthenticator,
    clear_legacy_sign_in_data,
)
from usbc_average_lookup.services.average_options import (
    BulkReviewCandidate,
    bulk_review_candidates,
    filter_average_options,
)
from usbc_average_lookup.services.bowl_api import HttpBowlApi
from usbc_average_lookup.services.exports import ExportSubset, export_results, select_results
from usbc_average_lookup.services.input_parser import (
    parse_input_file,
    workbook_sheet_names,
)
from usbc_average_lookup.services.lookup import (
    confirm_average,
    look_up_all,
    look_up_bowler,
    resolve_selected_member,
)

COLORS = {
    "navy": "#0C2744",
    "navy_soft": "#153252",
    "canvas": "#13191F",
    "surface": "#1D252C",
    "surface_raised": "#263139",
    "line": "#3A4852",
    "text": "#EDF4FA",
    "muted": "#C6D3DE",
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
        self.title("Average Assistant")
        self.geometry("1280x800")
        self.minsize(980, 650)
        self.configure(background=COLORS["canvas"])
        self.results: list[LookupResult] = []
        self.bowlers: list[InputBowler] = []
        self.selected_path: Path | None = None
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.signing_in = False
        clear_legacy_sign_in_data()
        self.authenticator = WebViewAuthenticator()
        self.api: HttpBowlApi | None = None
        self._configure_style()
        self._build_ui()
        self._render_results()
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
            "TButton",
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            padding=(12, 8),
        )
        style.map("TButton", background=[("active", COLORS["navy_soft"])])
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
        style.map(
            "Warm.TButton",
            background=[("active", "#C98447"), ("disabled", COLORS["surface_raised"])],
            foreground=[("disabled", COLORS["muted"])],
        )
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
        style.configure(
            "TSpinbox",
            fieldbackground=COLORS["surface_raised"],
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["text"],
            bordercolor=COLORS["line"],
            insertcolor=COLORS["text"],
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("readonly", COLORS["surface_raised"])],
            foreground=[("disabled", COLORS["muted"])],
        )
        style.configure(
            "TCheckbutton",
            background=COLORS["canvas"],
            foreground=COLORS["text"],
        )
        style.map(
            "TCheckbutton",
            background=[("active", COLORS["canvas"])],
            foreground=[("disabled", COLORS["muted"])],
        )

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Surface.TFrame", padding=(28, 20, 28, 16))
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Average Assistant", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="USBC bowler averages, ready for your league.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.auth_status = ttk.Label(header, text="Not signed in", style="Status.TLabel")
        self.auth_status.grid(row=0, column=1, rowspan=2, padx=(18, 0), sticky="e")
        self.sign_in_button = ttk.Button(
            header,
            text="Sign in to BOWL.com",
            command=self._start_sign_in,
            style="Primary.TButton",
        )
        self.sign_in_button.grid(row=0, column=2, rowspan=2, padx=(10, 0), sticky="e")
        self.sign_out_button = ttk.Button(
            header,
            text="Sign out",
            command=self._sign_out,
            state=tk.DISABLED,
        )
        self.sign_out_button.grid(row=0, column=3, rowspan=2, padx=(8, 0), sticky="e")

        steps = ttk.Frame(header, style="Surface.TFrame")
        steps.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        for column, (number, title) in enumerate(
            (("1", "Sign in"), ("2", "Choose roster"), ("3", "Review"), ("4", "Save"))
        ):
            steps.columnconfigure(column, weight=1)
            label = ttk.Label(
                steps,
                text=f"{number}   {title}",
                style="Surface.TLabel",
                anchor="w",
            )
            label.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))

        main = ttk.Frame(self, style="App.TFrame", padding=(28, 20, 28, 24))
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
        self.notebook.bind(
            "<<NotebookTabChanged>>", lambda _event: self._update_selection_buttons()
        )
        self.all_tab = ttk.Frame(self.notebook, style="Surface.TFrame")
        self.fixes_tab = ttk.Frame(self.notebook, style="Surface.TFrame")
        self.review_tab = ttk.Frame(self.notebook, style="Surface.TFrame")
        self.notebook.add(self.all_tab, text="All results")
        self.notebook.add(self.fixes_tab, text="Fixes needed (0)")
        self.notebook.add(self.review_tab, text="Review averages (0)")
        self.all_table = self._make_result_table(self.all_tab)
        self.fixes_table = self._make_result_table(self.fixes_tab)
        self._build_review_panel()

        footer = ttk.Frame(main, style="App.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        self.help_label = ttk.Label(
            footer,
            text="Every selected average must be reviewed before it is ready.",
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
        self.fix_button = ttk.Button(
            footer,
            text="Fix selected",
            command=self._fix_selected,
            state=tk.DISABLED,
        )
        self.fix_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.review_button = ttk.Button(
            footer,
            text="Review selected",
            command=self._review_selected,
            state=tk.DISABLED,
        )
        self.review_button.pack(side=tk.RIGHT, padx=(0, 8))

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
        table.tag_configure("review", foreground=COLORS["gold"])
        table.tag_configure("issue", foreground=COLORS["red"])
        table.tag_configure("inactive", foreground=COLORS["gold"])
        table.bind("<Double-1>", lambda _event: self._open_selected_result())
        table.bind("<<TreeviewSelect>>", lambda _event: self._update_selection_buttons())
        return table

    def _build_review_panel(self) -> None:
        self.review_tab.columnconfigure(0, weight=2)
        self.review_tab.columnconfigure(1, weight=3)
        self.review_tab.rowconfigure(1, weight=1)

        self.review_progress = ttk.Label(
            self.review_tab,
            text="No averages waiting for review",
            style="Surface.TLabel",
            padding=(12, 10),
        )
        self.review_progress.grid(row=0, column=0, columnspan=2, sticky="ew")

        list_frame = ttk.Frame(self.review_tab, style="Surface.TFrame", padding=(8, 0, 4, 8))
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.review_table = ttk.Treeview(
            list_frame,
            columns=("name", "average", "games", "source", "review"),
            show="headings",
        )
        for column, label, width in (
            ("name", "Bowler", 185),
            ("average", "Avg", 55),
            ("games", "Games", 55),
            ("source", "Source", 130),
            ("review", "Review", 90),
        ):
            self.review_table.heading(column, text=label)
            self.review_table.column(column, width=width, minwidth=50, anchor="w")
        review_scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.review_table.yview
        )
        self.review_table.configure(yscrollcommand=review_scrollbar.set)
        self.review_table.grid(row=0, column=0, sticky="nsew")
        review_scrollbar.grid(row=0, column=1, sticky="ns")
        self.review_table.tag_configure("ready", foreground=COLORS["green"])
        self.review_table.tag_configure("review", foreground=COLORS["gold"])
        self.review_table.bind("<<TreeviewSelect>>", self._review_selection_changed)

        detail = ttk.Frame(self.review_tab, style="App.TFrame", padding=(12, 8, 8, 8))
        detail.grid(row=1, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(4, weight=1)
        self.review_name = ttk.Label(
            detail,
            text="Select a bowler",
            style="Muted.TLabel",
            font=("Segoe UI", 14, "bold"),
        )
        self.review_name.grid(row=0, column=0, sticky="w")

        filters = ttk.Frame(detail, style="App.TFrame")
        filters.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        for column in range(4):
            filters.columnconfigure(column, weight=1)
        self.minimum_games_var = tk.StringVar(value="21")
        self.season_filter_var = tk.StringVar(value="All seasons")
        self.condition_filter_var = tk.StringVar(value="All types")
        self.league_filter_var = tk.StringVar(value="All leagues")
        self.center_filter_var = tk.StringVar(value="")
        self.sort_filter_var = tk.StringVar(value="Newest")
        self.include_rerates_var = tk.BooleanVar(value=True)
        self.qualifying_only_var = tk.BooleanVar(value=True)

        ttk.Label(filters, text="Minimum games", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        minimum_games = ttk.Spinbox(
            filters,
            from_=0,
            to=999,
            textvariable=self.minimum_games_var,
            width=8,
            command=self._render_average_choices,
        )
        minimum_games.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        minimum_games.bind("<KeyRelease>", lambda _event: self._render_average_choices())

        ttk.Label(filters, text="Season", style="Muted.TLabel").grid(
            row=0, column=1, sticky="w"
        )
        self.season_filter = ttk.Combobox(
            filters, textvariable=self.season_filter_var, state="readonly"
        )
        self.season_filter.grid(row=1, column=1, sticky="ew", padx=(0, 6))
        self.season_filter.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_average_choices()
        )

        ttk.Label(filters, text="Average type", style="Muted.TLabel").grid(
            row=0, column=2, sticky="w"
        )
        self.condition_filter = ttk.Combobox(
            filters,
            textvariable=self.condition_filter_var,
            values=("All types", *(condition.value for condition in AverageCondition)),
            state="readonly",
        )
        self.condition_filter.grid(row=1, column=2, sticky="ew", padx=(0, 6))
        self.condition_filter.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_average_choices()
        )

        ttk.Label(filters, text="League", style="Muted.TLabel").grid(
            row=0, column=3, sticky="w"
        )
        self.league_filter = ttk.Combobox(
            filters, textvariable=self.league_filter_var, state="readonly"
        )
        self.league_filter.grid(row=1, column=3, sticky="ew")
        self.league_filter.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_average_choices()
        )

        ttk.Label(filters, text="Center / association", style="Muted.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(7, 0)
        )
        center_entry = ttk.Entry(filters, textvariable=self.center_filter_var)
        center_entry.grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 6))
        center_entry.bind("<KeyRelease>", lambda _event: self._render_average_choices())
        ttk.Label(filters, text="Sort", style="Muted.TLabel").grid(
            row=2, column=2, sticky="w", pady=(7, 0)
        )
        sort_filter = ttk.Combobox(
            filters,
            textvariable=self.sort_filter_var,
            values=("Newest", "Highest average", "Most games"),
            state="readonly",
        )
        sort_filter.grid(row=3, column=2, sticky="ew", padx=(0, 6))
        sort_filter.bind("<<ComboboxSelected>>", lambda _event: self._render_average_choices())
        checks = ttk.Frame(filters, style="App.TFrame")
        checks.grid(row=2, column=3, rowspan=2, sticky="w", pady=(7, 0))
        ttk.Checkbutton(
            checks,
            text="Include rerates",
            variable=self.include_rerates_var,
            command=self._render_average_choices,
        ).pack(anchor="w")
        ttk.Checkbutton(
            checks,
            text="Qualifying only",
            variable=self.qualifying_only_var,
            command=self._render_average_choices,
        ).pack(anchor="w")

        self.review_guidance = ttk.Label(detail, text="", style="Muted.TLabel")
        self.review_guidance.grid(row=2, column=0, sticky="ew", pady=(5, 5))
        option_frame = ttk.Frame(detail, style="Surface.TFrame")
        option_frame.grid(row=4, column=0, sticky="nsew")
        option_frame.columnconfigure(0, weight=1)
        option_frame.rowconfigure(0, weight=1)
        self.average_table = ttk.Treeview(
            option_frame,
            columns=("average", "games", "season", "type", "source", "details"),
            show="headings",
        )
        for column, label, width in (
            ("average", "Avg", 50),
            ("games", "Games", 55),
            ("season", "Season", 70),
            ("type", "Type", 75),
            ("source", "Source", 95),
            ("details", "League / tournament", 220),
        ):
            self.average_table.heading(column, text=label)
            self.average_table.column(column, width=width, minwidth=45, anchor="w")
        option_scrollbar = ttk.Scrollbar(
            option_frame, orient=tk.VERTICAL, command=self.average_table.yview
        )
        self.average_table.configure(yscrollcommand=option_scrollbar.set)
        self.average_table.grid(row=0, column=0, sticky="nsew")
        option_scrollbar.grid(row=0, column=1, sticky="ns")
        self.average_table.bind("<<TreeviewSelect>>", lambda _event: self._update_confirm_button())
        self.average_table.bind("<Double-1>", lambda _event: self._confirm_selected_average())

        review_actions = ttk.Frame(detail, style="App.TFrame")
        review_actions.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.review_warning = ttk.Label(review_actions, text="", style="Muted.TLabel")
        self.review_warning.pack(side=tk.LEFT)
        self.next_review_button = ttk.Button(
            review_actions,
            text="Next unreviewed",
            command=self._next_unreviewed,
            state=tk.DISABLED,
        )
        self.next_review_button.pack(side=tk.RIGHT)
        self.confirm_average_button = ttk.Button(
            review_actions,
            text="Confirm selected and go to next",
            command=self._confirm_selected_average,
            style="Warm.TButton",
            state=tk.DISABLED,
        )
        self.confirm_average_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.bulk_review_button = ttk.Button(
            review_actions,
            text="Bulk review…",
            command=self._open_bulk_review,
            state=tk.DISABLED,
        )
        self.bulk_review_button.pack(side=tk.RIGHT, padx=(0, 8))

    def _start_sign_in(self) -> None:
        self.authenticator.sign_out()
        self.signing_in = True
        self.sign_in_button.configure(state=tk.DISABLED)
        self.sign_out_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="Finish signing in…")
        Thread(target=self._sign_in_worker, daemon=True).start()

    def _sign_in_worker(self) -> None:
        try:
            session = self.authenticator.sign_in()
        except Exception as error:
            self.after(0, self._sign_in_failed, str(error))
            return
        self.after(0, self._signed_in, session)

    def _signed_in(self, session: AuthSession) -> None:
        self.signing_in = False
        self.auth_session = session
        self.api = HttpBowlApi(lambda: self.auth_session.bearer_token)
        self.auth_status.configure(text="Signed in — ready")
        self.sign_in_button.configure(text="Sign in again", state=tk.NORMAL)
        self.sign_out_button.configure(state=tk.NORMAL)
        self._update_action_states()

    def _sign_in_failed(self, message: str) -> None:
        self.signing_in = False
        self.auth_status.configure(text="Sign-in not completed")
        self.sign_in_button.configure(state=tk.NORMAL)
        self.sign_out_button.configure(state=tk.DISABLED)
        messagebox.showerror("Could not sign in", message)

    def _sign_out(self) -> None:
        self.authenticator.sign_out()
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.api = None
        self.auth_status.configure(text="Not signed in")
        self.sign_in_button.configure(text="Sign in to BOWL.com", state=tk.NORMAL)
        self.sign_out_button.configure(state=tk.DISABLED)
        self._update_action_states()

    def _close_app(self) -> None:
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
        Thread(target=self._lookup_worker, daemon=True).start()

    def _lookup_worker(self) -> None:
        assert self.api is not None
        results = look_up_all(self.api, self.bowlers)
        self.after(0, self._lookup_finished, results)

    def _lookup_finished(self, results: list[LookupResult]) -> None:
        self.results = results
        self._render_results()
        self.auth_status.configure(text="Lookup complete")
        self._update_action_states()

    def _start_single_lookup(self) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        if self.bowlers and len(self.bowlers) != len(self.results):
            replace = messagebox.askyesno(
                "Roster not processed",
                "The selected roster has not been looked up. Start a separate single lookup?",
            )
            if not replace:
                return
            self.bowlers = []
            self.results = []
            self.selected_path = None
        bowler = SingleLookupDialog(self).show()
        if bowler is None:
            return
        self.single_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="Looking up one bowler…")
        Thread(target=self._single_lookup_worker, args=(bowler,), daemon=True).start()

    def _single_lookup_worker(self, bowler: InputBowler) -> None:
        assert self.api is not None
        result = look_up_bowler(self.api, bowler)
        self.after(0, self._single_lookup_finished, bowler, result)

    def _single_lookup_finished(
        self, bowler: InputBowler, result: LookupResult
    ) -> None:
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
        if result.needs_review:
            index = len(self.results) - 1
            self.notebook.select(self.review_tab)
            self.review_table.selection_set(str(index))
            self.review_table.focus(str(index))
            self.review_table.see(str(index))
        elif result.needs_resolution:
            index = len(self.results) - 1
            self.notebook.select(self.fixes_tab)
            self.fixes_table.selection_set(str(index))
            self.fixes_table.focus(str(index))
            self.fixes_table.see(str(index))

    def _clear_results(self) -> None:
        self.results = []
        self._render_results()
        self.auth_status.configure(
            text="Signed in — ready" if self.api is not None else "Not signed in"
        )
        self._update_action_states()

    def _render_results(self) -> None:
        selected_review = self.review_table.selection()
        selected_review_id = selected_review[0] if selected_review else None
        for table in (self.all_table, self.fixes_table, self.review_table):
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
            if result.needs_resolution:
                self.fixes_table.insert(
                    "", tk.END, iid=str(index), values=values, tags=(tag,)
                )
            if result.available_averages:
                selected = next(
                    (
                        option
                        for option in result.available_averages
                        if option.key == result.selected_average_key
                    ),
                    None,
                )
                source = selected.source_detail if selected else "—"
                review_state = "Confirmed" if result.reviewed else "Required"
                self.review_table.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=(
                        result.input_name,
                        result.average if result.average is not None else "—",
                        result.games if result.games is not None else "—",
                        source,
                        review_state,
                    ),
                    tags=("ready" if result.reviewed else "review",),
                )
        issue_count = sum(result.needs_resolution for result in self.results)
        review_count = sum(result.needs_review for result in self.results)
        reviewed_count = sum(
            result.reviewed and bool(result.available_averages) for result in self.results
        )
        review_total = sum(bool(result.available_averages) for result in self.results)
        self.notebook.tab(self.fixes_tab, text=f"Fixes needed ({issue_count})")
        self.notebook.tab(self.review_tab, text=f"Review averages ({review_count})")
        self.review_progress.configure(
            text=(
                f"Reviewed: {reviewed_count} of {review_total}   •   "
                f"{review_count} still require confirmation"
                if review_total
                else "No averages waiting for review"
            )
        )
        if not self.results:
            self.summary.configure(text="No current results")
        else:
            counts = Counter(result.status for result in self.results)
            ready = counts[LookupStatus.FOUND]
            inactive = sum(result.confirmed_inactive for result in self.results)
            self.summary.configure(
                text=(
                    f"{len(self.results)} processed   •   {ready} ready   •   "
                    f"{review_count} need review   •   {issue_count} need fixes   •   "
                    f"{inactive} inactive"
                )
            )
        if selected_review_id and self.review_table.exists(selected_review_id):
            self.review_table.selection_set(selected_review_id)
            self.review_table.focus(selected_review_id)
        self._update_selection_buttons()
        self._review_selection_changed()

    @staticmethod
    def _result_tag(result: LookupResult) -> str:
        if result.status is LookupStatus.FOUND:
            return "ready"
        if result.status is LookupStatus.REVIEW_REQUIRED:
            return "inactive" if result.member and not result.member.active else "review"
        if result.status is LookupStatus.INACTIVE_MEMBER:
            return "inactive"
        return "issue"

    def _active_table(self) -> ttk.Treeview:
        if self.notebook.select() == str(self.fixes_tab):
            return self.fixes_table
        if self.notebook.select() == str(self.review_tab):
            return self.review_table
        return self.all_table

    def _selected_result_index(self) -> int | None:
        table = self._active_table()
        selected = table.selection()
        return int(selected[0]) if selected else None

    def _update_selection_buttons(self) -> None:
        index = self._selected_result_index()
        can_fix = index is not None and self.results[index].needs_resolution
        can_review = index is not None and bool(self.results[index].available_averages)
        self.fix_button.configure(state=tk.NORMAL if can_fix else tk.DISABLED)
        self.review_button.configure(state=tk.NORMAL if can_review else tk.DISABLED)

    def _open_selected_result(self) -> None:
        index = self._selected_result_index()
        if index is None:
            return
        if self.results[index].available_averages:
            self._show_review_index(index)
        elif self.results[index].needs_resolution:
            self._fix_selected()

    def _fix_selected(self) -> None:
        index = self._selected_result_index()
        if index is None or not self.results[index].needs_resolution:
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
        Thread(
            target=self._fix_worker,
            args=(index, bowler, None, move_next),
            daemon=True,
        ).start()

    def _resolve_issue_member(
        self, index: int, bowler: InputBowler, member: Member, move_next: bool
    ) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        self.auth_status.configure(text=f"Updating {bowler.name}…")
        Thread(
            target=self._fix_worker,
            args=(index, bowler, member, move_next),
            daemon=True,
        ).start()

    def _fix_worker(
        self,
        index: int,
        bowler: InputBowler,
        member: Member | None,
        move_next: bool,
    ) -> None:
        assert self.api is not None
        result = (
            resolve_selected_member(self.api, bowler, member)
            if member is not None
            else look_up_bowler(self.api, bowler)
        )
        self.after(0, self._fix_finished, index, bowler, result, move_next)

    def _fix_finished(
        self,
        index: int,
        bowler: InputBowler,
        result: LookupResult,
        move_next: bool,
    ) -> None:
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
            index for index, result in enumerate(self.results) if result.needs_resolution
        ]
        if not unresolved:
            if any(result.needs_review for result in self.results):
                self.notebook.select(self.review_tab)
                self._next_unreviewed()
            else:
                messagebox.showinfo("All fixed", "No results currently need attention.")
            return
        index = next((item for item in unresolved if item > after_index), unresolved[0])
        self.notebook.select(self.fixes_tab)
        self.fixes_table.selection_set(str(index))
        self.fixes_table.focus(str(index))
        self.fixes_table.see(str(index))
        self._fix_selected()

    def _review_selected(self) -> None:
        index = self._selected_result_index()
        if index is not None and self.results[index].available_averages:
            self._show_review_index(index)

    def _show_review_index(self, index: int) -> None:
        self.notebook.select(self.review_tab)
        self.review_table.selection_set(str(index))
        self.review_table.focus(str(index))
        self.review_table.see(str(index))
        self._review_selection_changed()

    def _review_selection_changed(self, _event=None) -> None:
        selected = self.review_table.selection()
        self.average_table.delete(*self.average_table.get_children())
        self.review_option_map: dict[str, AverageOption] = {}
        if not selected:
            self.review_name.configure(text="Select a bowler")
            self.review_guidance.configure(text="")
            self.review_warning.configure(text="")
            self.confirm_average_button.configure(state=tk.DISABLED)
            self.next_review_button.configure(
                state=(
                    tk.NORMAL
                    if any(result.needs_review for result in self.results)
                    else tk.DISABLED
                )
            )
            self.bulk_review_button.configure(
                state=(
                    tk.NORMAL
                    if any(result.needs_review for result in self.results)
                    else tk.DISABLED
                )
            )
            return

        result = self.results[int(selected[0])]
        inactive_note = " — inactive member" if result.member and not result.member.active else ""
        self.review_name.configure(text=f"{result.input_name}{inactive_note}")
        seasons = sorted(
            {option.season for option in result.available_averages if option.season},
            reverse=True,
        )
        season_values = ("All seasons", *seasons)
        self.season_filter.configure(values=season_values)
        if self.season_filter_var.get() not in season_values:
            self.season_filter_var.set("All seasons")
        leagues = sorted(
            {option.league for option in result.available_averages if option.league},
            key=str.casefold,
        )
        league_values = ("All leagues", *leagues)
        self.league_filter.configure(values=league_values)
        if self.league_filter_var.get() not in league_values:
            self.league_filter_var.set("All leagues")
        self._render_average_choices()

    def _render_average_choices(self) -> None:
        if not hasattr(self, "average_table"):
            return
        self.average_table.delete(*self.average_table.get_children())
        self.review_option_map = {}
        selected_result = self.review_table.selection()
        if not selected_result:
            self._update_confirm_button()
            return
        result = self.results[int(selected_result[0])]
        try:
            minimum_games = int(self.minimum_games_var.get())
            if minimum_games < 0:
                raise ValueError
        except ValueError:
            self.review_guidance.configure(text="Minimum games must be zero or greater.")
            self._update_confirm_button()
            return
        season = self.season_filter_var.get()
        condition = self.condition_filter_var.get()
        league = self.league_filter_var.get()
        choices = filter_average_options(
            result.available_averages,
            minimum_games=minimum_games,
            season="" if season == "All seasons" else season,
            condition="" if condition == "All types" else condition,
            league="" if league == "All leagues" else league,
            center=self.center_filter_var.get(),
            include_rerates=self.include_rerates_var.get(),
            qualifying_only=self.qualifying_only_var.get(),
            sort_by=self.sort_filter_var.get(),
        )
        for index, option in enumerate(choices):
            iid = f"option-{index}"
            self.review_option_map[iid] = option
            details = option.source_detail
            location = " / ".join(
                part for part in (option.center, option.association) if part
            )
            if location:
                details = f"{details} — {location}"
            self.average_table.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    option.average,
                    option.games if option.games is not None else "—",
                    option.season or "—",
                    option.condition.value,
                    option.source.value,
                    details,
                ),
            )
        matching = next(
            (
                iid
                for iid, option in self.review_option_map.items()
                if option.key == result.selected_average_key
            ),
            None,
        )
        if matching is None and choices:
            matching = "option-0"
        if matching:
            self.average_table.selection_set(matching)
            self.average_table.focus(matching)
            self.average_table.see(matching)
        hidden = len(result.available_averages) - len(choices)
        message = f"Showing {len(choices)} of {len(result.available_averages)} available averages"
        if hidden:
            message += f" — {hidden} hidden by filters"
        if not choices:
            message += ". Turn off ‘Qualifying only’ or change the filters."
        self.review_guidance.configure(text=message)
        self.next_review_button.configure(
            state=tk.NORMAL if any(item.needs_review for item in self.results) else tk.DISABLED
        )
        self.bulk_review_button.configure(
            state=tk.NORMAL if any(item.needs_review for item in self.results) else tk.DISABLED
        )
        self._update_confirm_button()

    def _selected_average_option(self) -> AverageOption | None:
        selected = self.average_table.selection()
        return self.review_option_map.get(selected[0]) if selected else None

    def _update_confirm_button(self) -> None:
        option = self._selected_average_option()
        self.confirm_average_button.configure(
            state=tk.NORMAL if option is not None else tk.DISABLED
        )
        warning = ""
        selected_result = self.review_table.selection()
        result = self.results[int(selected_result[0])] if selected_result else None
        if result and result.member and not result.member.active:
            warning = "Inactive member — confirmation is still required"
        if option and option.source is AverageSource.RERATE:
            warning = "Rerated/adjusted average — verify the event rule"
        elif option and option.games is not None:
            try:
                minimum_games = int(self.minimum_games_var.get())
            except ValueError:
                minimum_games = 0
            if option.games < minimum_games:
                warning = f"Below the {minimum_games}-game minimum"
        self.review_warning.configure(text=warning)

    def _confirm_selected_average(self) -> None:
        selected_result = self.review_table.selection()
        option = self._selected_average_option()
        if not selected_result or option is None:
            return
        index = int(selected_result[0])
        try:
            self.results[index] = confirm_average(self.results[index], option)
        except ValueError as error:
            messagebox.showerror("Could not confirm average", str(error))
            return
        self._render_results()
        self.auth_status.configure(text="Average confirmed")
        self._show_review_index(index)
        self.after(50, self._next_unreviewed)

    def _next_unreviewed(self) -> None:
        unresolved = [
            index for index, result in enumerate(self.results) if result.needs_review
        ]
        if not unresolved:
            self.next_review_button.configure(state=tk.DISABLED)
            messagebox.showinfo("Review complete", "Every available average has been confirmed.")
            return
        selected = self.review_table.selection()
        current = int(selected[0]) if selected else -1
        index = next((item for item in unresolved if item > current), unresolved[0])
        self._show_review_index(index)

    def _open_bulk_review(self) -> None:
        try:
            minimum_games = int(self.minimum_games_var.get())
            if minimum_games < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Minimum games",
                "Minimum games must be zero or greater.",
            )
            return
        season = self.season_filter_var.get()
        condition = self.condition_filter_var.get()
        league = self.league_filter_var.get()
        candidates, excluded = bulk_review_candidates(
            self.results,
            minimum_games=minimum_games,
            season="" if season == "All seasons" else season,
            condition="" if condition == "All types" else condition,
            league="" if league == "All leagues" else league,
            center=self.center_filter_var.get(),
            include_rerates=self.include_rerates_var.get(),
            qualifying_only=self.qualifying_only_var.get(),
            sort_by=self.sort_filter_var.get(),
        )
        if not candidates:
            messagebox.showinfo(
                "No bulk candidates",
                "No unreviewed bowlers match the current filters. "
                "Change the filters or continue individual review.",
            )
            return
        BulkReviewDialog(
            self,
            candidates,
            self.results,
            excluded,
            minimum_games,
            on_confirm=self._confirm_bulk_review,
        )

    def _confirm_bulk_review(self, candidates: list[BulkReviewCandidate]) -> None:
        confirmed = 0
        for candidate in candidates:
            result = self.results[candidate.result_index]
            if not result.needs_review:
                continue
            self.results[candidate.result_index] = confirm_average(result, candidate.option)
            confirmed += 1
        self._render_results()
        self.auth_status.configure(text=f"{confirmed} averages confirmed")
        if any(result.needs_review for result in self.results):
            self.notebook.select(self.review_tab)
            self._next_unreviewed()
        else:
            messagebox.showinfo(
                "Review complete",
                "Every available average has been confirmed.",
            )

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
        if subset is ExportSubset.READY and unresolved:
            messagebox.showwarning(
                "Review not complete",
                f"{unresolved} bowlers still need review or correction. "
                "The ready roster cannot be saved until every bowler is confirmed.",
            )
            return
        if subset is ExportSubset.FULL and unresolved:
            proceed = messagebox.askyesno(
                "Save an unfinished draft?",
                f"{unresolved} bowlers still need review or correction. "
                "Save the full roster as an unfinished draft anyway?",
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


class BulkReviewDialog(tk.Toplevel):
    def __init__(
        self,
        parent: AverageLookupApp,
        candidates: list[BulkReviewCandidate],
        results: list[LookupResult],
        excluded: int,
        minimum_games: int,
        on_confirm: Callable[[list[BulkReviewCandidate]], None],
    ) -> None:
        super().__init__(parent)
        self.candidates = candidates
        self.results = results
        self.excluded = excluded
        self.minimum_games = minimum_games
        self.on_confirm = on_confirm
        self.title("Bulk average review")
        self.geometry("1180x680")
        self.minsize(900, 540)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)
        ttk.Label(
            content,
            text="Bulk review",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text=(
                "Review the proposed value in every selected row. Nothing is confirmed "
                "until you press the final button."
            ),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 4))
        self.summary_label = ttk.Label(content, text="", style="Muted.TLabel")
        self.summary_label.grid(row=2, column=0, sticky="ew", pady=(5, 8))

        table_frame = ttk.Frame(content, style="Surface.TFrame")
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            table_frame,
            columns=(
                "bowler",
                "average",
                "games",
                "season",
                "type",
                "source",
                "choices",
                "warnings",
            ),
            show="headings",
            selectmode="extended",
        )
        for column, label, width in (
            ("bowler", "Bowler", 190),
            ("average", "Avg", 55),
            ("games", "Games", 60),
            ("season", "Season", 75),
            ("type", "Type", 85),
            ("source", "Source", 160),
            ("choices", "Matches", 65),
            ("warnings", "Warnings", 230),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=50, anchor="w")
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.table.tag_configure("clean", foreground=COLORS["green"])
        self.table.tag_configure("warning", foreground=COLORS["gold"])
        for position, candidate in enumerate(self.candidates):
            result = self.results[candidate.result_index]
            option = candidate.option
            self.table.insert(
                "",
                tk.END,
                iid=str(position),
                values=(
                    result.input_name,
                    option.average,
                    option.games if option.games is not None else "—",
                    option.season or "—",
                    option.condition.value,
                    option.source_detail,
                    candidate.choice_count,
                    "; ".join(candidate.warnings) or "One qualifying choice",
                ),
                tags=("clean" if candidate.is_clean else "warning",),
            )
        self.table.bind("<<TreeviewSelect>>", lambda _event: self._update_selection())

        controls = ttk.Frame(content, style="App.TFrame")
        controls.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(
            controls,
            text="Select one-choice rows",
            command=self._select_clean,
        ).pack(side=tk.LEFT)
        ttk.Button(
            controls,
            text="Select all displayed",
            command=lambda: self.table.selection_set(self.table.get_children()),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            controls,
            text="Clear selection",
            command=lambda: self.table.selection_remove(self.table.selection()),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        self.confirm_button = ttk.Button(
            controls,
            text="Confirm selected bowlers",
            command=self._confirm,
            style="Warm.TButton",
            state=tk.DISABLED,
        )
        self.confirm_button.pack(side=tk.RIGHT, padx=(0, 8))
        self._update_selection()

    def _select_clean(self) -> None:
        clean = [
            str(index)
            for index, candidate in enumerate(self.candidates)
            if candidate.is_clean
        ]
        self.table.selection_set(clean)
        self._update_selection()

    def _update_selection(self) -> None:
        selected_count = len(self.table.selection())
        remaining = len(self.candidates) + self.excluded - selected_count
        self.summary_label.configure(
            text=(
                f"{selected_count} selected   •   {len(self.candidates)} displayed   •   "
                f"{remaining} will remain for individual review   •   "
                f"minimum {self.minimum_games} games"
            )
        )
        self.confirm_button.configure(
            state=tk.NORMAL if selected_count else tk.DISABLED
        )

    def _confirm(self) -> None:
        selected = [self.candidates[int(iid)] for iid in self.table.selection()]
        if not selected:
            return
        proceed = messagebox.askyesno(
            "Confirm bulk averages",
            f"Mark the displayed average as reviewed for {len(selected)} bowlers?\n\n"
            "Unselected bowlers will remain in the individual review queue.",
            parent=self,
        )
        if not proceed:
            return
        self.destroy()
        self.on_confirm(selected)


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
        candidate_frame.rowconfigure(0, weight=1)
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
        self.candidate_table.grid(row=0, column=0, sticky="nsew")
        for index, member in enumerate(self.result.candidates):
            association = ", ".join(
                part for part in (member.association, member.association_state) if part
            )
            self.candidate_table.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    member.display_name,
                    f"{member.prefix}-{member.suffix}",
                    association or "—",
                    "Active" if member.active else "Inactive",
                ),
            )
        if self.result.candidates:
            self.candidate_table.selection_set("0")
            self.candidate_table.focus("0")
        else:
            guidance = (
                "Enter a member ID above and retry"
                if self.result.status is LookupStatus.API_ERROR
                and not self.result.membership_id
                else "Edit above and retry"
            )
            self.candidate_table.insert(
                "", tk.END, values=("No selectable matches", "—", guidance, "—")
            )

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
