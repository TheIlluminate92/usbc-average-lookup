from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from queue import Queue
from threading import Thread
from tkinter import messagebox, simpledialog, ttk

from usbc_average_lookup.models import InputBowler, LookupResult, Member
from usbc_average_lookup.relationships_ui import (
    EntityKind,
    EntityRef,
    RelationshipBrowser,
)
from usbc_average_lookup.scoring_ui import LeagueScoringSettingsDialog, ScoringDesk
from usbc_average_lookup.services.bowl_api import BowlApi
from usbc_average_lookup.services.input_parser import parse_input_text
from usbc_average_lookup.services.lookup import look_up_bowler, resolve_selected_member
from usbc_average_lookup.services.registration import (
    BowlerProfile,
    Competition,
    CompetitionKind,
    PlayerPool,
    Registration,
    RegistrationDataError,
    RegistrationStore,
    RegistrationTarget,
    RegistrationView,
    RosterRole,
    Team,
)
from usbc_average_lookup.workspace import LeagueWorkspaceContext, ScoreSheetEditLocks

LookupTask = tuple[BowlApi, str, InputBowler]


class RegistrationDesk(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        store: RegistrationStore | None,
        api_provider: Callable[[], BowlApi | None],
        status_callback: Callable[[str], None],
        registration_parent: tk.Misc | None = None,
        workspace_context: LeagueWorkspaceContext | None = None,
        open_registration_callback: Callable[[], None] | None = None,
        detach_callback: Callable[[str], None] | None = None,
        score_edit_locks: ScoreSheetEditLocks | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame", padding=(28, 20, 28, 24))
        self.store = store
        self.api_provider = api_provider
        self.status_callback = status_callback
        self.workspace_context = workspace_context or LeagueWorkspaceContext()
        self.open_registration_callback = open_registration_callback
        self.detach_callback = detach_callback
        self.score_edit_locks = score_edit_locks or ScoreSheetEditLocks()
        self.competition_by_label: dict[str, Competition] = {}
        self.team_by_label: dict[str, str] = {}
        self.lookup_results: dict[str, LookupResult] = {}
        self.lookup_queue: Queue[LookupTask | None] = Queue()
        self.bulk_pending: set[str] = set()
        self.competition_var = tk.StringVar()
        self.team_filter_var = tk.StringVar(value="All teams")
        self.name_var = tk.StringVar()
        self.member_id_var = tk.StringVar()
        self.quick_team_var = tk.StringVar(value="Unassigned")
        self.registration_parent = registration_parent
        self._build()
        self._unsubscribe_context = self.workspace_context.subscribe(
            self._workspace_competition_changed
        )
        self.refresh()
        for _worker_number in range(2):
            Thread(target=self._lookup_queue_worker, daemon=True).start()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        management_context = ttk.Frame(
            self, style="Surface.TFrame", padding=(18, 12)
        )
        management_context.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        management_context.columnconfigure(1, weight=1)
        ttk.Label(
            management_context,
            text="Current league workspace",
            style="Surface.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.workspace_competition_box = ttk.Combobox(
            management_context,
            textvariable=self.competition_var,
            state="readonly",
        )
        self.workspace_competition_box.grid(row=0, column=1, sticky="ew")
        self.workspace_competition_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._competition_selected()
        )
        self.open_registration_button = ttk.Button(
            management_context,
            text="Register bowler",
            command=self._open_registration,
        )
        self.open_registration_button.grid(row=0, column=2, padx=(10, 0))
        self.detach_button = ttk.Button(
            management_context,
            text="Open view in new window",
            command=self._detach_current_section,
            state=tk.NORMAL if self.detach_callback else tk.DISABLED,
        )
        self.detach_button.grid(row=0, column=3, padx=(8, 0))

        self.section_tabs = ttk.Notebook(self)
        self.section_tabs.grid(row=1, column=0, sticky="nsew")
        registration_tab = ttk.Frame(
            self.registration_parent or self.section_tabs,
            style="App.TFrame",
            padding=(22, 16, 22, 20),
        )
        self.overview_tab = ttk.Frame(
            self.section_tabs, style="App.TFrame", padding=(22, 16, 22, 20)
        )
        self.players_tab = ttk.Frame(
            self.section_tabs, style="App.TFrame", padding=(22, 16, 22, 20)
        )
        self.teams_tab = ttk.Frame(
            self.section_tabs, style="App.TFrame", padding=(22, 16, 22, 20)
        )
        self.competitions_tab = ttk.Frame(
            self.section_tabs, style="App.TFrame", padding=(22, 16, 22, 20)
        )
        self.scores_tab = ttk.Frame(
            self.section_tabs, style="App.TFrame", padding=(22, 16, 22, 20)
        )
        self.rules_tab = ttk.Frame(
            self.section_tabs, style="App.TFrame", padding=(22, 16, 22, 20)
        )
        self.section_tabs.add(self.overview_tab, text="League home")
        self.section_tabs.add(self.teams_tab, text="Teams & roster")
        self.section_tabs.add(self.scores_tab, text="Scores & history")
        self.section_tabs.add(self.rules_tab, text="Rules & setup")
        self.section_tabs.add(self.players_tab, text="Player directory")
        self.section_tabs.add(self.competitions_tab, text="Leagues & seasons")
        if self.registration_parent is None:
            self.section_tabs.add(registration_tab, text="Registration")
        else:
            registration_tab.pack(fill=tk.BOTH, expand=True)

        registration_tab.columnconfigure(0, weight=1)
        registration_tab.rowconfigure(3, weight=1)

        heading = ttk.Frame(registration_tab, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(
            heading,
            text="Registration Desk",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text="Fast staff entry first. Self-registration can be added later.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(
            heading,
            text="New league or tournament",
            command=self._new_competition,
            style="Primary.TButton",
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        selector = ttk.Frame(registration_tab, style="Surface.TFrame", padding=14)
        selector.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        selector.columnconfigure(1, weight=1)
        ttk.Label(selector, text="Working on", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.competition_box = ttk.Combobox(
            selector,
            textvariable=self.competition_var,
            state="readonly",
        )
        self.competition_box.grid(row=0, column=1, sticky="ew")
        self.competition_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._competition_selected()
        )
        self.new_team_button = ttk.Button(selector, text="Add team", command=self._new_team)
        self.new_team_button.grid(row=0, column=2, padx=(10, 0))
        self.team_button = ttk.Button(
            selector, text="Register whole team", command=self._register_team
        )
        self.team_button.grid(row=0, column=3, padx=(8, 0))
        self.check_all_button = ttk.Button(
            selector, text="Check unverified", command=self._check_all
        )
        self.check_all_button.grid(row=0, column=4, padx=(8, 0))

        quick = ttk.Frame(registration_tab, style="Surface.TFrame", padding=14)
        quick.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        quick.columnconfigure(0, weight=2)
        quick.columnconfigure(1, weight=1)
        quick.columnconfigure(2, weight=1)
        ttk.Label(quick, text="Bowler name", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(quick, text="Member ID (optional)", style="Surface.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Label(quick, text="Team", style="Surface.TLabel").grid(
            row=0, column=2, sticky="w", padx=(10, 0)
        )
        self.name_entry = ttk.Entry(quick, textvariable=self.name_var)
        self.name_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        ttk.Entry(quick, textvariable=self.member_id_var).grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=(5, 0)
        )
        self.quick_team_box = ttk.Combobox(
            quick, textvariable=self.quick_team_var, state="readonly"
        )
        self.quick_team_box.grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(5, 0))
        self.add_button = ttk.Button(
            quick,
            text="Add to this league",
            command=self._quick_add,
            style="Warm.TButton",
        )
        self.add_button.grid(row=1, column=3, padx=(10, 0), pady=(5, 0))
        self.multi_add_button = ttk.Button(
            quick,
            text="Multiple leagues…",
            command=self._register_multiple,
        )
        self.multi_add_button.grid(row=1, column=4, padx=(8, 0), pady=(5, 0))
        self.name_entry.bind("<Return>", lambda _event: self._quick_add())

        table_frame = ttk.Frame(registration_tab, style="Surface.TFrame")
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)
        table_header = ttk.Frame(table_frame, style="Surface.TFrame", padding=(12, 9))
        table_header.grid(row=0, column=0, columnspan=2, sticky="ew")
        table_header.columnconfigure(0, weight=1)
        self.counter_label = ttk.Label(
            table_header, text="No registrations", style="Surface.TLabel"
        )
        self.counter_label.grid(row=0, column=0, sticky="w")
        ttk.Label(table_header, text="Show", style="Surface.TLabel").grid(
            row=0, column=1, padx=(12, 6)
        )
        self.team_filter_box = ttk.Combobox(
            table_header,
            textvariable=self.team_filter_var,
            state="readonly",
            width=22,
        )
        self.team_filter_box.grid(row=0, column=2)
        self.team_filter_box.bind("<<ComboboxSelected>>", lambda _event: self._render_rows())

        self.table = ttk.Treeview(
            table_frame,
            columns=("name", "member_id", "team", "average", "status", "notes"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("name", "Bowler", 190, True),
            ("member_id", "Member ID", 115, False),
            ("team", "Team", 155, True),
            ("average", "Average", 70, False),
            ("status", "Status", 155, False),
            ("notes", "Notes", 245, True),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=65, stretch=stretch, anchor="w")
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.table.tag_configure("ready", foreground="#72D6A5")
        self.table.tag_configure("attention", foreground="#F1C76D")
        self.table.tag_configure("error", foreground="#FF9999")
        self.table.tag_configure("withdrawn", foreground="#9FB0BF")
        self.table.bind("<<TreeviewSelect>>", lambda _event: self._update_row_actions())
        self.table.bind("<Double-1>", lambda _event: self._review_selected())

        footer = ttk.Frame(registration_tab, style="App.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            footer,
            text="Registrations save automatically. BOWL.com checks never block entry.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        self.withdraw_button = ttk.Button(
            footer, text="Withdraw selected", command=self._toggle_withdrawn, state=tk.DISABLED
        )
        self.withdraw_button.pack(side=tk.RIGHT)
        self.edit_button = ttk.Button(
            footer, text="Edit selected", command=self._edit_selected, state=tk.DISABLED
        )
        self.edit_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.review_button = ttk.Button(
            footer, text="Review / recheck", command=self._review_selected, state=tk.DISABLED
        )
        self.review_button.pack(side=tk.RIGHT, padx=(0, 8))

        self._build_overview_tab()
        self._build_players_tab()
        self._build_teams_tab()
        self._build_competitions_tab()
        self._build_rules_tab()
        self.scoring_desk = ScoringDesk(
            self.scores_tab,
            self.store,
            self.status_callback,
            workspace_context=self.workspace_context,
            edit_locks=self.score_edit_locks,
        )
        self.scoring_desk.pack(fill=tk.BOTH, expand=True)
        self.section_tabs.bind(
            "<<NotebookTabChanged>>", lambda _event: self.scoring_desk.refresh()
        )

    def _build_overview_tab(self) -> None:
        tab = self.overview_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)
        heading = ttk.Frame(tab, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        self.workspace_title_label = ttk.Label(
            heading,
            text="League home",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        )
        self.workspace_title_label.grid(row=0, column=0, sticky="w")
        self.workspace_detail_label = ttk.Label(
            heading,
            text="Choose a league or tournament above.",
            style="Muted.TLabel",
        )
        self.workspace_detail_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        overview_actions = ttk.Frame(heading, style="App.TFrame")
        overview_actions.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(
            overview_actions,
            text="Register bowler",
            command=self._open_registration,
            style="Primary.TButton",
        ).pack(side=tk.LEFT)
        self.overview_add_team_button = ttk.Button(
            overview_actions,
            text="Add team",
            command=self._new_managed_team,
            state=tk.DISABLED,
        )
        self.overview_add_team_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            overview_actions,
            text="Open scores",
            command=lambda: self.section_tabs.select(self.scores_tab),
        ).pack(side=tk.LEFT, padx=(8, 0))

        summary = ttk.Frame(tab, style="Surface.TFrame", padding=14)
        summary.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        for column in range(4):
            summary.columnconfigure(column, weight=1)
        self.overview_teams_label = self._summary_value(summary, 0, "Teams")
        self.overview_players_label = self._summary_value(summary, 1, "Active players")
        self.overview_attention_label = self._summary_value(summary, 2, "Needs attention")
        self.overview_weeks_label = self._summary_value(summary, 3, "Score sheets")

        ttk.Label(
            tab,
            text="Work queue",
            style="Muted.TLabel",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=2, column=0, sticky="w", pady=(3, 8))
        queue_frame = ttk.Frame(tab, style="Surface.TFrame")
        queue_frame.grid(row=3, column=0, sticky="nsew")
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)
        self.workspace_queue = ttk.Treeview(
            queue_frame,
            columns=("type", "item", "detail"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("type", "Needs work", 150, False),
            ("item", "Player / team", 230, True),
            ("detail", "Next step", 430, True),
        ):
            self.workspace_queue.heading(column, text=label)
            self.workspace_queue.column(
                column, width=width, minwidth=90, stretch=stretch, anchor="w"
            )
        queue_scroll = ttk.Scrollbar(
            queue_frame, orient=tk.VERTICAL, command=self.workspace_queue.yview
        )
        self.workspace_queue.configure(yscrollcommand=queue_scroll.set)
        self.workspace_queue.grid(row=0, column=0, sticky="nsew")
        queue_scroll.grid(row=0, column=1, sticky="ns")
        self.workspace_queue.bind(
            "<Double-1>", lambda _event: self._open_registration()
        )

    @staticmethod
    def _summary_value(parent: ttk.Frame, column: int, label: str) -> ttk.Label:
        block = ttk.Frame(parent, style="Surface.TFrame", padding=(8, 4))
        block.grid(row=0, column=column, sticky="ew")
        value = ttk.Label(
            block,
            text="0",
            style="Surface.TLabel",
            font=("Segoe UI", 18, "bold"),
        )
        value.pack(anchor="w")
        ttk.Label(block, text=label, style="Surface.TLabel").pack(anchor="w")
        return value

    def _build_rules_tab(self) -> None:
        tab = self.rules_tab
        tab.columnconfigure(0, weight=1)
        heading = ttk.Frame(tab, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(
            heading,
            text="Rules & Setup",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text="League details, average rules, handicap, and scoring defaults.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.rules_edit_league_button = ttk.Button(
            heading,
            text="Edit league details",
            command=self._edit_context_competition,
            state=tk.DISABLED,
        )
        self.rules_edit_league_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.rules_edit_scoring_button = ttk.Button(
            heading,
            text="Edit average & scoring rules",
            command=self._edit_context_rules,
            state=tk.DISABLED,
            style="Primary.TButton",
        )
        self.rules_edit_scoring_button.grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(8, 0)
        )

        details = ttk.Frame(tab, style="Surface.TFrame", padding=18)
        details.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        details.columnconfigure(1, weight=1)
        fields = (
            ("Workspace", "rules_workspace_value"),
            ("Games per night", "rules_games_value"),
            ("Average rule", "rules_average_value"),
            ("Handicap", "rules_handicap_value"),
            ("Blind / vacancy", "rules_blind_value"),
            ("Player pool", "rules_pool_value"),
        )
        for row, (label, attribute) in enumerate(fields):
            ttk.Label(details, text=label, style="Surface.TLabel").grid(
                row=row, column=0, sticky="nw", padx=(0, 18), pady=7
            )
            value = ttk.Label(details, text="—", style="Surface.TLabel")
            value.grid(row=row, column=1, sticky="w", pady=7)
            setattr(self, attribute, value)

        rules_footer = ttk.Frame(tab, style="App.TFrame")
        rules_footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.rules_pool_button = ttk.Button(
            rules_footer,
            text="Link player pool",
            command=self._link_context_player_pool,
            state=tk.DISABLED,
        )
        self.rules_pool_button.pack(side=tk.RIGHT)

    def _build_players_tab(self) -> None:
        tab = self.players_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        heading = ttk.Frame(tab, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(
            heading,
            text="Player Management",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text=(
                "One player identity shared across every season and tournament. "
                "Double-click a player to explore relationships."
            ),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.player_edit_button = ttk.Button(
            heading,
            text="Edit selected player",
            command=self._edit_managed_player,
            state=tk.DISABLED,
        )
        self.player_edit_button.grid(row=0, column=1, rowspan=2, sticky="e")

        search = ttk.Frame(tab, style="Surface.TFrame", padding=14)
        search.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Find player", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.player_search_var = tk.StringVar()
        player_search = ttk.Entry(search, textvariable=self.player_search_var)
        player_search.grid(row=0, column=1, sticky="ew")
        player_search.bind("<KeyRelease>", lambda _event: self._render_players())
        self.player_count_label = ttk.Label(
            search, text="0 players", style="Surface.TLabel"
        )
        self.player_count_label.grid(row=0, column=2, padx=(12, 0))
        ttk.Label(search, text="Season pool", style="Surface.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=(10, 0)
        )
        self.player_pool_var = tk.StringVar(value="All players")
        self.player_pool_box = ttk.Combobox(
            search, textvariable=self.player_pool_var, state="readonly"
        )
        self.player_pool_box.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        self.player_pool_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_players()
        )
        pool_actions = ttk.Frame(search, style="Surface.TFrame")
        pool_actions.grid(row=1, column=2, sticky="e", padx=(12, 0), pady=(10, 0))
        self.player_pool_new_button = ttk.Button(
            pool_actions, text="New pool", command=self._new_player_pool
        )
        self.player_pool_new_button.pack(side=tk.LEFT)
        self.player_pool_copy_button = ttk.Button(
            pool_actions,
            text="Copy forward",
            command=self._copy_player_pool,
            state=tk.DISABLED,
        )
        self.player_pool_copy_button.pack(side=tk.LEFT, padx=(6, 0))
        self.player_pool_add_button = ttk.Button(
            pool_actions,
            text="Add player",
            command=self._add_player_to_pool,
            state=tk.DISABLED,
        )
        self.player_pool_add_button.pack(side=tk.LEFT, padx=(6, 0))
        self.player_pool_remove_button = ttk.Button(
            pool_actions,
            text="Remove selected",
            command=self._remove_player_from_pool,
            state=tk.DISABLED,
        )
        self.player_pool_remove_button.pack(side=tk.LEFT, padx=(6, 0))

        frame = ttk.Frame(tab, style="Surface.TFrame")
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.player_table = ttk.Treeview(
            frame,
            columns=("name", "member_id", "registrations", "history"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("name", "Player", 220, True),
            ("member_id", "Member ID", 130, False),
            ("registrations", "Registrations", 100, False),
            ("history", "League / tournament history", 430, True),
        ):
            self.player_table.heading(column, text=label)
            self.player_table.column(
                column, width=width, minwidth=80, stretch=stretch, anchor="w"
            )
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.player_table.yview)
        self.player_table.configure(yscrollcommand=scrollbar.set)
        self.player_table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.player_table.bind(
            "<<TreeviewSelect>>", lambda _event: self._update_player_actions()
        )
        self.player_table.bind(
            "<Double-1>", lambda _event: self._show_selected_player_relationships()
        )

    def _build_teams_tab(self) -> None:
        tab = self.teams_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        tab.rowconfigure(3, weight=2)
        heading = ttk.Frame(tab, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(
            heading,
            text="Team Management",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text=(
                "Teams and rosters are filtered by league season or tournament. "
                "Double-click a team to explore relationships."
            ),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.team_add_button = ttk.Button(
            heading, text="Add team", command=self._new_managed_team, state=tk.DISABLED
        )
        self.team_add_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.team_rename_button = ttk.Button(
            heading,
            text="Rename selected",
            command=self._rename_managed_team,
            state=tk.DISABLED,
        )
        self.team_rename_button.grid(row=0, column=2, rowspan=2, sticky="e", padx=(8, 0))
        self.team_score_history_button = ttk.Button(
            heading,
            text="Score history",
            command=self._show_managed_team_score_history,
            state=tk.DISABLED,
        )
        self.team_score_history_button.grid(
            row=0, column=3, rowspan=2, sticky="e", padx=(8, 0)
        )

        selector = ttk.Frame(tab, style="Surface.TFrame", padding=14)
        selector.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        selector.columnconfigure(1, weight=1)
        ttk.Label(selector, text="League / tournament", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.team_management_competition_var = self.competition_var
        self.team_management_competition_box = ttk.Combobox(
            selector,
            textvariable=self.team_management_competition_var,
            state="readonly",
        )
        self.team_management_competition_box.grid(row=0, column=1, sticky="ew")
        self.team_management_competition_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._competition_selected()
        )
        self.team_count_label = ttk.Label(
            selector, text="0 teams", style="Surface.TLabel"
        )
        self.team_count_label.grid(row=0, column=2, padx=(12, 0))

        frame = ttk.Frame(tab, style="Surface.TFrame")
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.team_management_table = ttk.Treeview(
            frame,
            columns=("team", "regulars", "substitutes", "total"),
            show="headings",
            height=5,
        )
        for column, label, width, stretch in (
            ("team", "Team", 220, True),
            ("regulars", "Regulars", 100, False),
            ("substitutes", "Team substitutes", 120, False),
            ("total", "All entries", 90, False),
        ):
            self.team_management_table.heading(column, text=label)
            self.team_management_table.column(
                column, width=width, minwidth=75, stretch=stretch, anchor="w"
            )
        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=self.team_management_table.yview
        )
        self.team_management_table.configure(yscrollcommand=scrollbar.set)
        self.team_management_table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.team_management_table.bind(
            "<<TreeviewSelect>>", lambda _event: self._update_team_actions()
        )
        self.team_management_table.bind(
            "<Double-1>", lambda _event: self._show_selected_team_relationships()
        )

        roster_frame = ttk.Frame(tab, style="Surface.TFrame", padding=(10, 8))
        roster_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        roster_frame.columnconfigure(0, weight=1)
        roster_frame.rowconfigure(0, weight=1)
        self.roster_tabs = ttk.Notebook(roster_frame)
        self.roster_tabs.grid(row=0, column=0, sticky="nsew")
        regular_tab = ttk.Frame(self.roster_tabs, style="Surface.TFrame")
        substitute_tab = ttk.Frame(self.roster_tabs, style="Surface.TFrame")
        league_substitute_tab = ttk.Frame(self.roster_tabs, style="Surface.TFrame")
        self.roster_tabs.add(regular_tab, text="Regular roster")
        self.roster_tabs.add(substitute_tab, text="Team substitutes")
        self.roster_tabs.add(league_substitute_tab, text="League substitute pool")
        self.team_regular_table = self._make_roster_management_table(regular_tab)
        self.team_substitute_table = self._make_roster_management_table(substitute_tab)
        self.league_substitute_table = self._make_roster_management_table(
            league_substitute_tab
        )
        self.roster_tables = (
            self.team_regular_table,
            self.team_substitute_table,
            self.league_substitute_table,
        )
        self.roster_tabs.bind(
            "<<NotebookTabChanged>>", lambda _event: self._update_roster_actions()
        )

        roster_actions = ttk.Frame(tab, style="App.TFrame")
        roster_actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            roster_actions,
            text="Removing a player from a team keeps their league registration.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        self.roster_remove_button = ttk.Button(
            roster_actions,
            text="Remove from team",
            command=self._remove_player_from_team,
            state=tk.DISABLED,
        )
        self.roster_remove_button.pack(side=tk.RIGHT)
        self.roster_role_button = ttk.Button(
            roster_actions,
            text="Change roster role",
            command=self._toggle_roster_role,
            state=tk.DISABLED,
        )
        self.roster_role_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.roster_existing_button = ttk.Button(
            roster_actions,
            text="Add existing player",
            command=self._add_existing_player_to_team,
            state=tk.DISABLED,
        )
        self.roster_existing_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.roster_new_button = ttk.Button(
            roster_actions,
            text="Register new player",
            command=self._register_new_team_player,
            state=tk.DISABLED,
        )
        self.roster_new_button.pack(side=tk.RIGHT, padx=(0, 8))

    def _make_roster_management_table(self, parent: ttk.Frame) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        table = ttk.Treeview(
            parent,
            columns=("name", "member_id", "team", "status"),
            show="headings",
            height=7,
        )
        for column, label, width, stretch in (
            ("name", "Player", 220, True),
            ("member_id", "Member ID", 125, False),
            ("team", "Assignment", 190, True),
            ("status", "Status", 180, True),
        ):
            table.heading(column, text=label)
            table.column(
                column, width=width, minwidth=75, stretch=stretch, anchor="w"
            )
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        table.bind(
            "<<TreeviewSelect>>",
            lambda _event, selected_table=table: self._roster_row_selected(
                selected_table
            ),
        )
        return table

    def _build_competitions_tab(self) -> None:
        tab = self.competitions_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        heading = ttk.Frame(tab, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        heading.columnconfigure(0, weight=1)
        ttk.Label(
            heading,
            text="League & Tournament Management",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text=(
                "Each league season remains an independent historical workspace. "
                "Double-click one to explore its teams and players."
            ),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(
            heading,
            text="New league or tournament",
            command=self._new_competition,
            style="Primary.TButton",
        ).grid(row=0, column=1, rowspan=2, sticky="e")
        self.competition_edit_button = ttk.Button(
            heading,
            text="Edit selected",
            command=self._edit_managed_competition,
            state=tk.DISABLED,
        )
        self.competition_edit_button.grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(8, 0)
        )
        self.competition_archive_button = ttk.Button(
            heading,
            text="Archive selected",
            command=self._toggle_competition_archive,
            state=tk.DISABLED,
        )
        self.competition_archive_button.grid(
            row=0, column=3, rowspan=2, sticky="e", padx=(8, 0)
        )

        frame = ttk.Frame(tab, style="Surface.TFrame")
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.competition_management_table = ttk.Treeview(
            frame,
            columns=("kind", "name", "season", "pool", "teams", "bowlers", "status"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("kind", "Type", 100, False),
            ("name", "Name", 240, True),
            ("season", "Season / year", 120, False),
            ("pool", "Player pool", 120, False),
            ("teams", "Teams", 70, False),
            ("bowlers", "Bowlers", 80, False),
            ("status", "Status", 90, False),
        ):
            self.competition_management_table.heading(column, text=label)
            self.competition_management_table.column(
                column, width=width, minwidth=65, stretch=stretch, anchor="w"
            )
        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=self.competition_management_table.yview
        )
        self.competition_management_table.configure(yscrollcommand=scrollbar.set)
        self.competition_management_table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.competition_management_table.tag_configure(
            "archived", foreground="#9FB0BF"
        )
        self.competition_management_table.bind(
            "<<TreeviewSelect>>", lambda _event: self._managed_competition_selected()
        )
        self.competition_management_table.bind(
            "<Double-1>", lambda _event: self._show_selected_competition_relationships()
        )

        actions = ttk.Frame(tab, style="App.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            actions,
            text="Reuse players or teams from prior seasons.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        self.competition_pool_button = ttk.Button(
            actions,
            text="Link player pool",
            command=self._link_competition_player_pool,
            state=tk.DISABLED,
        )
        self.competition_pool_button.pack(side=tk.RIGHT)
        self.competition_score_history_button = ttk.Button(
            actions,
            text="Score history",
            command=self._show_selected_competition_score_history,
            state=tk.DISABLED,
        )
        self.competition_score_history_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.competition_add_player_button = ttk.Button(
            actions,
            text="Register new player",
            command=self._add_player_to_managed_competition,
            state=tk.DISABLED,
        )
        self.competition_add_player_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.competition_pull_player_button = ttk.Button(
            actions,
            text="Pull existing player",
            command=self._pull_player_into_managed_competition,
            state=tk.DISABLED,
        )
        self.competition_pull_player_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.competition_add_team_button = ttk.Button(
            actions,
            text="Add team",
            command=self._add_team_to_managed_competition,
            state=tk.DISABLED,
        )
        self.competition_add_team_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.competition_copy_team_button = ttk.Button(
            actions,
            text="Copy existing team",
            command=self._copy_team_to_managed_competition,
            state=tk.DISABLED,
        )
        self.competition_copy_team_button.pack(side=tk.RIGHT, padx=(0, 8))

    def refresh(self) -> None:
        if self.store is None:
            self.competition_box.configure(values=(), state=tk.DISABLED)
            self.workspace_competition_box.configure(values=(), state=tk.DISABLED)
            self._set_competition_actions(False)
            self.counter_label.configure(text="Registration data could not be opened")
            self._refresh_management_views()
            return
        competitions = sorted(
            (item for item in self.store.competitions if not item.archived),
            key=lambda item: (item.kind.value, item.season, item.name.casefold()),
            reverse=True,
        )
        self.competition_by_label = {
            item.selection_label: item for item in competitions
        }
        labels = list(self.competition_by_label)
        selection_state = "readonly" if labels else tk.DISABLED
        self.competition_box.configure(values=labels, state=selection_state)
        self.workspace_competition_box.configure(values=labels, state=selection_state)
        preferred_label = next(
            (
                label
                for label, competition in self.competition_by_label.items()
                if competition.id == self.workspace_context.competition_id
            ),
            "",
        )
        if preferred_label:
            self.competition_var.set(preferred_label)
        elif self.competition_var.get() not in self.competition_by_label:
            self.competition_var.set(labels[0] if labels else "")
        competition = self._current_competition()
        if competition is not None:
            self.workspace_context.select(competition.id)
        self._competition_changed()
        self._refresh_management_views()

    def _open_registration(self) -> None:
        if self.open_registration_callback is not None:
            self.open_registration_callback()
            return
        for tab_id in self.section_tabs.tabs():
            if self.section_tabs.tab(tab_id, "text") == "Registration":
                self.section_tabs.select(tab_id)
                return

    def _detach_current_section(self) -> None:
        if self.detach_callback is None:
            return
        selected = self.section_tabs.select()
        section = self.section_tabs.tab(selected, "text") if selected else ""
        self.detach_callback(str(section))

    def select_section(self, section: str) -> None:
        for tab_id in self.section_tabs.tabs():
            if self.section_tabs.tab(tab_id, "text") == section:
                self.section_tabs.select(tab_id)
                return

    def _competition_selected(self) -> None:
        competition = self._current_competition()
        if competition is not None:
            self.workspace_context.select(competition.id)
        self._competition_changed()
        self._refresh_team_management_competitions()
        self.scoring_desk.refresh()

    def _workspace_competition_changed(self, competition_id: str) -> None:
        label = next(
            (
                label
                for label, competition in self.competition_by_label.items()
                if competition.id == competition_id
            ),
            "",
        )
        if label and self.competition_var.get() != label:
            self.competition_var.set(label)
        self._competition_changed()
        self._refresh_team_management_competitions()

    def refresh_auth_state(self) -> None:
        self._update_actions()

    def _refresh_management_views(self) -> None:
        self._render_workspace_overview()
        self._refresh_player_pools()
        self._render_players()
        self._refresh_team_management_competitions()
        self._render_competitions()
        self.scoring_desk.refresh()
        self._render_rules_summary()

    def _render_workspace_overview(self) -> None:
        self.workspace_queue.delete(*self.workspace_queue.get_children())
        competition = self._current_competition()
        if self.store is None or competition is None:
            self.workspace_title_label.configure(text="League home")
            self.workspace_detail_label.configure(
                text="Create or choose a league or tournament to begin."
            )
            for label in (
                self.overview_teams_label,
                self.overview_players_label,
                self.overview_attention_label,
                self.overview_weeks_label,
            ):
                label.configure(text="0")
            self.overview_add_team_button.configure(state=tk.DISABLED)
            return
        teams = self.store.list_teams(competition.id)
        views = [
            view
            for view in self.store.registration_views(competition.id)
            if not view.registration.withdrawn
        ]
        needs_attention = [view for view in views if view.status != "Ready"]
        unassigned = [
            view
            for view in views
            if not view.registration.team_id
            and view.registration.roster_role is RosterRole.REGULAR
        ]
        sessions = (
            self.scoring_desk.scoring_store.list_sessions(competition.id)
            if competition.kind is CompetitionKind.LEAGUE
            and self.scoring_desk.scoring_store is not None
            else []
        )
        self.workspace_title_label.configure(text=competition.display_name)
        self.workspace_detail_label.configure(
            text=f"{competition.kind.value} workspace • all changes save automatically"
        )
        self.overview_teams_label.configure(text=str(len(teams)))
        self.overview_players_label.configure(text=str(len(views)))
        self.overview_attention_label.configure(
            text=str(len({view.registration.id for view in needs_attention + unassigned}))
        )
        self.overview_weeks_label.configure(text=str(len(sessions)))
        self.overview_add_team_button.configure(state=tk.NORMAL)
        queue_number = 0
        for view in unassigned:
            self.workspace_queue.insert(
                "",
                tk.END,
                iid=f"unassigned-{queue_number}",
                values=("Unassigned player", view.bowler.name, "Choose a team or substitute role"),
            )
            queue_number += 1
        for view in needs_attention:
            self.workspace_queue.insert(
                "",
                tk.END,
                iid=f"verification-{queue_number}",
                values=("Average verification", view.bowler.name, view.status),
            )
            queue_number += 1
        if not queue_number:
            self.workspace_queue.insert(
                "",
                tk.END,
                iid="ready",
                values=("Ready", competition.display_name, "No roster issues need attention"),
            )

    def _render_rules_summary(self) -> None:
        competition = self._current_competition()
        enabled = self.store is not None and competition is not None
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in (
            self.rules_edit_league_button,
            self.rules_edit_scoring_button,
            self.rules_pool_button,
        ):
            button.configure(state=state)
        if competition is None or self.store is None:
            for attribute in (
                "rules_workspace_value",
                "rules_games_value",
                "rules_average_value",
                "rules_handicap_value",
                "rules_blind_value",
                "rules_pool_value",
            ):
                getattr(self, attribute).configure(text="—")
            return
        pool = next(
            (
                item
                for item in self.store.player_pools
                if item.id == competition.player_pool_id
            ),
            None,
        )
        percent = competition.handicap_percent * 100
        self.rules_workspace_value.configure(
            text=f"{competition.display_name} • {competition.kind.value}"
        )
        self.rules_games_value.configure(text=str(competition.games_per_session))
        self.rules_average_value.configure(
            text=(
                f"{competition.average_rule_name}; minimum "
                f"{competition.average_minimum_games} games; ×"
                f"{competition.average_multiplier} {competition.average_add_pins:+d} pins; "
                f"{competition.average_rounding.value}"
            )
        )
        self.rules_handicap_value.configure(
            text=f"{percent}% of {competition.handicap_base} minus average"
        )
        self.rules_blind_value.configure(
            text=(
                f"Blind penalty {competition.blind_penalty}; "
                f"vacancy score {competition.vacancy_score}"
            )
        )
        self.rules_pool_value.configure(text=pool.label if pool else "Not linked")

    def _edit_context_competition(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            return
        choice = CompetitionDialog(self, competition).show()
        if choice is None:
            return
        try:
            self.store.update_competition(competition.id, *choice)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update", str(error), parent=self)
            return
        self.refresh()

    def _edit_context_rules(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            return
        settings = LeagueScoringSettingsDialog(self, competition).show()
        if settings is None:
            return
        try:
            self.store.update_competition_scoring_settings(competition.id, **settings)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not save settings", str(error), parent=self)
            return
        self.refresh()
        self.status_callback(f"Saved rules for {competition.display_name}")

    def _link_context_player_pool(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            return
        pool_id = PoolPickerDialog(
            self, self.store.player_pools, competition.player_pool_id
        ).show()
        if pool_id is None:
            return
        try:
            self.store.set_competition_player_pool(competition.id, pool_id)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not link player pool", str(error), parent=self)
            return
        self.refresh()

    def _refresh_after_roster_change(self) -> None:
        """Refresh every screen that displays a player-to-team relationship."""
        self._refresh_teams()
        self._render_rows()
        self._refresh_management_views()

    def _refresh_player_pools(self) -> None:
        pools = (
            sorted(
                (item for item in self.store.player_pools if not item.archived),
                key=lambda item: item.label,
                reverse=True,
            )
            if self.store
            else []
        )
        self.player_pool_by_label: dict[str, PlayerPool] = {
            item.label: item for item in pools
        }
        values = ["All players", *self.player_pool_by_label]
        self.player_pool_box.configure(values=values, state="readonly")
        if self.player_pool_var.get() not in values:
            self.player_pool_var.set("All players")

    def _current_player_pool(self) -> PlayerPool | None:
        return self.player_pool_by_label.get(self.player_pool_var.get())

    def _render_players(self) -> None:
        self.player_table.delete(*self.player_table.get_children())
        if self.store is None:
            self.player_count_label.configure(text="Player data unavailable")
            self._update_player_actions()
            return
        query = " ".join(self.player_search_var.get().split()).casefold()
        selected_pool = self._current_player_pool()
        pool_bowler_ids = (
            {item.id for item in self.store.pool_bowlers(selected_pool.id)}
            if selected_pool
            else None
        )
        competition_by_id = {item.id: item for item in self.store.competitions}
        registrations_by_bowler: dict[str, list] = {}
        for registration in self.store.registrations:
            registrations_by_bowler.setdefault(registration.bowler_id, []).append(
                registration
            )
        visible = []
        for bowler in sorted(self.store.bowlers, key=lambda item: item.name.casefold()):
            if pool_bowler_ids is not None and bowler.id not in pool_bowler_ids:
                continue
            if query and query not in f"{bowler.name} {bowler.membership_id}".casefold():
                continue
            registrations = registrations_by_bowler.get(bowler.id, [])
            history = []
            for registration in registrations:
                competition = competition_by_id.get(registration.competition_id)
                if competition is None:
                    continue
                label = competition.display_name
                if competition.archived:
                    label += " (archived)"
                if label not in history:
                    history.append(label)
            visible.append(bowler)
            self.player_table.insert(
                "",
                tk.END,
                iid=bowler.id,
                values=(
                    bowler.name,
                    bowler.membership_id or "—",
                    len(registrations),
                    "; ".join(history) or "No registrations",
                ),
            )
        self.player_count_label.configure(
            text=f"{len(visible)} of {len(self.store.bowlers)} players"
        )
        self._update_player_actions()

    def _selected_player_id(self) -> str | None:
        selected = self.player_table.selection()
        return selected[0] if selected else None

    def _update_player_actions(self) -> None:
        selected_pool = self._current_player_pool()
        self.player_edit_button.configure(
            state=tk.NORMAL if self._selected_player_id() else tk.DISABLED
        )
        pool_state = tk.NORMAL if selected_pool else tk.DISABLED
        self.player_pool_copy_button.configure(state=pool_state)
        self.player_pool_add_button.configure(state=pool_state)
        self.player_pool_remove_button.configure(
            state=(
                tk.NORMAL
                if selected_pool and self._selected_player_id()
                else tk.DISABLED
            )
        )

    def _new_player_pool(self) -> None:
        if self.store is None:
            return
        label = simpledialog.askstring(
            "New season player pool",
            "Season or year (example: 2026-27)",
            parent=self,
        )
        if label is None:
            return
        try:
            pool = self.store.add_player_pool(label)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not create pool", str(error), parent=self)
            return
        self._refresh_player_pools()
        self.player_pool_var.set(pool.label)
        self._render_players()

    def _copy_player_pool(self) -> None:
        if self.store is None:
            return
        source = self._current_player_pool()
        if source is None:
            return
        label = simpledialog.askstring(
            "Copy player pool forward",
            "New season or year",
            parent=self,
        )
        if label is None:
            return
        try:
            pool = self.store.copy_player_pool(source.id, label)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not copy pool", str(error), parent=self)
            return
        self._refresh_player_pools()
        self.player_pool_var.set(pool.label)
        self._render_players()

    def _add_player_to_pool(self) -> None:
        if self.store is None:
            return
        pool = self._current_player_pool()
        if pool is None:
            return
        existing_ids = {item.id for item in self.store.pool_bowlers(pool.id)}
        available = [item for item in self.store.bowlers if item.id not in existing_ids]
        bowler_id = PlayerPickerDialog(
            self, f"Add player to {pool.label}", available
        ).show()
        if bowler_id is None:
            return
        try:
            self.store.add_bowler_to_pool(pool.id, bowler_id)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update pool", str(error), parent=self)
            return
        self._render_players()

    def _remove_player_from_pool(self) -> None:
        if self.store is None:
            return
        pool = self._current_player_pool()
        bowler_id = self._selected_player_id()
        if pool is None or bowler_id is None:
            return
        try:
            self.store.remove_bowler_from_pool(pool.id, bowler_id)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update pool", str(error), parent=self)
            return
        self._render_players()

    def _edit_managed_player(self) -> None:
        if self.store is None:
            return
        bowler_id = self._selected_player_id()
        if bowler_id is None:
            return
        bowler = next((item for item in self.store.bowlers if item.id == bowler_id), None)
        if bowler is None:
            return
        choice = PlayerEditDialog(self, bowler.name, bowler.membership_id).show()
        if choice is None:
            return
        try:
            self.store.update_bowler_profile(bowler_id, *choice)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update player", str(error), parent=self)
            return
        self._refresh_after_roster_change()
        self.status_callback("Player updated; affected averages need rechecking")

    def _refresh_team_management_competitions(self) -> None:
        labels = list(self.competition_by_label)
        self.team_management_competition_box.configure(
            values=labels,
            state="readonly" if labels else tk.DISABLED,
        )
        if self.competition_var.get() not in self.competition_by_label:
            self.competition_var.set(labels[0] if labels else "")
        self._render_teams()

    def _team_management_competition(self) -> Competition | None:
        return self.competition_by_label.get(
            self.team_management_competition_var.get()
        )

    def _render_teams(self) -> None:
        selected_team_id = self._selected_managed_team_id()
        self.team_management_table.delete(*self.team_management_table.get_children())
        competition = self._team_management_competition()
        if self.store is None or competition is None:
            self.team_count_label.configure(text="0 teams")
            self._render_team_rosters()
            self._update_team_actions()
            return
        teams = self.store.list_teams(competition.id)
        views = self.store.registration_views(competition.id)
        for team in teams:
            members = [view for view in views if view.registration.team_id == team.id]
            active = [view for view in members if not view.registration.withdrawn]
            regulars = [
                view
                for view in active
                if view.registration.roster_role is RosterRole.REGULAR
            ]
            substitutes = [
                view
                for view in active
                if view.registration.roster_role is RosterRole.SUBSTITUTE
            ]
            self.team_management_table.insert(
                "",
                tk.END,
                iid=team.id,
                values=(
                    team.name,
                    len(regulars),
                    len(substitutes),
                    len(members),
                ),
            )
        team_ids = {team.id for team in teams}
        if selected_team_id in team_ids:
            self.team_management_table.selection_set(selected_team_id)
            self.team_management_table.focus(selected_team_id)
        elif teams:
            self.team_management_table.selection_set(teams[0].id)
            self.team_management_table.focus(teams[0].id)
        self.team_count_label.configure(text=f"{len(teams)} teams")
        self._render_team_rosters()
        self._update_team_actions()

    def _render_team_rosters(self) -> None:
        for table in self.roster_tables:
            table.delete(*table.get_children())
        competition = self._team_management_competition()
        team_id = self._selected_managed_team_id()
        if self.store is None or competition is None:
            self._update_roster_actions()
            return
        views = self.store.registration_views(competition.id)
        groups = (
            (
                self.team_regular_table,
                [
                    view
                    for view in views
                    if view.registration.team_id == team_id
                    and view.registration.roster_role is RosterRole.REGULAR
                ],
            ),
            (
                self.team_substitute_table,
                [
                    view
                    for view in views
                    if view.registration.team_id == team_id
                    and view.registration.roster_role is RosterRole.SUBSTITUTE
                ],
            ),
            (
                self.league_substitute_table,
                [
                    view
                    for view in views
                    if not view.registration.team_id
                    and view.registration.roster_role is RosterRole.SUBSTITUTE
                ],
            ),
        )
        for table, group in groups:
            for view in group:
                assignment = view.team.name if view.team else "League-wide substitute"
                table.insert(
                    "",
                    tk.END,
                    iid=view.registration.id,
                    values=(
                        view.bowler.name,
                        view.bowler.membership_id or "—",
                        assignment,
                        view.status,
                    ),
                )
        self._update_roster_actions()

    def _selected_managed_team_id(self) -> str | None:
        selected = self.team_management_table.selection()
        return selected[0] if selected else None

    def _update_team_actions(self) -> None:
        has_competition = self._team_management_competition() is not None
        self.team_add_button.configure(
            state=tk.NORMAL if has_competition else tk.DISABLED
        )
        self.team_rename_button.configure(
            state=tk.NORMAL if self._selected_managed_team_id() else tk.DISABLED
        )
        competition = self._team_management_competition()
        self.team_score_history_button.configure(
            state=(
                tk.NORMAL
                if competition is not None
                and competition.kind is CompetitionKind.LEAGUE
                and self._selected_managed_team_id()
                else tk.DISABLED
            )
        )
        self._render_team_rosters()

    def _active_roster_table(self) -> ttk.Treeview:
        return self.roster_tables[self.roster_tabs.index(self.roster_tabs.select())]

    def _selected_roster_view(self) -> RegistrationView | None:
        if self.store is None:
            return None
        competition = self._team_management_competition()
        if competition is None:
            return None
        selected = self._active_roster_table().selection()
        if not selected:
            return None
        return next(
            (
                view
                for view in self.store.registration_views(competition.id)
                if view.registration.id == selected[0]
            ),
            None,
        )

    def _roster_row_selected(self, selected_table: ttk.Treeview) -> None:
        if selected_table.selection():
            for table in self.roster_tables:
                if table is not selected_table:
                    table.selection_remove(*table.selection())
        self._update_roster_actions()

    def _update_roster_actions(self) -> None:
        has_team = self._selected_managed_team_id() is not None
        view = self._selected_roster_view()
        self.roster_existing_button.configure(
            state=tk.NORMAL if has_team else tk.DISABLED
        )
        self.roster_new_button.configure(state=tk.NORMAL if has_team else tk.DISABLED)
        self.roster_remove_button.configure(
            state=tk.NORMAL if view is not None and view.team is not None else tk.DISABLED
        )
        self.roster_role_button.configure(
            state=tk.NORMAL if view is not None else tk.DISABLED,
            text=(
                "Make substitute"
                if view is not None
                and view.registration.roster_role is RosterRole.REGULAR
                else "Make regular"
            ),
        )

    def _desired_roster_role(self) -> RosterRole:
        return (
            RosterRole.REGULAR
            if self._active_roster_table() is self.team_regular_table
            else RosterRole.SUBSTITUTE
        )

    def _remove_player_from_team(self) -> None:
        if self.store is None:
            return
        view = self._selected_roster_view()
        if view is None or view.team is None:
            return
        try:
            self.store.assign_registration(
                view.registration.id, "", view.registration.roster_role
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update roster", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _toggle_roster_role(self) -> None:
        if self.store is None:
            return
        view = self._selected_roster_view()
        if view is None:
            return
        role = (
            RosterRole.SUBSTITUTE
            if view.registration.roster_role is RosterRole.REGULAR
            else RosterRole.REGULAR
        )
        try:
            self.store.assign_registration(
                view.registration.id, view.registration.team_id, role
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update roster", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _add_existing_player_to_team(self) -> None:
        if self.store is None:
            return
        competition = self._team_management_competition()
        team_id = self._selected_managed_team_id()
        if competition is None or team_id is None:
            return
        role = self._desired_roster_role()
        destination_team_id = (
            "" if self._active_roster_table() is self.league_substitute_table else team_id
        )
        views = self.store.registration_views(competition.id)
        view_by_bowler_id = {view.bowler.id: view for view in views}
        available = [
            bowler
            for bowler in self.store.bowlers
            if not (
                (view := view_by_bowler_id.get(bowler.id))
                and view.registration.team_id == destination_team_id
                and view.registration.roster_role is role
            )
        ]
        if not available:
            messagebox.showinfo(
                "No players available",
                "Every player is already assigned to this roster section.",
                parent=self,
            )
            return
        bowler_id = LeagueDirectoryPlayerPickerDialog(
            self, competition, available, view_by_bowler_id
        ).show()
        if bowler_id is None:
            return
        view = view_by_bowler_id.get(bowler_id)
        if view is not None and view.team is not None and not messagebox.askyesno(
            "Move player?",
            f"{view.bowler.name} is currently on {view.team.name} in "
            f"{competition.display_name}. Move them?",
            parent=self,
        ):
            return
        try:
            if view is None:
                self.store.register_existing_bowler(
                    competition.id, bowler_id, destination_team_id, role
                )
            else:
                self.store.assign_registration(
                    view.registration.id, destination_team_id, role
                )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update roster", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _register_new_team_player(self) -> None:
        if self.store is None:
            return
        competition = self._team_management_competition()
        team_id = self._selected_managed_team_id()
        if competition is None or team_id is None:
            return
        choice = LeaguePlayerDialog(
            self,
            self.store.list_teams(competition.id),
            default_team_id=team_id,
            default_role=self._desired_roster_role(),
        ).show()
        if choice is None:
            return
        name, membership_id, selected_team_id, role = choice
        try:
            self.store.register_bowler(
                competition.id, name, membership_id, selected_team_id, role
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not register player", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _new_managed_team(self) -> None:
        if self.store is None:
            return
        competition = self._team_management_competition()
        if competition is None:
            return
        name = simpledialog.askstring("Add team", "Team name", parent=self)
        if name is None:
            return
        try:
            self.store.add_team(competition.id, name)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not add team", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _rename_managed_team(self) -> None:
        if self.store is None:
            return
        team_id = self._selected_managed_team_id()
        if team_id is None:
            return
        team = next((item for item in self.store.teams if item.id == team_id), None)
        if team is None:
            return
        name = simpledialog.askstring(
            "Rename team", "Team name", initialvalue=team.name, parent=self
        )
        if name is None:
            return
        try:
            self.store.rename_team(team.id, name)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not rename team", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _render_competitions(self) -> None:
        selected = self._selected_managed_competition()
        selected_id = (
            selected.id
            if selected
            else (self.workspace_context.competition_id or None)
        )
        self.competition_management_table.delete(
            *self.competition_management_table.get_children()
        )
        if self.store is None:
            self._update_competition_actions()
            return
        for competition in sorted(
            self.store.competitions,
            key=lambda item: (
                item.archived,
                item.kind.value,
                item.name.casefold(),
                item.season,
            ),
        ):
            teams = self.store.list_teams(competition.id)
            registrations = self.store.registration_views(competition.id)
            pool = next(
                (
                    item
                    for item in self.store.player_pools
                    if item.id == competition.player_pool_id
                ),
                None,
            )
            self.competition_management_table.insert(
                "",
                tk.END,
                iid=competition.id,
                values=(
                    competition.kind.value,
                    competition.name,
                    competition.season or "—",
                    pool.label if pool else "Not linked",
                    len(teams),
                    len(registrations),
                    "Archived" if competition.archived else "Active",
                ),
                tags=(("archived",) if competition.archived else ()),
            )
        if selected_id and self.competition_management_table.exists(selected_id):
            self.competition_management_table.selection_set(selected_id)
            self.competition_management_table.focus(selected_id)
        self._update_competition_actions()

    def _managed_competition_selected(self) -> None:
        competition = self._selected_managed_competition()
        self._update_competition_actions()
        if competition is not None and not competition.archived:
            self.workspace_context.select(competition.id)

    def _selected_managed_competition(self) -> Competition | None:
        if self.store is None:
            return None
        selected = self.competition_management_table.selection()
        if not selected:
            return None
        return next(
            (item for item in self.store.competitions if item.id == selected[0]),
            None,
        )

    def _update_competition_actions(self) -> None:
        competition = self._selected_managed_competition()
        state = tk.NORMAL if competition else tk.DISABLED
        active_state = (
            tk.NORMAL if competition is not None and not competition.archived else tk.DISABLED
        )
        self.competition_edit_button.configure(state=state)
        self.competition_archive_button.configure(state=state)
        self.competition_add_team_button.configure(state=active_state)
        self.competition_add_player_button.configure(state=active_state)
        self.competition_pull_player_button.configure(state=active_state)
        self.competition_copy_team_button.configure(state=active_state)
        self.competition_pool_button.configure(state=active_state)
        self.competition_score_history_button.configure(
            state=(
                tk.NORMAL
                if competition is not None and competition.kind is CompetitionKind.LEAGUE
                else tk.DISABLED
            )
        )
        if competition:
            self.competition_archive_button.configure(
                text="Restore selected" if competition.archived else "Archive selected"
            )

    def _show_selected_competition_score_history(self) -> None:
        competition = self._selected_managed_competition()
        if competition is None or competition.kind is not CompetitionKind.LEAGUE:
            return
        self.section_tabs.select(self.scores_tab)
        self.scoring_desk.select_competition(competition.id, show_history=True)

    def _show_managed_team_score_history(self) -> None:
        competition = self._team_management_competition()
        team_id = self._selected_managed_team_id()
        if (
            competition is None
            or competition.kind is not CompetitionKind.LEAGUE
            or team_id is None
        ):
            return
        self.section_tabs.select(self.scores_tab)
        self.scoring_desk.select_competition(
            competition.id, show_history=True, team_id=team_id
        )

    def _show_selected_competition_relationships(self) -> None:
        competition = self._selected_managed_competition()
        if self.store is None or competition is None:
            return
        RelationshipBrowser(
            self, self.store, EntityRef(EntityKind.LEAGUE, competition.id)
        )

    def _show_selected_team_relationships(self) -> None:
        team_id = self._selected_managed_team_id()
        if self.store is None or team_id is None:
            return
        RelationshipBrowser(self, self.store, EntityRef(EntityKind.TEAM, team_id))

    def _show_selected_player_relationships(self) -> None:
        bowler_id = self._selected_player_id()
        if self.store is None or bowler_id is None:
            return
        RelationshipBrowser(
            self, self.store, EntityRef(EntityKind.PLAYER, bowler_id)
        )

    def _add_team_to_managed_competition(self) -> None:
        if self.store is None:
            return
        competition = self._selected_managed_competition()
        if competition is None or competition.archived:
            return
        name = simpledialog.askstring("Add team", "Team name", parent=self)
        if name is None:
            return
        try:
            self.store.add_team(competition.id, name)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not add team", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _add_player_to_managed_competition(self) -> None:
        if self.store is None:
            return
        competition = self._selected_managed_competition()
        if competition is None or competition.archived:
            return
        choice = LeaguePlayerDialog(
            self, self.store.list_teams(competition.id)
        ).show()
        if choice is None:
            return
        name, membership_id, team_id, role = choice
        try:
            self.store.register_bowler(
                competition.id, name, membership_id, team_id, role
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not register player", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _pull_player_into_managed_competition(self) -> None:
        if self.store is None:
            return
        competition = self._selected_managed_competition()
        if competition is None or competition.archived:
            return
        registered_ids = {
            view.bowler.id for view in self.store.registration_views(competition.id)
        }
        available = [
            bowler for bowler in self.store.bowlers if bowler.id not in registered_ids
        ]
        if not available:
            messagebox.showinfo(
                "No players available",
                "Every player in the permanent player list is already in this "
                "league or tournament.",
                parent=self,
            )
            return
        bowler_id = PlayerPickerDialog(
            self, f"Pull player into {competition.display_name}", available
        ).show()
        if bowler_id is None:
            return
        try:
            self.store.register_existing_bowler(competition.id, bowler_id)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not pull player", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def _copy_team_to_managed_competition(self) -> None:
        if self.store is None:
            return
        competition = self._selected_managed_competition()
        if competition is None or competition.archived:
            return
        source_teams = [
            team for team in self.store.teams if team.competition_id != competition.id
        ]
        if not source_teams:
            messagebox.showinfo(
                "No teams available",
                "Create a team in another league or tournament first.",
                parent=self,
            )
            return
        choice = TeamCopyDialog(
            self, competition, self.store.competitions, source_teams, self.store.registrations
        ).show()
        if choice is None:
            return
        source_team_id, name, copy_roster = choice
        try:
            team, copied, skipped = self.store.copy_team_to_competition(
                source_team_id, competition.id, name, copy_roster
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not copy team", str(error), parent=self)
            return
        self._refresh_after_roster_change()
        detail = f"Copied {team.name}"
        if copy_roster:
            detail += f" with {copied} active player{'s' if copied != 1 else ''}"
            if skipped:
                detail += f"; {skipped} already assigned elsewhere"
        self.status_callback(detail)

    def _link_competition_player_pool(self) -> None:
        if self.store is None:
            return
        competition = self._selected_managed_competition()
        if competition is None or competition.archived:
            return
        pool_id = PoolPickerDialog(
            self, self.store.player_pools, competition.player_pool_id
        ).show()
        if pool_id is None:
            return
        try:
            self.store.set_competition_player_pool(competition.id, pool_id)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not link player pool", str(error), parent=self)
            return
        self._render_competitions()
        self._refresh_player_pools()
        self._render_players()

    def _edit_managed_competition(self) -> None:
        if self.store is None:
            return
        competition = self._selected_managed_competition()
        if competition is None:
            return
        choice = CompetitionDialog(self, competition).show()
        if choice is None:
            return
        try:
            self.store.update_competition(competition.id, *choice)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update", str(error), parent=self)
            return
        self.refresh()

    def _toggle_competition_archive(self) -> None:
        if self.store is None:
            return
        competition = self._selected_managed_competition()
        if competition is None:
            return
        try:
            self.store.set_competition_archived(
                competition.id, not competition.archived
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update", str(error), parent=self)
            return
        self.refresh()

    def _current_competition(self) -> Competition | None:
        return self.competition_by_label.get(self.competition_var.get())

    def _competition_changed(self) -> None:
        competition = self._current_competition()
        enabled = competition is not None and self.store is not None
        self._set_competition_actions(enabled)
        self._refresh_teams()
        self._render_rows()
        if enabled:
            self.name_entry.focus_set()

    def _set_competition_actions(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for widget in (
            self.new_team_button,
            self.team_button,
            self.add_button,
            self.multi_add_button,
            self.name_entry,
            self.quick_team_box,
        ):
            widget.configure(state=state if widget is not self.quick_team_box else (
                "readonly" if enabled else tk.DISABLED
            ))
        self._update_actions()

    def _refresh_teams(self) -> None:
        competition = self._current_competition()
        teams = self.store.list_teams(competition.id) if self.store and competition else []
        self.team_by_label = {team.name: team.id for team in teams}
        quick_values = ["Unassigned", *self.team_by_label]
        self.quick_team_box.configure(values=quick_values)
        if self.quick_team_var.get() not in quick_values:
            self.quick_team_var.set("Unassigned")
        filter_values = [
            "All teams",
            "Unassigned",
            "League substitute pool",
            *self.team_by_label,
        ]
        self.team_filter_box.configure(values=filter_values)
        if self.team_filter_var.get() not in filter_values:
            self.team_filter_var.set("All teams")

    def _new_competition(self) -> None:
        if self.store is None:
            return
        choice = CompetitionDialog(self).show()
        if choice is None:
            return
        name, season, kind = choice
        try:
            competition = self.store.add_competition(name, season, kind)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not create", str(error), parent=self)
            return
        self.refresh()
        self.competition_var.set(competition.selection_label)
        self.workspace_context.select(competition.id)
        self._competition_changed()

    def _new_team(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            return
        name = simpledialog.askstring("Add team", "Team name", parent=self)
        if name is None:
            return
        try:
            team = self.store.add_team(competition.id, name)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not add team", str(error), parent=self)
            return
        self.quick_team_var.set(team.name)
        self._refresh_after_roster_change()

    def _quick_add(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            messagebox.showinfo(
                "Create a league or tournament first",
                "Registration needs somewhere to put this bowler.",
                parent=self,
            )
            return
        team_id = self.team_by_label.get(self.quick_team_var.get(), "")
        try:
            registration = self.store.register_bowler(
                competition.id,
                self.name_var.get(),
                self.member_id_var.get(),
                team_id,
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not register bowler", str(error), parent=self)
            return
        bowler = InputBowler(self.name_var.get().strip(), self.member_id_var.get().strip())
        self.name_var.set("")
        self.member_id_var.set("")
        self._refresh_after_roster_change()
        self.name_entry.focus_set()
        if self.api_provider() is not None:
            self._start_lookup(registration.id, bowler)

    def _register_multiple(self) -> None:
        if self.store is None:
            return
        competitions = sorted(
            (item for item in self.store.competitions if not item.archived),
            key=lambda item: (item.season, item.name.casefold()),
            reverse=True,
        )
        if not competitions:
            messagebox.showinfo(
                "Create a league or tournament first",
                "Registration needs somewhere to put this bowler.",
                parent=self,
            )
            return
        current = self._current_competition()
        choice = MultiLeagueRegistrationDialog(
            self,
            competitions,
            self.store.teams,
            initial_name=self.name_var.get(),
            initial_membership_id=self.member_id_var.get(),
            initial_competition_id=current.id if current else "",
            initial_team_id=self.team_by_label.get(self.quick_team_var.get(), ""),
        ).show()
        if choice is None:
            return
        name, membership_id, targets = choice
        try:
            registrations = self.store.register_bowler_many(
                name, membership_id, targets
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not register bowler", str(error), parent=self)
            return
        self.name_var.set("")
        self.member_id_var.set("")
        self._refresh_after_roster_change()
        self.name_entry.focus_set()
        if self.api_provider() is not None:
            bowler = InputBowler(name, membership_id)
            self._queue_lookups(
                [(registration.id, bowler) for registration in registrations]
            )
        self.status_callback(
            f"Registered {name} in {len(registrations)} "
            f"workspace{'s' if len(registrations) != 1 else ''}"
        )

    def _register_team(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            return
        choice = TeamRegistrationDialog(self, list(self.team_by_label)).show()
        if choice is None:
            return
        team_name, text = choice
        try:
            bowlers = parse_input_text(text)
            _team, registrations = self.store.register_team(
                competition.id, team_name, bowlers
            )
        except (OSError, UnicodeError, ValueError, RegistrationDataError) as error:
            messagebox.showerror("Could not register team", str(error), parent=self)
            return
        self._refresh_after_roster_change()
        if self.api_provider() is not None:
            self._queue_lookups(
                [
                    (registration.id, bowler)
                    for registration, bowler in zip(registrations, bowlers, strict=True)
                ]
            )

    def _check_all(self) -> None:
        if self.store is None:
            return
        competition = self._current_competition()
        api = self.api_provider()
        if competition is None or api is None:
            messagebox.showinfo(
                "Sign in needed",
                "Sign in to BOWL.com to check registrations. "
                "You can keep entering bowlers without signing in.",
                parent=self,
            )
            return
        pending = [
            view
            for view in self.store.registration_views(competition.id)
            if not view.registration.withdrawn and view.status != "Ready"
        ]
        if not pending:
            messagebox.showinfo(
                "Nothing to check",
                "All active registrations are ready.",
                parent=self,
            )
            return
        self.bulk_pending.update(view.registration.id for view in pending)
        self._queue_lookups(
            [
                (
                    view.registration.id,
                    InputBowler(view.bowler.name, view.bowler.membership_id),
                )
                for view in pending
            ]
        )
        self.status_callback(f"Checking 0 of {len(pending)} registrations…")

    def _start_lookup(self, registration_id: str, bowler: InputBowler) -> None:
        if self.store is None:
            return
        api = self.api_provider()
        if api is None:
            return
        self._queue_lookups([(registration_id, bowler)])

    def _queue_lookups(self, items: list[tuple[str, InputBowler]]) -> None:
        if self.store is None or not items:
            return
        api = self.api_provider()
        if api is None:
            return
        try:
            self.store.mark_checking_many([registration_id for registration_id, _ in items])
        except (OSError, RegistrationDataError) as error:
            for registration_id, _bowler in items:
                self.bulk_pending.discard(registration_id)
            if self.bulk_pending:
                self.status_callback(
                    f"{len(self.bulk_pending)} registrations still checking…"
                )
            else:
                self.status_callback("Registration checks stopped")
            messagebox.showerror("Could not save lookup status", str(error), parent=self)
            return
        self._render_rows()
        self._render_teams()
        for registration_id, bowler in items:
            self.lookup_queue.put((api, registration_id, bowler))
        if len(items) == 1:
            self.status_callback(f"Checking {items[0][1].name}…")
        else:
            self.status_callback(f"Queued {len(items)} registrations for checking")

    def _lookup_queue_worker(self) -> None:
        while True:
            task = self.lookup_queue.get()
            if task is None:
                self.lookup_queue.task_done()
                return
            api, registration_id, bowler = task
            result = look_up_bowler(api, bowler)
            self.after(
                0,
                self._lookup_finished,
                registration_id,
                result,
                "Registration updated",
            )
            self.lookup_queue.task_done()

    def _lookup_finished(
        self, registration_id: str, result: LookupResult, status_text: str
    ) -> None:
        if self.store is None:
            return
        try:
            self.store.apply_lookup_result(registration_id, result)
        except (OSError, RegistrationDataError) as error:
            try:
                self.store.mark_lookup_error(registration_id, str(error))
            except (OSError, RegistrationDataError):
                pass
            messagebox.showerror("Could not save lookup result", str(error), parent=self)
            self._render_rows()
            self._render_players()
            self._render_teams()
            self._complete_lookup_progress(
                registration_id, "Lookup needs attention"
            )
            return
        self.lookup_results[registration_id] = result
        self._render_rows()
        self._render_players()
        self._render_teams()
        self._complete_lookup_progress(registration_id, status_text)

    def _complete_lookup_progress(
        self, registration_id: str, status_text: str
    ) -> None:
        if registration_id in self.bulk_pending:
            self.bulk_pending.remove(registration_id)
            remaining = len(self.bulk_pending)
            if remaining:
                self.status_callback(f"{remaining} registrations still checking…")
            else:
                self.status_callback("Registration checks complete")
        else:
            self.status_callback(status_text)

    def _render_rows(self) -> None:
        self.table.delete(*self.table.get_children())
        competition = self._current_competition()
        if self.store is None or competition is None:
            self.counter_label.configure(text="Create a league or tournament to begin")
            self._update_row_actions()
            return
        views = self.store.registration_views(competition.id)
        total = len(views)
        active = [view for view in views if not view.registration.withdrawn]
        ready = sum(view.status == "Ready" for view in active)
        attention = len(active) - ready
        self.counter_label.configure(
            text=f"{total} registered  •  {ready} ready  •  {attention} need attention"
        )
        selected_filter = self.team_filter_var.get()
        for view in views:
            team_name = (
                view.team.name
                if view.team
                else (
                    "League substitute pool"
                    if view.registration.roster_role is RosterRole.SUBSTITUTE
                    else "Unassigned"
                )
            )
            if selected_filter not in {"", "All teams", team_name}:
                continue
            average = (
                str(view.registration.average)
                if view.registration.average is not None
                else "—"
            )
            tag = self._row_tag(view)
            self.table.insert(
                "",
                tk.END,
                iid=view.registration.id,
                values=(
                    view.bowler.name,
                    view.bowler.membership_id or "—",
                    team_name,
                    average,
                    view.status,
                    view.registration.note or "—",
                ),
                tags=(tag,),
            )
        self._update_row_actions()

    @staticmethod
    def _row_tag(view: RegistrationView) -> str:
        if view.registration.withdrawn:
            return "withdrawn"
        if view.status == "Ready":
            return "ready"
        if "error" in view.status.casefold() or "not found" in view.status.casefold():
            return "error"
        return "attention"

    def _selected_view(self) -> RegistrationView | None:
        if self.store is None:
            return None
        selected = self.table.selection()
        competition = self._current_competition()
        if not selected or competition is None:
            return None
        return next(
            (
                view
                for view in self.store.registration_views(competition.id)
                if view.registration.id == selected[0]
            ),
            None,
        )

    def _update_actions(self) -> None:
        competition = self._current_competition()
        can_check = competition is not None and self.api_provider() is not None
        self.check_all_button.configure(state=tk.NORMAL if can_check else tk.DISABLED)
        self._update_row_actions()

    def _update_row_actions(self) -> None:
        view = self._selected_view()
        selected_state = tk.NORMAL if view is not None else tk.DISABLED
        self.edit_button.configure(state=selected_state)
        self.withdraw_button.configure(state=selected_state)
        can_review = view is not None and self.api_provider() is not None
        self.review_button.configure(state=tk.NORMAL if can_review else tk.DISABLED)
        if view:
            self.withdraw_button.configure(
                text="Restore selected" if view.registration.withdrawn else "Withdraw selected"
            )

    def _review_selected(self) -> None:
        view = self._selected_view()
        if view is None:
            return
        api = self.api_provider()
        if api is None:
            messagebox.showinfo("Sign in needed", "Sign in to BOWL.com first.", parent=self)
            return
        result = self.lookup_results.get(view.registration.id)
        if result is not None and result.candidates:
            RegistrationMatchDialog(
                self,
                result,
                lambda member: self._resolve_member(view, member),
            )
            return
        self._start_lookup(
            view.registration.id,
            InputBowler(view.bowler.name, view.bowler.membership_id),
        )

    def _resolve_member(self, view: RegistrationView, member: Member) -> None:
        api = self.api_provider()
        if api is None:
            return
        bowler = InputBowler(view.bowler.name, f"{member.prefix}-{member.suffix}")
        self.status_callback(f"Confirming {member.display_name}…")
        Thread(
            target=self._resolve_worker,
            args=(api, view.registration.id, bowler, member),
            daemon=True,
        ).start()

    def _resolve_worker(
        self,
        api: BowlApi,
        registration_id: str,
        bowler: InputBowler,
        member: Member,
    ) -> None:
        result = resolve_selected_member(api, bowler, member)
        self.after(0, self._lookup_finished, registration_id, result, "Match confirmed")

    def _edit_selected(self) -> None:
        if self.store is None:
            return
        view = self._selected_view()
        if view is None:
            return
        choice = RegistrationEditDialog(
            self, view, list(self.team_by_label)
        ).show()
        if choice is None:
            return
        name, membership_id, team_label, roster_role = choice
        team_id = self.team_by_label.get(team_label, "")
        try:
            self.store.update_registration(
                view.registration.id,
                name,
                membership_id,
                team_id,
                roster_role,
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update bowler", str(error), parent=self)
            return
        self._refresh_after_roster_change()
        if self.api_provider() is not None:
            self._start_lookup(
                view.registration.id, InputBowler(name, membership_id)
            )

    def _toggle_withdrawn(self) -> None:
        if self.store is None:
            return
        view = self._selected_view()
        if view is None:
            return
        try:
            self.store.set_withdrawn(
                view.registration.id, not view.registration.withdrawn
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update registration", str(error), parent=self)
            return
        self._refresh_after_roster_change()

    def close(self) -> None:
        self._unsubscribe_context()
        self.scoring_desk.close()
        for _worker_number in range(2):
            self.lookup_queue.put(None)


class PlayerPickerDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, title: str, bowlers: list[BowlerProfile]
    ) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.title(title)
        self.geometry("560x430")
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text=title,
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="Choose a player from the permanent player directory.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))
        self.table = ttk.Treeview(
            content, columns=("name", "member_id"), show="headings"
        )
        self.table.heading("name", text="Player")
        self.table.heading("member_id", text="Member ID")
        self.table.column("name", width=300, anchor="w")
        self.table.column("member_id", width=160, anchor="w")
        self.table.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=1, sticky="ns")
        for bowler in sorted(bowlers, key=lambda item: item.name.casefold()):
            self.table.insert(
                "",
                tk.END,
                iid=bowler.id,
                values=(bowler.name, bowler.membership_id or "—"),
            )
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=3, column=0, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Add selected", command=self._accept, style="Primary.TButton"
        ).pack(side=tk.LEFT, padx=(8, 0))
        self.table.bind("<Double-1>", lambda _event: self._accept())
        children = self.table.get_children()
        if children:
            self.table.selection_set(children[0])
            self.table.focus(children[0])

    def _accept(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        self.choice = selected[0]
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.choice


class LeagueDirectoryPlayerPickerDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        competition: Competition,
        bowlers: list[BowlerProfile],
        views_by_bowler_id: dict[str, RegistrationView],
    ) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.title("Pull player into roster")
        self.geometry("760x470")
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text=f"Player list for {competition.display_name}",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="The league-status column only reflects the selected league or tournament.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))
        self.table = ttk.Treeview(
            content,
            columns=("name", "member_id", "league_status"),
            show="headings",
        )
        for column, label, width in (
            ("name", "Player", 240),
            ("member_id", "Member ID", 135),
            ("league_status", "Status in selected league", 310),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=1, sticky="ns")
        for bowler in sorted(bowlers, key=lambda item: item.name.casefold()):
            view = views_by_bowler_id.get(bowler.id)
            if view is None:
                status = "Not registered in this league"
            elif view.team is not None:
                status = f"{view.team.name} — {view.registration.roster_role.value}"
            elif view.registration.roster_role is RosterRole.SUBSTITUTE:
                status = "League substitute pool"
            else:
                status = "Registered — no team"
            self.table.insert(
                "",
                tk.END,
                iid=bowler.id,
                values=(bowler.name, bowler.membership_id or "—", status),
            )
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=3, column=0, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Add selected",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        self.table.bind("<Double-1>", lambda _event: self._accept())
        children = self.table.get_children()
        if children:
            self.table.selection_set(children[0])
            self.table.focus(children[0])

    def _accept(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        self.choice = selected[0]
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.choice


class TeamCopyDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        target: Competition,
        competitions: list[Competition],
        teams: list[Team],
        registrations: list[Registration],
    ) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str, bool] | None = None
        self.team_by_id = {team.id: team for team in teams}
        competition_by_id = {item.id: item for item in competitions}
        active_counts: dict[str, int] = {}
        for registration in registrations:
            if registration.team_id and not registration.withdrawn:
                active_counts[registration.team_id] = (
                    active_counts.get(registration.team_id, 0) + 1
                )
        self.title("Copy existing team")
        self.geometry("760x520")
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text=f"Copy a team into {target.display_name}",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="Choose a team from another league season or tournament.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))
        self.table = ttk.Treeview(
            content,
            columns=("source", "team", "players"),
            show="headings",
            height=9,
        )
        for column, label, width in (
            ("source", "League / tournament", 360),
            ("team", "Team", 230),
            ("players", "Active players", 100),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=1, sticky="ns")
        for team in sorted(
            teams,
            key=lambda item: (
                competition_by_id[item.competition_id].display_name.casefold(),
                item.name.casefold(),
            ),
        ):
            source = competition_by_id[team.competition_id]
            source_label = source.display_name
            if source.archived:
                source_label += " (archived)"
            self.table.insert(
                "",
                tk.END,
                iid=team.id,
                values=(source_label, team.name, active_counts.get(team.id, 0)),
            )
        options = ttk.Frame(content, style="App.TFrame")
        options.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="New team name", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.name_var = tk.StringVar()
        ttk.Entry(options, textvariable=self.name_var).grid(
            row=0, column=1, sticky="ew"
        )
        self.copy_roster_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options,
            text="Copy active team roster (old averages are not copied)",
            variable=self.copy_roster_var,
        ).grid(row=1, column=1, sticky="w", pady=(10, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=4, column=0, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Copy team",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        self.table.bind("<<TreeviewSelect>>", lambda _event: self._team_selected())
        self.table.bind("<Double-1>", lambda _event: self._accept())
        children = self.table.get_children()
        if children:
            self.table.selection_set(children[0])
            self.table.focus(children[0])
            self._team_selected()

    def _team_selected(self) -> None:
        selected = self.table.selection()
        if selected:
            self.name_var.set(self.team_by_id[selected[0]].name)

    def _accept(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Team name needed", "Enter a team name.", parent=self)
            return
        self.choice = (selected[0], name, self.copy_roster_var.get())
        self.destroy()

    def show(self) -> tuple[str, str, bool] | None:
        self.wait_window()
        return self.choice


class RegistrationTeamChoiceDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        competition: Competition,
        teams: list[Team],
        current_team_id: str = "",
        current_new_team_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.teams = teams
        self.choice: tuple[str, str] | None = None
        self.team_id_by_label = {team.name: team.id for team in teams}
        current_label = next(
            (team.name for team in teams if team.id == current_team_id), "Unassigned"
        )
        self.title(f"Team — {competition.display_name}")
        self.geometry("560x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text=competition.display_name,
            style="Muted.TLabel",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
        ttk.Label(content, text="Existing team", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=7
        )
        self.team_var = tk.StringVar(value=current_label)
        ttk.Combobox(
            content,
            textvariable=self.team_var,
            values=["Unassigned", *self.team_id_by_label],
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", pady=7)
        ttk.Label(content, text="Or create team", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=7
        )
        self.new_team_var = tk.StringVar(value=current_new_team_name)
        new_team_entry = ttk.Entry(content, textvariable=self.new_team_var)
        new_team_entry.grid(row=2, column=1, sticky="ew", pady=7)
        ttk.Label(
            content,
            text="A new team name takes priority over the existing-team choice.",
            style="Muted.TLabel",
        ).grid(row=3, column=1, sticky="w", pady=(4, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Use team", command=self._accept, style="Warm.TButton"
        ).pack(side=tk.LEFT, padx=(8, 0))
        new_team_entry.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        new_team_name = self.new_team_var.get().strip()
        self.choice = (
            "" if new_team_name else self.team_id_by_label.get(self.team_var.get(), ""),
            new_team_name,
        )
        self.destroy()

    def show(self) -> tuple[str, str] | None:
        self.wait_window()
        return self.choice


class MultiLeagueRegistrationDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        competitions: list[Competition],
        teams: list[Team],
        initial_name: str = "",
        initial_membership_id: str = "",
        initial_competition_id: str = "",
        initial_team_id: str = "",
    ) -> None:
        super().__init__(parent)
        self.competition_by_id = {item.id: item for item in competitions}
        self.teams = teams
        self.assignments: dict[str, tuple[str, str]] = {}
        if initial_competition_id:
            self.assignments[initial_competition_id] = (initial_team_id, "")
        self.choice: tuple[str, str, list[RegistrationTarget]] | None = None
        self.title("Register bowler in multiple leagues")
        self.geometry("780x590")
        self.minsize(700, 520)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(4, weight=1)
        ttk.Label(
            content,
            text="Register bowler",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(content, text="Bowler name", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=(16, 6)
        )
        self.name_var = tk.StringVar(value=initial_name.strip())
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(16, 6))
        ttk.Label(content, text="Member ID", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=6
        )
        self.id_var = tk.StringVar(value=initial_membership_id.strip())
        ttk.Entry(content, textvariable=self.id_var).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=6
        )
        ttk.Label(
            content,
            text=(
                "Select every league or tournament this bowler is joining. "
                "Use Ctrl-click for more than one, then set a team for each as needed."
            ),
            style="Muted.TLabel",
            wraplength=690,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 10))
        self.table = ttk.Treeview(
            content,
            columns=("workspace", "team"),
            show="headings",
            selectmode="extended",
        )
        self.table.heading("workspace", text="League / tournament")
        self.table.heading("team", text="Team assignment")
        self.table.column("workspace", width=430, stretch=True, anchor="w")
        self.table.column("team", width=220, stretch=True, anchor="w")
        self.table.grid(row=4, column=0, columnspan=2, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=4, column=2, sticky="ns")
        for competition in competitions:
            self.table.insert(
                "",
                tk.END,
                iid=competition.id,
                values=(competition.selection_label, self._team_label(competition.id)),
            )
        if initial_competition_id and self.table.exists(initial_competition_id):
            self.table.selection_set(initial_competition_id)
            self.table.focus(initial_competition_id)
            self.table.see(initial_competition_id)
        elif competitions:
            self.table.selection_set(competitions[0].id)
            self.table.focus(competitions[0].id)
        self.table.bind("<Double-1>", lambda _event: self._set_team())
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        ttk.Button(buttons, text="Set team for highlighted league", command=self._set_team).pack(
            side=tk.LEFT
        )
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(
            buttons,
            text="Register bowler",
            command=self._accept,
            style="Warm.TButton",
        ).pack(side=tk.RIGHT, padx=(0, 8))
        name_entry.focus_set()

    def _team_label(self, competition_id: str) -> str:
        team_id, new_team_name = self.assignments.get(competition_id, ("", ""))
        if new_team_name:
            return f"New team: {new_team_name}"
        team = next((item for item in self.teams if item.id == team_id), None)
        return team.name if team else "Unassigned"

    def _set_team(self) -> None:
        competition_id = self.table.focus()
        if not competition_id:
            selected = self.table.selection()
            competition_id = selected[0] if selected else ""
        competition = self.competition_by_id.get(competition_id)
        if competition is None:
            return
        current_team_id, current_new_team_name = self.assignments.get(
            competition_id, ("", "")
        )
        choice = RegistrationTeamChoiceDialog(
            self,
            competition,
            [team for team in self.teams if team.competition_id == competition_id],
            current_team_id,
            current_new_team_name,
        ).show()
        if choice is None:
            return
        self.assignments[competition_id] = choice
        self.table.set(competition_id, "team", self._team_label(competition_id))

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Enter a bowler name.", parent=self)
            return
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning(
                "League needed",
                "Select at least one league or tournament.",
                parent=self,
            )
            return
        targets = []
        for competition_id in selected:
            team_id, new_team_name = self.assignments.get(competition_id, ("", ""))
            targets.append(
                RegistrationTarget(
                    competition_id=competition_id,
                    team_id=team_id,
                    new_team_name=new_team_name,
                )
            )
        self.choice = (name, self.id_var.get().strip(), targets)
        self.destroy()

    def show(self) -> tuple[str, str, list[RegistrationTarget]] | None:
        self.wait_window()
        return self.choice


class LeaguePlayerDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        teams: list[Team],
        default_team_id: str = "",
        default_role: RosterRole = RosterRole.REGULAR,
    ) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str, str, RosterRole] | None = None
        self.team_id_by_label = {team.name: team.id for team in teams}
        selected_team = next(
            (team.name for team in teams if team.id == default_team_id), "Unassigned"
        )
        self.title("Add league player")
        self.geometry("540x390")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text="Add player",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
        self.name_var = tk.StringVar()
        self.id_var = tk.StringVar()
        self.team_var = tk.StringVar(value=selected_team)
        self.role_var = tk.StringVar(value=default_role.value)
        for row, label in enumerate(
            ("Player name", "Member ID", "Team", "Roster role"), start=1
        ):
            ttk.Label(content, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=7
            )
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=1, column=1, sticky="ew", pady=7)
        ttk.Entry(content, textvariable=self.id_var).grid(
            row=2, column=1, sticky="ew", pady=7
        )
        ttk.Combobox(
            content,
            textvariable=self.team_var,
            values=["Unassigned", *self.team_id_by_label],
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=7)
        ttk.Combobox(
            content,
            textvariable=self.role_var,
            values=[item.value for item in RosterRole],
            state="readonly",
        ).grid(row=4, column=1, sticky="ew", pady=7)
        ttk.Label(
            content,
            text="An unassigned substitute stays available in the league substitute pool.",
            style="Muted.TLabel",
            wraplength=350,
        ).grid(row=5, column=1, sticky="w", pady=(5, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(22, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Add player", command=self._accept, style="Warm.TButton"
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Enter a player name.", parent=self)
            return
        self.choice = (
            name,
            self.id_var.get().strip(),
            self.team_id_by_label.get(self.team_var.get(), ""),
            RosterRole(self.role_var.get()),
        )
        self.destroy()

    def show(self) -> tuple[str, str, str, RosterRole] | None:
        self.wait_window()
        return self.choice


class PoolPickerDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, pools: list[PlayerPool], current_pool_id: str
    ) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.pool_id_by_label = {item.label: item.id for item in pools}
        current = next(
            (item.label for item in pools if item.id == current_pool_id), "No linked pool"
        )
        self.title("Link player pool")
        self.geometry("500x250")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        ttk.Label(
            content,
            text="Link a season player pool",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="New registrations will also be added to this year’s player pool.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 16))
        self.pool_var = tk.StringVar(value=current)
        pool_box = ttk.Combobox(
            content,
            textvariable=self.pool_var,
            values=["No linked pool", *self.pool_id_by_label],
            state="readonly",
        )
        pool_box.grid(row=2, column=0, sticky="ew")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=3, column=0, sticky="e", pady=(22, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Save link", command=self._accept, style="Primary.TButton"
        ).pack(side=tk.LEFT, padx=(8, 0))
        pool_box.focus_set()

    def _accept(self) -> None:
        self.choice = self.pool_id_by_label.get(self.pool_var.get(), "")
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.choice


class PlayerEditDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, name: str, membership_id: str) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str] | None = None
        self.title("Edit player")
        self.geometry("500x290")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text="Edit player identity",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.name_var = tk.StringVar(value=name)
        self.id_var = tk.StringVar(value=membership_id)
        ttk.Label(content, text="Player name", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=7
        )
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=1, column=1, sticky="ew", pady=7)
        ttk.Label(content, text="Member ID", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=7
        )
        ttk.Entry(content, textvariable=self.id_var).grid(
            row=2, column=1, sticky="ew", pady=7
        )
        ttk.Label(
            content,
            text=(
                "This updates the player across every season. "
                "Saved averages will need rechecking."
            ),
            style="Muted.TLabel",
            wraplength=340,
        ).grid(row=3, column=1, sticky="w", pady=(5, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(24, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Save player",
            command=self._accept,
            style="Warm.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Enter a player name.", parent=self)
            return
        self.choice = (name, self.id_var.get().strip())
        self.destroy()

    def show(self) -> tuple[str, str] | None:
        self.wait_window()
        return self.choice


class CompetitionDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, competition: Competition | None = None
    ) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str, CompetitionKind] | None = None
        self.competition = competition
        self.title("Edit league or tournament" if competition else "New league or tournament")
        self.geometry("500x320")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text=(
                "Edit league or tournament"
                if competition
                else "Create a registration workspace"
            ),
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.kind_var = tk.StringVar(
            value=competition.kind.value if competition else CompetitionKind.LEAGUE.value
        )
        self.name_var = tk.StringVar(value=competition.name if competition else "")
        self.season_var = tk.StringVar(value=competition.season if competition else "")
        for row, label in enumerate(("Type", "Name", "Season or year"), start=1):
            ttk.Label(content, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=7
            )
        ttk.Combobox(
            content,
            textvariable=self.kind_var,
            values=[item.value for item in CompetitionKind],
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", pady=7)
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=2, column=1, sticky="ew", pady=7)
        ttk.Entry(content, textvariable=self.season_var).grid(
            row=3, column=1, sticky="ew", pady=7
        )
        ttk.Label(
            content,
            text="Example: Monday Misfits, 2026–27",
            style="Muted.TLabel",
        ).grid(row=4, column=1, sticky="w")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(26, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Save changes" if competition else "Create",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Enter a name.", parent=self)
            return
        self.choice = (
            name,
            self.season_var.get().strip(),
            CompetitionKind(self.kind_var.get()),
        )
        self.destroy()

    def show(self) -> tuple[str, str, CompetitionKind] | None:
        self.wait_window()
        return self.choice


class TeamRegistrationDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, teams: list[str]) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str] | None = None
        self.title("Register a whole team")
        self.geometry("620x510")
        self.minsize(540, 430)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(4, weight=1)
        ttk.Label(
            content,
            text="Register a whole team",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="Use an existing team or type a new team name.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))
        self.team_var = tk.StringVar(value=teams[0] if teams else "")
        team_box = ttk.Combobox(content, textvariable=self.team_var, values=teams)
        team_box.grid(row=2, column=0, sticky="ew")
        ttk.Label(
            content,
            text="One bowler per line. Member IDs are optional: Jane Smith (1234-567890)",
            style="Muted.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(16, 6))
        self.roster = tk.Text(
            content,
            height=12,
            background="#263139",
            foreground="#EDF4FA",
            insertbackground="#EDF4FA",
            relief=tk.FLAT,
            padx=10,
            pady=8,
        )
        self.roster.grid(row=4, column=0, sticky="nsew")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Register team",
            command=self._accept,
            style="Warm.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        team_box.focus_set()

    def _accept(self) -> None:
        team = self.team_var.get().strip()
        roster = self.roster.get("1.0", tk.END).strip()
        if not team or not roster:
            messagebox.showwarning(
                "Team and bowlers needed",
                "Enter a team name and at least one bowler.",
                parent=self,
            )
            return
        self.choice = (team, roster)
        self.destroy()

    def show(self) -> tuple[str, str] | None:
        self.wait_window()
        return self.choice


class RegistrationEditDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, view: RegistrationView, teams: list[str]
    ) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str, str, RosterRole] | None = None
        self.title("Edit registration")
        self.geometry("520x410")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text="Edit registration",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.name_var = tk.StringVar(value=view.bowler.name)
        self.id_var = tk.StringVar(value=view.bowler.membership_id)
        self.team_var = tk.StringVar(value=view.team.name if view.team else "Unassigned")
        self.role_var = tk.StringVar(value=view.registration.roster_role.value)
        for row, label in enumerate(
            ("Bowler name", "Member ID", "Team", "Roster role"), start=1
        ):
            ttk.Label(content, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=7
            )
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=1, column=1, sticky="ew", pady=7)
        ttk.Entry(content, textvariable=self.id_var).grid(
            row=2, column=1, sticky="ew", pady=7
        )
        ttk.Combobox(
            content,
            textvariable=self.team_var,
            values=["Unassigned", *teams],
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=7)
        ttk.Combobox(
            content,
            textvariable=self.role_var,
            values=[item.value for item in RosterRole],
            state="readonly",
        ).grid(row=4, column=1, sticky="ew", pady=7)
        ttk.Label(
            content,
            text=(
                "An unassigned substitute stays in the league-wide substitute pool. "
                "Identity changes will recheck the bowler when signed in."
            ),
            style="Muted.TLabel",
            wraplength=330,
        ).grid(row=5, column=1, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(26, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Save changes", command=self._accept, style="Warm.TButton"
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Enter a bowler name.", parent=self)
            return
        self.choice = (
            name,
            self.id_var.get().strip(),
            self.team_var.get(),
            RosterRole(self.role_var.get()),
        )
        self.destroy()

    def show(self) -> tuple[str, str, str, RosterRole] | None:
        self.wait_window()
        return self.choice


class RegistrationMatchDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        result: LookupResult,
        on_select: Callable[[Member], None],
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.on_select = on_select
        self.title("Choose the right bowler")
        self.geometry("700x470")
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)
        ttk.Label(
            content,
            text=f"Choose the right {result.input_name}",
            style="Muted.TLabel",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="The rest of registration can continue while this waits.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))
        search_bar = ttk.Frame(content, style="App.TFrame")
        search_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        search_bar.columnconfigure(1, weight=1)
        ttk.Label(search_bar, text="Filter matches", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_bar, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew")
        search_entry.bind("<KeyRelease>", lambda _event: self._render_candidates())
        self.table = ttk.Treeview(
            content,
            columns=("name", "id", "association", "status"),
            show="headings",
        )
        for column, label, width in (
            ("name", "Bowler", 180),
            ("id", "Member ID", 120),
            ("association", "Association", 230),
            ("status", "Status", 80),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=3, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=3, column=1, sticky="ns")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Not now", command=self.destroy).pack(side=tk.LEFT)
        self.use_button = ttk.Button(
            buttons,
            text="Use selected bowler",
            command=self._accept,
            style="Primary.TButton",
        )
        self.use_button.pack(side=tk.LEFT, padx=(8, 0))
        self.table.bind("<Double-1>", lambda _event: self._accept())
        self._render_candidates()

    def _render_candidates(self) -> None:
        self.table.delete(*self.table.get_children())
        query = " ".join(self.search_var.get().split()).casefold()
        visible_ids: list[str] = []
        for index, member in enumerate(self.result.candidates):
            member_id = f"{member.prefix}-{member.suffix}"
            association = ", ".join(
                value
                for value in (member.association, member.association_state)
                if value
            )
            searchable = f"{member.display_name} {member_id} {association}".casefold()
            if query and query not in searchable:
                continue
            item_id = str(index)
            visible_ids.append(item_id)
            self.table.insert(
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
            self.table.selection_set(visible_ids[0])
            self.table.focus(visible_ids[0])
        self.use_button.configure(state=tk.NORMAL if visible_ids else tk.DISABLED)

    def _accept(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        member = self.result.candidates[int(selected[0])]
        self.destroy()
        self.on_select(member)
