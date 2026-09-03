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
from usbc_average_lookup.workspace import LeagueWorkspaceContext


class ScheduleDesk(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        store: RegistrationStore | None,
        status_callback: Callable[[str], None],
        workspace_context: LeagueWorkspaceContext,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.registration_store = store
        self.schedule_store = ScheduleStore(store) if store is not None else None
        self.status_callback = status_callback
        self.workspace_context = workspace_context
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
            text="Schedule & lanes",
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
            text="Generate round robin",
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
            text="Change lane pair",
            command=self._change_lane,
            state=tk.DISABLED,
        )
        self.lane_button.grid(row=0, column=2, padx=(10, 0))

        table_frame = ttk.Frame(self, style="Surface.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            table_frame,
            columns=("lanes", "left", "right", "status"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("lanes", "Lane pair", 110, False),
            ("left", "Team", 260, True),
            ("right", "Opponent", 260, True),
            ("status", "Status", 130, False),
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
        self.table.bind("<<TreeviewSelect>>", lambda _event: self._update_actions())
        self.table.bind("<Double-1>", lambda _event: self._change_lane())

        self.footer_label = ttk.Label(
            self,
            text=(
                "The schedule keeps matchups and lane pairs together. "
                "Scores and standings will connect to these rounds next."
            ),
            style="Muted.TLabel",
        )
        self.footer_label.grid(row=3, column=0, sticky="w", pady=(7, 0))

    def refresh(self) -> None:
        competition = self._competition()
        if competition is None or self.schedule_store is None:
            self.title_label.configure(text="Schedule & lanes")
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
        for match in matches:
            self.table.insert(
                "",
                tk.END,
                iid=match.id,
                values=(
                    match.lane_pair,
                    match.left_team_name,
                    match.right_team_name or "BYE",
                    match.status.value,
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
            "Change lane pair",
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
