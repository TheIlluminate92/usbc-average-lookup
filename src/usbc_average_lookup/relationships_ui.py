from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from enum import StrEnum
from tkinter import ttk

from usbc_average_lookup.services.registration import RegistrationStore


class EntityKind(StrEnum):
    LEAGUE = "League / tournament"
    TEAM = "Team"
    PLAYER = "Player"


@dataclass(frozen=True, slots=True)
class EntityRef:
    kind: EntityKind
    id: str


class RelationshipBrowser(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, store: RegistrationStore, start: EntityRef
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.history = [start]
        self.history_index = 0
        self.row_targets: dict[str, EntityRef] = {}
        self.title("Relationships")
        self.geometry("880x590")
        self.minsize(700, 460)
        self.transient(parent)
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)
        navigation = ttk.Frame(content, style="App.TFrame")
        navigation.grid(row=0, column=0, sticky="ew")
        self.back_button = ttk.Button(
            navigation, text="← Back", command=self._back, state=tk.DISABLED
        )
        self.back_button.pack(side=tk.LEFT)
        self.forward_button = ttk.Button(
            navigation, text="Forward →", command=self._forward, state=tk.DISABLED
        )
        self.forward_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(navigation, text="Close", command=self.destroy).pack(side=tk.RIGHT)
        self.title_label = ttk.Label(
            content,
            text="",
            style="Muted.TLabel",
            font=("Segoe UI", 19, "bold"),
        )
        self.title_label.grid(row=1, column=0, sticky="w", pady=(18, 0))
        self.detail_label = ttk.Label(content, text="", style="Muted.TLabel")
        self.detail_label.grid(row=2, column=0, sticky="w", pady=(3, 12))
        frame = ttk.Frame(content, style="Surface.TFrame")
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            frame,
            columns=("type", "name", "relationship", "status"),
            show="headings",
        )
        for column, label, width in (
            ("type", "Type", 135),
            ("name", "Name", 250),
            ("relationship", "Relationship", 245),
            ("status", "Status", 135),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.table.bind("<Double-1>", lambda _event: self._open_selected())
        footer = ttk.Frame(content, style="App.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            footer,
            text="Double-click a league, team, or player to move through the relationships.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(
            footer,
            text="Open selected",
            command=self._open_selected,
            style="Primary.TButton",
        ).pack(side=tk.RIGHT)
        self._render()

    def _current(self) -> EntityRef:
        return self.history[self.history_index]

    def _render(self) -> None:
        self.table.delete(*self.table.get_children())
        self.row_targets = {}
        current = self._current()
        if current.kind is EntityKind.LEAGUE:
            self._render_league(current.id)
        elif current.kind is EntityKind.TEAM:
            self._render_team(current.id)
        else:
            self._render_player(current.id)
        self.back_button.configure(
            state=tk.NORMAL if self.history_index > 0 else tk.DISABLED
        )
        self.forward_button.configure(
            state=(
                tk.NORMAL
                if self.history_index < len(self.history) - 1
                else tk.DISABLED
            )
        )

    def _render_league(self, competition_id: str) -> None:
        competition = next(
            item for item in self.store.competitions if item.id == competition_id
        )
        teams = self.store.list_teams(competition.id)
        views = self.store.registration_views(competition.id)
        self.title_label.configure(text=competition.display_name)
        self.detail_label.configure(
            text=(
                f"{competition.kind.value} • {len(teams)} teams • "
                f"{len(views)} registered players"
            )
        )
        for team in teams:
            count = sum(view.registration.team_id == team.id for view in views)
            self._insert(
                EntityRef(EntityKind.TEAM, team.id),
                team.name,
                f"Team in {competition.display_name}",
                f"{count} players",
            )
        for view in views:
            assignment = view.team.name if view.team is not None else "Unassigned"
            self._insert(
                EntityRef(EntityKind.PLAYER, view.bowler.id),
                view.bowler.name,
                assignment,
                "Withdrawn" if view.registration.withdrawn else view.status,
            )

    def _render_team(self, team_id: str) -> None:
        team = next(item for item in self.store.teams if item.id == team_id)
        competition = next(
            item
            for item in self.store.competitions
            if item.id == team.competition_id
        )
        views = [
            view
            for view in self.store.registration_views(competition.id)
            if view.registration.team_id == team.id
        ]
        self.title_label.configure(text=team.name)
        self.detail_label.configure(
            text=f"Team in {competition.display_name} • {len(views)} players"
        )
        self._insert(
            EntityRef(EntityKind.LEAGUE, competition.id),
            competition.display_name,
            "League / tournament",
            "Archived" if competition.archived else "Active",
        )
        for view in views:
            self._insert(
                EntityRef(EntityKind.PLAYER, view.bowler.id),
                view.bowler.name,
                view.registration.roster_role.value,
                "Withdrawn" if view.registration.withdrawn else view.status,
            )

    def _render_player(self, bowler_id: str) -> None:
        bowler = next(item for item in self.store.bowlers if item.id == bowler_id)
        competition_by_id = {item.id: item for item in self.store.competitions}
        team_by_id = {item.id: item for item in self.store.teams}
        registrations = [
            item for item in self.store.registrations if item.bowler_id == bowler.id
        ]
        self.title_label.configure(text=bowler.name)
        self.detail_label.configure(
            text=(
                f"Member ID {bowler.membership_id or 'not set'} • "
                f"{len(registrations)} league/tournament registrations"
            )
        )
        for registration in sorted(
            registrations,
            key=lambda item: competition_by_id[item.competition_id].display_name,
            reverse=True,
        ):
            competition = competition_by_id[registration.competition_id]
            team = team_by_id.get(registration.team_id)
            self._insert(
                EntityRef(EntityKind.LEAGUE, competition.id),
                competition.display_name,
                team.name if team is not None else "Unassigned",
                "Withdrawn" if registration.withdrawn else registration.roster_role.value,
            )
            if team is not None:
                self._insert(
                    EntityRef(EntityKind.TEAM, team.id),
                    team.name,
                    competition.display_name,
                    registration.roster_role.value,
                )

    def _insert(
        self, target: EntityRef, name: str, relationship: str, status: str
    ) -> None:
        iid = f"row-{len(self.row_targets)}"
        self.row_targets[iid] = target
        self.table.insert(
            "",
            tk.END,
            iid=iid,
            values=(target.kind.value, name, relationship, status),
        )

    def _open_selected(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        target = self.row_targets.get(selected[0])
        if target is None:
            return
        self.history = self.history[: self.history_index + 1]
        self.history.append(target)
        self.history_index += 1
        self._render()

    def _back(self) -> None:
        if self.history_index > 0:
            self.history_index -= 1
            self._render()

    def _forward(self) -> None:
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._render()
