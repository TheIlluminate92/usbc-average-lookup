from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, simpledialog, ttk

from usbc_average_lookup.services.registration import (
    Competition,
    CompetitionFormat,
    RegistrationDataError,
    RegistrationStore,
)
from usbc_average_lookup.services.scheduling import (
    CompetitionMatch,
    CompetitionRound,
    ScheduleStore,
)
from usbc_average_lookup.services.scoring import SessionStatus
from usbc_average_lookup.services.standings import StandingsStore
from usbc_average_lookup.ui_helpers import ButtonHint
from usbc_average_lookup.workspace import LeagueWorkspaceContext


class ScheduleDesk(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        store: RegistrationStore | None,
        status_callback: Callable[[str], None],
        workspace_context: LeagueWorkspaceContext,
        open_scores: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.registration_store = store
        self.schedule_store = ScheduleStore(store) if store is not None else None
        self.status_callback = status_callback
        self.workspace_context = workspace_context
        self.open_scores = open_scores
        self.standings_store = StandingsStore(store) if store else None
        self.round_var = tk.StringVar()
        self.round_by_label: dict[str, CompetitionRound] = {}
        self.matches: dict[str, CompetitionMatch] = {}
        self._build()
        self._unsubscribe_context = workspace_context.subscribe(
            lambda _competition_id: self.refresh()
        )

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        heading = ttk.Frame(self, style="Surface.TFrame", padding=(12, 10))
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(
            heading,
            text="Schedule",
            style="Surface.TLabel",
            font=("Segoe UI", 15, "bold"),
        )
        self.title_label.grid(row=0, column=0, sticky="w")
        self.detail_label = ttk.Label(
            heading,
            text="Choose a league or tournament above.",
            style="Subtitle.TLabel",
        )
        self.detail_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.generate_button = ttk.Button(
            heading,
            text="Build schedule…",
            command=self._generate,
            state=tk.DISABLED,
            style="Primary.TButton",
        )
        self.generate_button.grid(row=0, column=1, rowspan=2, sticky="e")

        controls = ttk.Frame(self, style="Surface.TFrame", padding=(12, 9))
        controls.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Week / round", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.round_box = ttk.Combobox(
            controls,
            textvariable=self.round_var,
            state="disabled",
        )
        self.round_box.grid(row=0, column=1, sticky="ew")
        self.round_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_matches()
        )
        self.lane_button = ttk.Button(
            controls,
            text="Change lanes…",
            command=self._change_lane,
            state=tk.DISABLED,
        )
        self.lane_button.grid(row=0, column=2, padx=(10, 0))
        self.score_button = ttk.Button(controls, text="Link scores…", command=self._open_scores)
        self.score_button.grid(row=0, column=3, padx=(8, 0))
        self.unlink_button = ttk.Button(controls, text="Unlink…", command=self._unlink)
        self.unlink_button.grid(row=0, column=4, padx=(8, 0))
        ButtonHint(
            self.generate_button,
            "Build a full round-robin cycle with rotating lane pairs and BYEs for odd team counts.",
        )
        ButtonHint(
            self.lane_button,
            "Choose a different lane pair for this matchup without changing its opponents.",
        )

        table_frame = ttk.Frame(self, style="Surface.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            table_frame,
            columns=("lanes", "left", "right", "status", "pins", "points"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("lanes", "Lane pair", 110, False),
            ("left", "Team", 260, True),
            ("right", "Opponent", 260, True),
            ("status", "Result", 210, True),
            ("pins", "Series (left / right)", 145, False),
            ("points", "Points (left / right)", 145, False),
        ):
            self.table.heading(column, text=label)
            self.table.column(
                column, width=width, minwidth=80, stretch=stretch, anchor="w"
            )
        scroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.table.yview
        )
        self.table.configure(yscrollcommand=scroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(xscrollcommand=horizontal.set)
        self.table.bind("<<TreeviewSelect>>", lambda _event: self._update_actions())
        self.table.bind("<Double-1>", lambda _event: self._change_lane())

        self.footer_label = ttk.Label(
            self,
            text=(
                "The schedule keeps matchups and lane pairs together. "
                "Link a score week explicitly; only finalized scores count toward standings."
            ),
            style="Muted.TLabel",
        )
        self.footer_label.grid(row=3, column=0, sticky="w", pady=(7, 0))

    def refresh(self) -> None:
        competition = self._competition()
        if competition is None or self.schedule_store is None:
            self.title_label.configure(text="Schedule")
            self.detail_label.configure(text="Choose a league or tournament above.")
            self.generate_button.configure(state=tk.DISABLED)
            self.round_by_label = {}
            self.round_box.configure(values=(), state="disabled")
            self.round_var.set("")
            self._render_matches()
            return

        rounds = self.schedule_store.list_rounds(competition.id)
        self.round_by_label = {round_.display_name: round_ for round_ in rounds}
        labels = list(self.round_by_label)
        self.title_label.configure(text=f"{competition.display_name} schedule")
        self.detail_label.configure(
            text=(
                f"{competition.competition_format.value} • "
                f"{len(self.registration_store.list_teams(competition.id))} teams • "
                f"{len(rounds)} rounds"
            )
        )
        can_generate = (
            competition.competition_format is CompetitionFormat.ROUND_ROBIN
            and not competition.archived
            and not rounds
        )
        self.generate_button.configure(
            state=tk.NORMAL if can_generate else tk.DISABLED
        )
        self.round_box.configure(
            values=labels, state="readonly" if labels else "disabled"
        )
        if self.round_var.get() not in self.round_by_label:
            self.round_var.set(labels[0] if labels else "")
        self._render_matches()

    def _competition(self) -> Competition | None:
        if self.registration_store is None:
            return None
        return next(
            (
                competition
                for competition in self.registration_store.competitions
                if competition.id == self.workspace_context.competition_id
            ),
            None,
        )

    def close(self) -> None:
        self._unsubscribe_context()

    def _round(self) -> CompetitionRound | None:
        return self.round_by_label.get(self.round_var.get())

    def _render_matches(self) -> None:
        self.table.delete(*self.table.get_children())
        round_ = self._round()
        if round_ is None or self.schedule_store is None:
            self.matches = {}
            self._update_actions()
            return
        matches = self.schedule_store.list_matches(round_.id)
        self.matches = {match.id: match for match in matches}
        results = {r.match_id: r for r in self.standings_store.round_results(round_.id)}
        for match in matches:
            result = results[match.id]
            self.table.insert(
                "",
                tk.END,
                iid=match.id,
                values=(
                    match.lane_pair,
                    match.left_team_name,
                    match.right_team_name or "BYE",
                    result.status,
                    (f"{result.left_total} / {result.right_total}"
                     if result.left_total is not None else "—"),
                    (f"{result.left_points} / {result.right_points}"
                     if result.status == "Final" else "—"),
                ),
            )
        self._update_actions()

    def _selected_match(self) -> CompetitionMatch | None:
        selected = self.table.selection()
        return self.matches.get(selected[0]) if selected else None

    def _update_actions(self) -> None:
        match = self._selected_match()
        self.lane_button.configure(
            state=tk.NORMAL if match is not None and not match.is_bye else tk.DISABLED
        )
        round_ = self._round()
        linked = (self.standings_store.linked_session(round_.id)
                  if self.standings_store and round_ else None)
        self.score_button.configure(
            text="Open scores" if linked else "Link scores…",
            state=tk.NORMAL if round_ and self.open_scores else tk.DISABLED,
        )
        self.unlink_button.configure(state=tk.NORMAL if linked else tk.DISABLED)

    def _open_scores(self) -> None:
        round_ = self._round()
        if not round_ or not self.standings_store or not self.open_scores:
            return
        linked = self.standings_store.linked_session(round_.id)
        if linked:
            self.open_scores(linked)
            return
        LinkScoresDialog(self, self.standings_store, round_, self.open_scores)

    def _unlink(self) -> None:
        round_ = self._round()
        if not round_ or not self.standings_store:
            return
        reason = simpledialog.askstring(
            "Unlink scores", "Reason for unlinking this score week (scores are kept):", parent=self,
        )
        if reason is None:
            return
        try:
            self.standings_store.unlink(round_.id, reason)
        except RegistrationDataError as error:
            messagebox.showerror("Could not unlink", str(error), parent=self)
        self.refresh()

    def _generate(self) -> None:
        competition = self._competition()
        if competition is None or self.schedule_store is None:
            return
        first_lane = simpledialog.askinteger(
            "Generate round-robin schedule",
            (
                "Enter the first lane in the league's lane block.\n\n"
                "The program will pair it with the next lane and rotate all teams "
                "through the available pairs."
            ),
            parent=self,
            initialvalue=1,
            minvalue=1,
        )
        if first_lane is None:
            return
        try:
            rounds = self.schedule_store.generate_round_robin(
                competition.id, first_lane=first_lane
            )
        except RegistrationDataError as error:
            messagebox.showerror("Could not make schedule", str(error), parent=self)
            return
        self.status_callback(
            f"Created {len(rounds)} rounds for {competition.display_name}"
        )
        self.refresh()

    def _change_lane(self) -> None:
        match = self._selected_match()
        if match is None or match.is_bye or self.schedule_store is None:
            return
        lane = simpledialog.askinteger(
            "Change lanes",
            f"Enter the first lane for {match.matchup}:",
            parent=self,
            initialvalue=match.lane_start or 1,
            minvalue=1,
        )
        if lane is None:
            return
        try:
            self.schedule_store.update_match_lane(match.id, lane)
        except RegistrationDataError as error:
            messagebox.showerror("Could not change lanes", str(error), parent=self)
            return
        self.status_callback(f"Moved {match.matchup} to lanes {lane}–{lane + 1}")
        self._render_matches()


class LinkScoresDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, store: StandingsStore, round_: CompetitionRound,
                 open_scores: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.title(f"Link scores — {round_.display_name}")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.store, self.round, self.open_scores = store, round_, open_scores
        sessions = store.scores.list_sessions(round_.competition_id)
        self.sessions = {s.display_name: s for s in sessions if s.status is SessionStatus.DRAFT}
        self.choice = tk.StringVar(value=next(iter(self.sessions), ""))
        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Choose an existing Draft score week:").pack(anchor="w")
        ttk.Combobox(body, textvariable=self.choice, values=list(self.sessions),
                     state="readonly", width=55).pack(fill=tk.X, pady=8)
        ttk.Button(body, text="Link selected week", command=self._link).pack(fill=tk.X)
        self.create = ttk.Button(body, text=f"Create and link week {round_.round_number}",
                                 command=self._create)
        self.create.pack(fill=tk.X, pady=8)
        if any(s.week_number == round_.round_number for s in sessions):
            self.create.configure(state=tk.DISABLED)
        ttk.Label(body, wraplength=450, text=(
            "Each week can belong to one round. Final weeks must be reopened first. "
            "The current standings points rules will be saved with this link."
        )).pack(pady=8)
        self.error = ttk.Label(body, wraplength=450)
        self.error.pack()
        ttk.Button(body, text="Cancel", command=self.destroy).pack()
        self.bind("<Escape>", lambda _event: self.destroy())

    def _link(self) -> None:
        session = self.sessions.get(self.choice.get())
        if session:
            self._finish(session.id)

    def _create(self) -> None:
        try:
            session = self.store.scores.create_session(
                self.round.competition_id, self.round.round_number, self.round.scheduled_on,
            )
        except RegistrationDataError as error:
            self.error.configure(text=str(error))
            return
        self.sessions[session.display_name] = session
        self.choice.set(session.display_name)
        self.create.configure(state=tk.DISABLED)
        self._finish(session.id)

    def _finish(self, session_id: str) -> None:
        try:
            self.store.link(self.round.id, session_id)
        except RegistrationDataError as error:
            self.error.configure(text=str(error))
            return
        self.destroy()
        self.open_scores(session_id)
