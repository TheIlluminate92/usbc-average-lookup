from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk

from usbc_average_lookup.services.average_rules import AverageRounding
from usbc_average_lookup.services.registration import (
    Competition,
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
    RegistrationView,
    Team,
)
from usbc_average_lookup.services.scoring import (
    GameScore,
    GameStatus,
    LeagueSession,
    ScoreLineView,
    ScoringStore,
    SessionStatus,
)


class ScoringDesk(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        store: RegistrationStore | None,
        status_callback: Callable[[str], None],
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.registration_store = store
        self.scoring_store = ScoringStore(store) if store is not None else None
        self.status_callback = status_callback
        self.competition_var = tk.StringVar()
        self.session_var = tk.StringVar()
        self.team_filter_var = tk.StringVar(value="All teams")
        self.competition_by_label: dict[str, Competition] = {}
        self.session_by_label: dict[str, LeagueSession] = {}
        self.team_by_name: dict[str, Team] = {}
        self.current_sheet: list[ScoreLineView] = []
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=3)
        self.rowconfigure(4, weight=1)

        heading = ttk.Frame(self, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(
            heading,
            text="League Scores",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text="Permanent weekly score sheets with automatic team totals.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.settings_button = ttk.Button(
            heading,
            text="League scoring settings",
            command=self._edit_settings,
            state=tk.DISABLED,
        )
        self.settings_button.grid(row=0, column=1, rowspan=2, sticky="e")

        selectors = ttk.Frame(self, style="Surface.TFrame", padding=14)
        selectors.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        selectors.columnconfigure(1, weight=1)
        selectors.columnconfigure(3, weight=1)
        ttk.Label(selectors, text="League season", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.competition_box = ttk.Combobox(
            selectors, textvariable=self.competition_var, state="readonly"
        )
        self.competition_box.grid(row=0, column=1, sticky="ew")
        self.competition_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._competition_changed()
        )
        ttk.Label(selectors, text="Score sheet", style="Surface.TLabel").grid(
            row=0, column=2, sticky="w", padx=(14, 8)
        )
        self.session_box = ttk.Combobox(
            selectors, textvariable=self.session_var, state="disabled"
        )
        self.session_box.grid(row=0, column=3, sticky="ew")
        self.session_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._session_changed()
        )
        self.new_session_button = ttk.Button(
            selectors,
            text="New week",
            command=self._new_session,
            state=tk.DISABLED,
        )
        self.new_session_button.grid(row=0, column=4, padx=(10, 0))
        self.final_button = ttk.Button(
            selectors,
            text="Finalize week",
            command=self._toggle_final,
            state=tk.DISABLED,
        )
        self.final_button.grid(row=0, column=5, padx=(8, 0))

        actions = ttk.Frame(self, style="Surface.TFrame", padding=12)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        actions.columnconfigure(1, weight=1)
        ttk.Label(actions, text="Show team", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.team_filter_box = ttk.Combobox(
            actions,
            textvariable=self.team_filter_var,
            state="disabled",
            width=24,
        )
        self.team_filter_box.grid(row=0, column=1, sticky="w")
        self.team_filter_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_sheet()
        )
        self.session_status_label = ttk.Label(
            actions, text="Choose a league", style="Surface.TLabel"
        )
        self.session_status_label.grid(
            row=0, column=2, columnspan=3, sticky="w", padx=(12, 12)
        )
        self.log_button = ttk.Button(
            actions,
            text="Change log",
            command=self._show_change_log,
            state=tk.DISABLED,
        )
        self.log_button.grid(row=0, column=6)
        self.history_button = ttk.Button(
            actions,
            text="History",
            command=self.show_history,
            state=tk.DISABLED,
        )
        self.history_button.grid(row=0, column=5, padx=(8, 0))
        self.remove_button = ttk.Button(
            actions,
            text="Remove row",
            command=self._remove_selected,
            state=tk.DISABLED,
        )
        self.remove_button.grid(row=1, column=4, pady=(8, 0))
        self.vacancy_button = ttk.Button(
            actions,
            text="Add vacancy",
            command=self._add_vacancy,
            state=tk.DISABLED,
        )
        self.vacancy_button.grid(row=1, column=5, padx=(8, 0), pady=(8, 0))
        self.add_player_button = ttk.Button(
            actions,
            text="Add player back / substitute",
            command=self._add_score_player,
            state=tk.DISABLED,
        )
        self.add_player_button.grid(row=1, column=6, padx=(8, 0), pady=(8, 0))

        sheet_frame = ttk.Frame(self, style="Surface.TFrame")
        sheet_frame.grid(row=3, column=0, sticky="nsew")
        sheet_frame.columnconfigure(0, weight=1)
        sheet_frame.rowconfigure(0, weight=1)
        self.sheet_table = ttk.Treeview(sheet_frame, show="headings")
        self.sheet_table.grid(row=0, column=0, sticky="nsew")
        sheet_scroll_y = ttk.Scrollbar(
            sheet_frame, orient=tk.VERTICAL, command=self.sheet_table.yview
        )
        sheet_scroll_x = ttk.Scrollbar(
            sheet_frame, orient=tk.HORIZONTAL, command=self.sheet_table.xview
        )
        self.sheet_table.configure(
            yscrollcommand=sheet_scroll_y.set, xscrollcommand=sheet_scroll_x.set
        )
        sheet_scroll_y.grid(row=0, column=1, sticky="ns")
        sheet_scroll_x.grid(row=1, column=0, sticky="ew")
        self.sheet_table.bind(
            "<<TreeviewSelect>>", lambda _event: self._update_actions()
        )
        self.sheet_table.bind("<Double-1>", lambda _event: self._edit_selected())

        totals_frame = ttk.Frame(self, style="Surface.TFrame", padding=(10, 8))
        totals_frame.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        totals_frame.columnconfigure(0, weight=1)
        totals_frame.rowconfigure(1, weight=1)
        ttk.Label(
            totals_frame,
            text="Team totals — scratch / with handicap",
            style="Surface.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.totals_table = ttk.Treeview(totals_frame, show="headings", height=4)
        self.totals_table.grid(row=1, column=0, sticky="nsew")
        totals_scroll = ttk.Scrollbar(
            totals_frame, orient=tk.VERTICAL, command=self.totals_table.yview
        )
        self.totals_table.configure(yscrollcommand=totals_scroll.set)
        totals_scroll.grid(row=1, column=1, sticky="ns")

        ttk.Label(
            self,
            text=(
                "Double-click a player to enter games. Final weeks must be "
                "reopened with a reason before corrections."
            ),
            style="Muted.TLabel",
        ).grid(row=5, column=0, sticky="w", pady=(9, 0))

    def refresh(self) -> None:
        if self.registration_store is None or self.scoring_store is None:
            self.competition_box.configure(values=(), state=tk.DISABLED)
            return
        leagues = sorted(
            (
                competition
                for competition in self.registration_store.competitions
                if competition.kind is CompetitionKind.LEAGUE
            ),
            key=lambda item: (item.season, item.name.casefold()),
            reverse=True,
        )
        self.competition_by_label = {
            competition.selection_label
            + (" — Archived" if competition.archived else ""): competition
            for competition in leagues
        }
        labels = list(self.competition_by_label)
        self.competition_box.configure(
            values=labels, state="readonly" if labels else tk.DISABLED
        )
        if self.competition_var.get() not in self.competition_by_label:
            self.competition_var.set(labels[0] if labels else "")
        self._competition_changed()

    def _competition(self) -> Competition | None:
        return self.competition_by_label.get(self.competition_var.get())

    def _session(self) -> LeagueSession | None:
        return self.session_by_label.get(self.session_var.get())

    def _competition_changed(self) -> None:
        competition = self._competition()
        available = competition is not None and self.scoring_store is not None
        editable = available and not competition.archived
        self.settings_button.configure(state=tk.NORMAL if editable else tk.DISABLED)
        self.new_session_button.configure(state=tk.NORMAL if editable else tk.DISABLED)
        self.history_button.configure(state=tk.NORMAL if available else tk.DISABLED)
        if not available:
            self.session_by_label = {}
            self.session_box.configure(values=(), state=tk.DISABLED)
            self.session_var.set("")
            self._session_changed()
            return
        assert competition is not None and self.scoring_store is not None
        sessions = self.scoring_store.list_sessions(competition.id)
        self.session_by_label = {session.display_name: session for session in sessions}
        labels = list(self.session_by_label)
        self.session_box.configure(
            values=labels, state="readonly" if labels else tk.DISABLED
        )
        if self.session_var.get() not in self.session_by_label:
            self.session_var.set(labels[0] if labels else "")
        self._session_changed()

    def _session_changed(self) -> None:
        session = self._session()
        competition = self._competition()
        teams = (
            self.registration_store.list_teams(competition.id)
            if self.registration_store is not None and competition is not None
            else []
        )
        self.team_by_name = {team.name: team for team in teams}
        team_values = ["All teams", *self.team_by_name]
        self.team_filter_box.configure(
            values=team_values,
            state="readonly" if session is not None else tk.DISABLED,
        )
        if self.team_filter_var.get() not in team_values:
            self.team_filter_var.set("All teams")
        self._render_sheet()

    def _render_sheet(self) -> None:
        session = self._session()
        scoring = self.scoring_store
        selected = self.sheet_table.selection()
        selected_id = selected[0] if selected else ""
        self.sheet_table.delete(*self.sheet_table.get_children())
        self.totals_table.delete(*self.totals_table.get_children())
        if session is None or scoring is None:
            self.current_sheet = []
            self._configure_score_columns(3)
            self.session_status_label.configure(text="Choose or create a score sheet")
            self._update_actions()
            return
        session = scoring.get_session(session.id)
        self.session_by_label[self.session_var.get()] = session
        self.current_sheet = scoring.score_sheet(session.id)
        self._configure_score_columns(session.games_per_player)
        team_filter = self.team_filter_var.get()
        for view in self.current_sheet:
            if team_filter != "All teams" and view.line.team_name != team_filter:
                continue
            role = "Vacancy" if view.line.is_vacancy else view.line.roster_role.value
            game_values = tuple(self._game_display(game) for game in view.games)
            self.sheet_table.insert(
                "",
                tk.END,
                iid=view.line.id,
                values=(
                    view.line.team_name,
                    view.line.player_name,
                    role,
                    view.line.entering_average,
                    view.line.handicap,
                    *game_values,
                    view.scratch_total,
                    view.counted_total,
                ),
            )
        for total in scoring.team_totals(session.id):
            if team_filter != "All teams" and total.team_name != team_filter:
                continue
            games = tuple(
                f"{scratch} / {counted}"
                for scratch, counted in zip(total.scratch, total.counted, strict=True)
            )
            self.totals_table.insert(
                "",
                tk.END,
                iid=total.team_id,
                values=(
                    total.team_name,
                    *games,
                    f"{total.scratch_total} / {total.counted_total}",
                ),
            )
        if selected_id and self.sheet_table.exists(selected_id):
            self.sheet_table.selection_set(selected_id)
            self.sheet_table.focus(selected_id)
        entered = sum(
            game.status is not GameStatus.NOT_ENTERED
            for view in self.current_sheet
            for game in view.games
        )
        possible = len(self.current_sheet) * session.games_per_player
        self.session_status_label.configure(
            text=f"{session.status.value} • {entered} of {possible} games entered"
        )
        self.final_button.configure(
            text="Reopen week" if session.status is SessionStatus.FINAL else "Finalize week"
        )
        self._update_actions()

    def _configure_score_columns(self, game_count: int) -> None:
        game_columns = tuple(f"game_{number}" for number in range(1, game_count + 1))
        columns = (
            "team",
            "player",
            "role",
            "average",
            "handicap",
            *game_columns,
            "scratch",
            "counted",
        )
        self.sheet_table.configure(columns=columns)
        headings = {
            "team": ("Team", 150),
            "player": ("Player", 180),
            "role": ("Role", 85),
            "average": ("Avg", 55),
            "handicap": ("Hcp", 55),
            "scratch": ("Series", 70),
            "counted": ("With Hcp", 80),
        }
        for number, column in enumerate(game_columns, start=1):
            headings[column] = (f"Game {number}", 90)
        for column in columns:
            label, width = headings[column]
            self.sheet_table.heading(column, text=label)
            self.sheet_table.column(
                column,
                width=width,
                minwidth=50,
                stretch=column in ("team", "player"),
                anchor="w" if column in ("team", "player", "role") else "center",
            )
        total_columns = ("team", *game_columns, "total")
        self.totals_table.configure(columns=total_columns)
        self.totals_table.heading("team", text="Team")
        self.totals_table.column("team", width=190, anchor="w", stretch=True)
        for number, column in enumerate(game_columns, start=1):
            self.totals_table.heading(column, text=f"Game {number}")
            self.totals_table.column(column, width=115, anchor="center")
        self.totals_table.heading("total", text="Series")
        self.totals_table.column("total", width=130, anchor="center")

    @staticmethod
    def _game_display(game: GameScore) -> str:
        if game.status is GameStatus.NOT_ENTERED:
            return "—"
        if game.status is GameStatus.BOWLED:
            return str(game.scratch_score)
        if game.status is GameStatus.ABSENT:
            return "Absent"
        return f"{game.status.value} {game.scratch_score or 0}"

    def _selected_line(self) -> ScoreLineView | None:
        selected = self.sheet_table.selection()
        if not selected:
            return None
        return next(
            (view for view in self.current_sheet if view.line.id == selected[0]), None
        )

    def _update_actions(self) -> None:
        session = self._session()
        line = self._selected_line()
        has_session = session is not None
        competition = self._competition()
        is_draft = (
            has_session
            and session.status is SessionStatus.DRAFT
            and competition is not None
            and not competition.archived
        )
        editable_session = has_session and competition is not None and not competition.archived
        self.final_button.configure(
            state=tk.NORMAL if editable_session else tk.DISABLED
        )
        self.log_button.configure(state=tk.NORMAL if has_session else tk.DISABLED)
        self.history_button.configure(
            state=tk.NORMAL if competition is not None else tk.DISABLED
        )
        self.add_player_button.configure(state=tk.NORMAL if is_draft else tk.DISABLED)
        self.vacancy_button.configure(state=tk.NORMAL if is_draft else tk.DISABLED)
        self.remove_button.configure(
            state=tk.NORMAL if is_draft and line is not None else tk.DISABLED
        )

    def _new_session(self) -> None:
        competition = self._competition()
        scoring = self.scoring_store
        if competition is None or scoring is None:
            return
        sessions = scoring.list_sessions(competition.id)
        next_week = max((item.week_number for item in sessions), default=0) + 1
        choice = NewSessionDialog(self, competition, next_week).show()
        if choice is None:
            return
        try:
            session = scoring.create_session(competition.id, *choice)
        except RegistrationDataError as error:
            messagebox.showerror("Could not create score sheet", str(error), parent=self)
            return
        self._competition_changed()
        label = next(
            label for label, item in self.session_by_label.items() if item.id == session.id
        )
        self.session_var.set(label)
        self._session_changed()
        self.status_callback(f"Created {session.display_name}")

    def _edit_settings(self) -> None:
        competition = self._competition()
        store = self.registration_store
        if competition is None or store is None:
            return
        settings = LeagueScoringSettingsDialog(self, competition).show()
        if settings is None:
            return
        try:
            store.update_competition_scoring_settings(competition.id, **settings)
        except RegistrationDataError as error:
            messagebox.showerror("Could not save settings", str(error), parent=self)
            return
        self.refresh()
        self.status_callback(f"Saved scoring settings for {competition.display_name}")

    def _edit_selected(self) -> None:
        session = self._session()
        view = self._selected_line()
        scoring = self.scoring_store
        if session is None or view is None or scoring is None:
            return
        if session.status is SessionStatus.FINAL:
            messagebox.showinfo(
                "Final score sheet",
                "Reopen this week before making a correction.",
                parent=self,
            )
            return
        choice = ScoreEntryDialog(self, view).show()
        if choice is None:
            return
        average, entries, reason = choice
        try:
            scoring.save_line_scores(view.line.id, average, entries, reason)
        except RegistrationDataError as error:
            messagebox.showerror("Could not save scores", str(error), parent=self)
            return
        self._render_sheet()
        self.status_callback(f"Saved scores for {view.line.player_name}")

    def _add_score_player(self) -> None:
        session = self._session()
        competition = self._competition()
        scoring = self.scoring_store
        store = self.registration_store
        if session is None or competition is None or scoring is None or store is None:
            return
        used = {view.line.registration_id for view in self.current_sheet}
        available = [
            view
            for view in store.registration_views(competition.id)
            if not view.registration.withdrawn and view.registration.id not in used
        ]
        if not available:
            messagebox.showinfo(
                "No players available",
                "Every active league player is already on this score sheet.",
                parent=self,
            )
            return
        choice = ScorePlayerPickerDialog(
            self, available, list(self.team_by_name.values())
        ).show()
        if choice is None:
            return
        try:
            scoring.add_registered_player(session.id, *choice)
        except RegistrationDataError as error:
            messagebox.showerror("Could not add player", str(error), parent=self)
            return
        self._render_sheet()

    def _add_vacancy(self) -> None:
        session = self._session()
        scoring = self.scoring_store
        if session is None or scoring is None:
            return
        team = TeamPickerDialog(self, list(self.team_by_name.values())).show()
        if team is None:
            return
        try:
            scoring.add_vacancy(session.id, team)
        except RegistrationDataError as error:
            messagebox.showerror("Could not add vacancy", str(error), parent=self)
            return
        self._render_sheet()

    def _remove_selected(self) -> None:
        view = self._selected_line()
        scoring = self.scoring_store
        if view is None or scoring is None:
            return
        has_scores = any(
            game.status is not GameStatus.NOT_ENTERED for game in view.games
        )
        reason = ""
        if has_scores:
            reason = simpledialog.askstring(
                "Reason required",
                f"Why is {view.line.player_name} being removed from this score sheet?",
                parent=self,
            ) or ""
            if not reason:
                return
        elif not messagebox.askyesno(
            "Remove row",
            f"Remove {view.line.player_name} from this week's score sheet?",
            parent=self,
        ):
            return
        try:
            scoring.remove_line(view.line.id, reason)
        except RegistrationDataError as error:
            messagebox.showerror("Could not remove row", str(error), parent=self)
            return
        self._render_sheet()

    def _toggle_final(self) -> None:
        session = self._session()
        scoring = self.scoring_store
        if session is None or scoring is None:
            return
        try:
            if session.status is SessionStatus.FINAL:
                reason = simpledialog.askstring(
                    "Reason required",
                    "Why is this finalized score sheet being reopened?",
                    parent=self,
                )
                if not reason:
                    return
                scoring.reopen_session(session.id, reason)
            else:
                if not messagebox.askyesno(
                    "Finalize score sheet",
                    "Finalize this week? It must be reopened with a reason before corrections.",
                    parent=self,
                ):
                    return
                scoring.finalize_session(session.id)
        except RegistrationDataError as error:
            messagebox.showerror("Could not update score sheet", str(error), parent=self)
            return
        self._competition_changed()

    def _show_change_log(self) -> None:
        session = self._session()
        scoring = self.scoring_store
        if session is None or scoring is None:
            return
        ChangeLogDialog(self, session, scoring.change_log(session.id))

    def select_competition(
        self,
        competition_id: str,
        *,
        show_history: bool = False,
        team_id: str = "",
    ) -> None:
        self.refresh()
        label = next(
            (
                label
                for label, competition in self.competition_by_label.items()
                if competition.id == competition_id
            ),
            "",
        )
        if not label:
            return
        self.competition_var.set(label)
        self._competition_changed()
        if show_history:
            self.show_history(team_id)

    def show_history(self, team_id: str = "") -> None:
        competition = self._competition()
        scoring = self.scoring_store
        store = self.registration_store
        if competition is None or scoring is None or store is None:
            return
        if not team_id and self.team_filter_var.get() != "All teams":
            selected_team = self.team_by_name.get(self.team_filter_var.get())
            team_id = selected_team.id if selected_team is not None else ""
        selected_session_id = LeagueHistoryDialog(
            self,
            competition,
            scoring,
            store.list_teams(competition.id),
            team_id,
        ).show()
        if selected_session_id is None:
            return
        label = next(
            (
                label
                for label, session in self.session_by_label.items()
                if session.id == selected_session_id
            ),
            "",
        )
        if label:
            self.session_var.set(label)
            self._session_changed()


class NewSessionDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, competition: Competition, next_week: int
    ) -> None:
        super().__init__(parent)
        self.choice: tuple[int, str, str] | None = None
        self.title("New weekly score sheet")
        self.geometry("520x310")
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
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.week_var = tk.StringVar(value=str(next_week))
        self.date_var = tk.StringVar(value=date.today().isoformat())
        self.label_var = tk.StringVar()
        for row, (label, variable) in enumerate(
            (("Week number", self.week_var), ("Date", self.date_var), ("Label", self.label_var)),
            start=1,
        ):
            ttk.Label(content, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            ttk.Entry(content, textvariable=variable).grid(
                row=row, column=1, sticky="ew", pady=6
            )
        ttk.Label(
            content, text="Date format: YYYY-MM-DD", style="Muted.TLabel"
        ).grid(row=4, column=1, sticky="w")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Create score sheet",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))

    def _accept(self) -> None:
        try:
            week = int(self.week_var.get())
        except ValueError:
            messagebox.showwarning(
                "Week number needed", "Enter a whole-number week.", parent=self
            )
            return
        self.choice = (week, self.date_var.get(), self.label_var.get())
        self.destroy()

    def show(self) -> tuple[int, str, str] | None:
        self.wait_window()
        return self.choice


class ScoreEntryDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, view: ScoreLineView) -> None:
        super().__init__(parent)
        self.view = view
        self.choice: tuple[
            int, list[tuple[GameStatus, int | None]], str
        ] | None = None
        self.title(f"Enter scores — {view.line.player_name}")
        height = 330 + len(view.games) * 42
        self.geometry(f"590x{height}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(2, weight=1)
        ttk.Label(
            content,
            text=view.line.player_name,
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            content,
            text=f"{view.line.team_name} • {view.line.roster_role.value}",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 14))
        ttk.Label(content, text="Entering average", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.average_var = tk.StringVar(value=str(view.line.entering_average))
        ttk.Entry(content, textvariable=self.average_var, width=10).grid(
            row=2, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Label(content, text="Result", style="Muted.TLabel").grid(
            row=3, column=1, sticky="w", padx=(10, 0), pady=(14, 3)
        )
        ttk.Label(content, text="Scratch score", style="Muted.TLabel").grid(
            row=3, column=2, sticky="w", padx=(10, 0), pady=(14, 3)
        )
        self.status_vars: list[tk.StringVar] = []
        self.score_vars: list[tk.StringVar] = []
        for row, game in enumerate(view.games, start=4):
            ttk.Label(
                content, text=f"Game {game.game_number}", style="Muted.TLabel"
            ).grid(row=row, column=0, sticky="w", pady=5)
            status_var = tk.StringVar(value=game.status.value)
            score_var = tk.StringVar(
                value=str(game.scratch_score)
                if game.status is GameStatus.BOWLED and game.scratch_score is not None
                else ""
            )
            status_box = ttk.Combobox(
                content,
                textvariable=status_var,
                values=[status.value for status in GameStatus],
                state="readonly",
                width=15,
            )
            status_box.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=5)
            ttk.Entry(content, textvariable=score_var).grid(
                row=row, column=2, sticky="ew", padx=(10, 0), pady=5
            )
            self.status_vars.append(status_var)
            self.score_vars.append(score_var)
        reason_row = 4 + len(view.games)
        ttk.Label(
            content,
            text="Correction reason (required when changing saved results)",
            style="Muted.TLabel",
        ).grid(row=reason_row, column=0, columnspan=3, sticky="w", pady=(14, 4))
        self.reason_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.reason_var).grid(
            row=reason_row + 1, column=0, columnspan=3, sticky="ew"
        )
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(
            row=reason_row + 2, column=0, columnspan=3, sticky="e", pady=(20, 0)
        )
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Save scores",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))

    def _accept(self) -> None:
        try:
            average = int(self.average_var.get())
            entries: list[tuple[GameStatus, int | None]] = []
            for status_var, score_var in zip(
                self.status_vars, self.score_vars, strict=True
            ):
                status = GameStatus(status_var.get())
                score_text = score_var.get().strip()
                score = int(score_text) if score_text else None
                entries.append((status, score))
        except ValueError:
            messagebox.showwarning(
                "Check score entry",
                "Averages and scratch scores must be whole numbers.",
                parent=self,
            )
            return
        self.choice = (average, entries, self.reason_var.get())
        self.destroy()

    def show(
        self,
    ) -> tuple[int, list[tuple[GameStatus, int | None]], str] | None:
        self.wait_window()
        return self.choice


class LeagueScoringSettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, competition: Competition) -> None:
        super().__init__(parent)
        self.choice: dict[str, object] | None = None
        self.title("League scoring settings")
        self.geometry("650x610")
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
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            content,
            text="The verified standard composite is adjusted by this league's rule.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 14))
        self.variables = {
            "games_per_session": tk.StringVar(value=str(competition.games_per_session)),
            "average_rule_name": tk.StringVar(value=competition.average_rule_name),
            "average_minimum_games": tk.StringVar(
                value=str(competition.average_minimum_games)
            ),
            "average_multiplier": tk.StringVar(
                value=str(competition.average_multiplier)
            ),
            "average_add_pins": tk.StringVar(value=str(competition.average_add_pins)),
            "average_rounding": tk.StringVar(value=competition.average_rounding.value),
            "handicap_base": tk.StringVar(value=str(competition.handicap_base)),
            "handicap_percent": tk.StringVar(
                value=str(competition.handicap_percent * 100)
            ),
            "blind_penalty": tk.StringVar(value=str(competition.blind_penalty)),
            "vacancy_score": tk.StringVar(value=str(competition.vacancy_score)),
        }
        fields = (
            ("Games per night", "games_per_session"),
            ("Average rule name", "average_rule_name"),
            ("Minimum games", "average_minimum_games"),
            ("Average multiplier", "average_multiplier"),
            ("Add/subtract pins", "average_add_pins"),
            ("Rounding", "average_rounding"),
            ("Handicap base", "handicap_base"),
            ("Handicap percent", "handicap_percent"),
            ("Blind penalty", "blind_penalty"),
            ("Vacancy score", "vacancy_score"),
        )
        for row, (label, key) in enumerate(fields, start=2):
            ttk.Label(content, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=5
            )
            if key == "average_rounding":
                widget = ttk.Combobox(
                    content,
                    textvariable=self.variables[key],
                    values=[rounding.value for rounding in AverageRounding],
                    state="readonly",
                )
            else:
                widget = ttk.Entry(content, textvariable=self.variables[key])
            widget.grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(
            content,
            text=(
                "Example: multiplier 0.9 uses 90% of the verified average. "
                "Handicap percent is entered as 90, not 0.9."
            ),
            style="Muted.TLabel",
            wraplength=590,
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(12, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=13, column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Save settings",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))

    def _accept(self) -> None:
        try:
            self.choice = {
                "games_per_session": int(self.variables["games_per_session"].get()),
                "average_rule_name": self.variables["average_rule_name"].get(),
                "average_minimum_games": int(
                    self.variables["average_minimum_games"].get()
                ),
                "average_multiplier": Decimal(
                    self.variables["average_multiplier"].get()
                ),
                "average_add_pins": int(self.variables["average_add_pins"].get()),
                "average_rounding": AverageRounding(
                    self.variables["average_rounding"].get()
                ),
                "handicap_base": int(self.variables["handicap_base"].get()),
                "handicap_percent": Decimal(
                    self.variables["handicap_percent"].get()
                )
                / Decimal("100"),
                "blind_penalty": int(self.variables["blind_penalty"].get()),
                "vacancy_score": int(self.variables["vacancy_score"].get()),
            }
        except (InvalidOperation, ValueError):
            messagebox.showwarning(
                "Check scoring settings",
                "Enter valid whole numbers and percentages.",
                parent=self,
            )
            return
        self.destroy()

    def show(self) -> dict[str, object] | None:
        self.wait_window()
        return self.choice


class ScorePlayerPickerDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, players: list[RegistrationView], teams: list[Team]
    ) -> None:
        super().__init__(parent)
        self.players = players
        self.teams = teams
        self.choice: tuple[str, str] | None = None
        self.title("Add player for this week")
        self.geometry("700x500")
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text="Add a registered player to this week",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.search_var = tk.StringVar()
        search = ttk.Entry(content, textvariable=self.search_var)
        search.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 10))
        search.bind("<KeyRelease>", lambda _event: self._render())
        self.table = ttk.Treeview(
            content,
            columns=("name", "member", "current"),
            show="headings",
        )
        for column, label, width in (
            ("name", "Player", 230),
            ("member", "Member ID", 140),
            ("current", "League role", 190),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=1, sticky="ns")
        picker = ttk.Frame(content, style="App.TFrame")
        picker.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        picker.columnconfigure(1, weight=1)
        ttk.Label(picker, text="Bowl for team", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.team_var = tk.StringVar(value=teams[0].name if teams else "")
        ttk.Combobox(
            picker,
            textvariable=self.team_var,
            values=[team.name for team in teams],
            state="readonly",
        ).grid(row=0, column=1, sticky="ew")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Add to score sheet",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        self._render()

    def _render(self) -> None:
        self.table.delete(*self.table.get_children())
        query = self.search_var.get().strip().casefold()
        first = ""
        for view in self.players:
            text = f"{view.bowler.name} {view.bowler.membership_id}".casefold()
            if query and query not in text:
                continue
            self.table.insert(
                "",
                tk.END,
                iid=view.registration.id,
                values=(
                    view.bowler.name,
                    view.bowler.membership_id or "—",
                    view.registration.roster_role.value,
                ),
            )
            first = first or view.registration.id
        if first:
            self.table.selection_set(first)
            self.table.focus(first)

    def _accept(self) -> None:
        selected = self.table.selection()
        team = next((item for item in self.teams if item.name == self.team_var.get()), None)
        if not selected or team is None:
            return
        self.choice = (selected[0], team.id)
        self.destroy()

    def show(self) -> tuple[str, str] | None:
        self.wait_window()
        return self.choice


class TeamPickerDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, teams: list[Team]) -> None:
        super().__init__(parent)
        self.teams = teams
        self.choice: str | None = None
        self.title("Choose team")
        self.geometry("430x190")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        ttk.Label(content, text="Add vacancy to", style="Muted.TLabel").pack(
            anchor="w"
        )
        self.team_var = tk.StringVar(value=teams[0].name if teams else "")
        ttk.Combobox(
            content,
            textvariable=self.team_var,
            values=[team.name for team in teams],
            state="readonly",
        ).pack(fill=tk.X, pady=(8, 18))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.pack(anchor="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Add vacancy",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))

    def _accept(self) -> None:
        team = next((item for item in self.teams if item.name == self.team_var.get()), None)
        if team is None:
            return
        self.choice = team.id
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.choice


class LeagueHistoryDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        competition: Competition,
        scoring: ScoringStore,
        teams: list[Team],
        selected_team_id: str = "",
    ) -> None:
        super().__init__(parent)
        self.competition = competition
        self.scoring = scoring
        self.teams = teams
        self.choice: str | None = None
        self.title(f"Score history — {competition.display_name}")
        self.geometry("980x540")
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text=f"{competition.display_name} score history",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        filters = ttk.Frame(content, style="App.TFrame")
        filters.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 10))
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="Team", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.team_by_label = {team.name: team for team in teams}
        initial_team = next(
            (team.name for team in teams if team.id == selected_team_id), "All teams"
        )
        self.team_var = tk.StringVar(value=initial_team)
        team_box = ttk.Combobox(
            filters,
            textvariable=self.team_var,
            values=["All teams", *self.team_by_label],
            state="readonly",
        )
        team_box.grid(row=0, column=1, sticky="ew")
        team_box.bind("<<ComboboxSelected>>", lambda _event: self._render())
        self.summary_label = ttk.Label(filters, text="", style="Muted.TLabel")
        self.summary_label.grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.table = ttk.Treeview(
            content,
            columns=(
                "week",
                "date",
                "label",
                "status",
                "players",
                "games",
                "scratch",
                "counted",
                "changes",
            ),
            show="headings",
        )
        for column, label, width in (
            ("week", "Week", 55),
            ("date", "Date", 100),
            ("label", "Label", 150),
            ("status", "Status", 70),
            ("players", "Rows", 55),
            ("games", "Games entered", 105),
            ("scratch", "Scratch", 75),
            ("counted", "With handicap", 105),
            ("changes", "Changes", 70),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.table.bind("<Double-1>", lambda _event: self._accept())
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Open score sheet",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        self._render()

    def _render(self) -> None:
        self.table.delete(*self.table.get_children())
        selected_team = self.team_by_label.get(self.team_var.get())
        team_id = selected_team.id if selected_team is not None else ""
        summaries = self.scoring.session_history(self.competition.id, team_id)
        for summary in summaries:
            session = summary.session
            self.table.insert(
                "",
                tk.END,
                iid=session.id,
                values=(
                    session.week_number,
                    session.bowled_on or "—",
                    session.label or "—",
                    session.status.value,
                    summary.player_rows,
                    f"{summary.games_entered} / {summary.total_games}",
                    summary.scratch_total,
                    summary.counted_total,
                    summary.correction_count,
                ),
            )
        if summaries:
            first = summaries[0].session.id
            self.table.selection_set(first)
            self.table.focus(first)
        team_label = selected_team.name if selected_team is not None else "all teams"
        self.summary_label.configure(
            text=f"{len(summaries)} week{'s' if len(summaries) != 1 else ''} • {team_label}"
        )

    def _accept(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        self.choice = selected[0]
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.choice


class ChangeLogDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, session: LeagueSession, changes: list) -> None:
        super().__init__(parent)
        self.title(f"Change log — {session.display_name}")
        self.geometry("980x520")
        self.transient(parent)
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)
        ttk.Label(
            content,
            text=f"{session.display_name} change log",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        table = ttk.Treeview(
            content,
            columns=("when", "player", "team", "game", "before", "after", "reason"),
            show="headings",
        )
        for column, label, width in (
            ("when", "Changed", 145),
            ("player", "Player", 145),
            ("team", "Team", 125),
            ("game", "Game", 55),
            ("before", "Before", 100),
            ("after", "After", 100),
            ("reason", "Reason", 260),
        ):
            table.heading(column, text=label)
            table.column(column, width=width, anchor="w")
        table.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")
        for change in changes:
            before = _change_value(
                change.old_status, change.old_scratch_score, change.old_pins_counted
            )
            after = _change_value(
                change.new_status, change.new_scratch_score, change.new_pins_counted
            )
            table.insert(
                "",
                tk.END,
                values=(
                    change.changed_at.replace("T", " ")[:19],
                    change.player_name or "Score sheet",
                    change.team_name or "—",
                    change.game_number or "—",
                    before,
                    after,
                    change.reason,
                ),
            )
        if not changes:
            table.insert("", tk.END, values=("No corrections recorded", "", "", "", "", "", ""))
        ttk.Button(content, text="Close", command=self.destroy).grid(
            row=2, column=0, columnspan=2, sticky="e", pady=(14, 0)
        )


def _change_value(status: str, scratch: int | None, counted: int) -> str:
    if status in (SessionStatus.DRAFT, SessionStatus.FINAL, "Removed"):
        return status
    if scratch is None:
        return status
    return f"{status} {scratch} ({counted})"
