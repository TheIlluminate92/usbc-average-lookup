from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import asdict
from tkinter import messagebox, ttk

from usbc_average_lookup.services.registration import RegistrationDataError, RegistrationStore
from usbc_average_lookup.services.standings import StandingRules, StandingsStore
from usbc_average_lookup.workspace import LeagueWorkspaceContext


class StandingsDesk(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        store: RegistrationStore | None,
        workspace_context: LeagueWorkspaceContext,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.store = StandingsStore(store) if store else None
        self.context = workspace_context
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = ttk.Frame(self, style="Surface.TFrame", padding=10)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.summary = ttk.Label(bar, style="Surface.TLabel", wraplength=850)
        self.summary.grid(row=0, column=0, sticky="w")
        self.rules_button = ttk.Button(bar, text="Standings rules…", command=self.edit_rules)
        self.rules_button.grid(row=0, column=1, padx=(10, 0))
        frame = ttk.Frame(self)
        frame.grid(row=1, column=0, sticky="nsew", pady=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = (
            "rank",
            "team",
            "played",
            "wins",
            "losses",
            "ties",
            "game_wins",
            "points",
            "scratch",
            "handicap",
        )
        self.table = ttk.Treeview(frame, columns=columns, show="headings")
        for key, title in zip(
            columns,
            (
                "Rank",
                "Team",
                "Matches",
                "Series W",
                "Series L",
                "Series T",
                "Game W",
                "Points",
                "Scratch pins",
                "With handicap",
            ),
            strict=True,
        ):
            self.table.heading(key, text=title)
            self.table.column(key, width=180 if key == "team" else 95, minwidth=60)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.table.yview)
        horizontal = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.table.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        ttk.Label(
            self,
            style="Muted.TLabel",
            wraplength=1000,
            text="Only linked, finalized matches count. BYEs and forfeits award no points. "
            "Series wins compare total pins, not points. Tied ranks share the same place. "
            "These are test standings, not payout instructions.",
        ).grid(row=2, column=0, sticky="w")
        self._unsubscribe = workspace_context.subscribe(lambda _id: self.refresh())
        self.bind("<Destroy>", self._destroyed, add="+")

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self._unsubscribe()

    def refresh(self) -> None:
        self.table.delete(*self.table.get_children())
        competition_id = self.context.competition_id
        self.rules_button.configure(
            state=tk.NORMAL if self.store and competition_id else tk.DISABLED
        )
        if not self.store or not competition_id:
            self.summary.configure(text="Choose a league or tournament above.")
            return
        rules = self.store.rules(competition_id)
        rounds = self.store.schedules.list_rounds(competition_id)
        linked = sum(self.store.linked_session(r.id) is not None for r in rounds)
        self.summary.configure(
            text=(
                f"Rank by {rules.ranking.lower()} • tie breaker: {rules.tiebreaker.lower()} • "
                f"{linked}/{len(rounds)} rounds linked\n"
                f"New links: {rules.comparison} • {rules.game_points} per game / "
                f"{rules.series_points} per series • {rules.ties}"
            )
        )
        for entry in self.store.standings(competition_id):
            self.table.insert(
                "",
                tk.END,
                iid=entry.team_id,
                values=(
                    entry.rank,
                    entry.team_name,
                    entry.played,
                    entry.wins,
                    entry.losses,
                    entry.ties,
                    entry.game_wins,
                    str(entry.points),
                    entry.scratch_pins,
                    entry.handicap_pins,
                ),
            )

    def edit_rules(self) -> None:
        if not self.store or not self.context.competition_id:
            return
        competition_id = self.context.competition_id
        RulesDialog(
            self,
            self.store.rules(competition_id),
            lambda rules: self.store.save_rules(competition_id, rules),
        )


class RulesDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, rules: StandingRules, save: Callable[[StandingRules], None]
    ) -> None:
        super().__init__(parent)
        self.title("Standings rules")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.save_callback = save
        self.variables = {key: tk.StringVar(value=value) for key, value in asdict(rules).items()}
        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        choices = {
            "comparison": ("Scratch", "Handicap"),
            "ties": ("Split points", "No points"),
            "ranking": ("Series wins", "Points", "Game wins"),
            "tiebreaker": ("None", "Scratch pins", "Handicap pins"),
        }
        labels = (
            "Compare scores",
            "Points per game",
            "Points per series",
            "Tied games/series",
            "Rank teams by",
            "Then break ties by",
        )
        for row, ((key, variable), label) in enumerate(
            zip(self.variables.items(), labels, strict=True)
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
            if key in choices:
                control = ttk.Combobox(
                    body, textvariable=variable, values=choices[key], state="readonly"
                )
            else:
                control = ttk.Entry(body, textvariable=variable)
            control.grid(row=row, column=1, padx=(12, 0), pady=4)
        ttk.Label(
            body,
            wraplength=450,
            text=(
                "Points and score comparison are copied when linking a round; changing them here "
                "only affects new links. Ranking and tie breakers apply to the whole table. "
                "All score rows count; legal-lineup and forfeit rules are not enforced yet."
            ),
        ).grid(row=6, column=0, columnspan=2, pady=12)
        self.error = ttk.Label(body, wraplength=450)
        self.error.grid(row=7, column=0, columnspan=2)
        ttk.Button(body, text="Cancel", command=self.destroy).grid(row=8, column=0)
        ttk.Button(body, text="Save rules", command=self._save).grid(row=8, column=1)
        self.bind("<Escape>", lambda _event: self.destroy())

    def _save(self) -> None:
        try:
            rules = StandingRules(**{k: v.get().strip() for k, v in self.variables.items()})
            rules.validate()
            self.save_callback(rules)
        except RegistrationDataError as error:
            self.error.configure(text=str(error))
            messagebox.showwarning("Check rules", str(error), parent=self)
            return
        self.destroy()
