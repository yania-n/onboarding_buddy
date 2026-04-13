"""
core/state_store.py — Joiner State Persistence
===============================================
Manages reading and writing JoinerProfile and JoinerState records to disk.
In production, swap the JSON backend for a proper database (Postgres, DynamoDB, etc.)
by replacing only the _load / _save private methods — the public API stays the same.

Thread safety: uses a threading.Lock so concurrent agent writes do not corrupt state.
"""

import json
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from core.models import JoinerProfile, JoinerState, ChecklistItem, PhaseStatus
from core.config import PHASE_BY_ID, PHASES


# ─────────────────────────────────────────────
# Storage paths
# ─────────────────────────────────────────────

DATA_DIR = Path("data")
PROFILES_PATH = DATA_DIR / "profiles.json"
STATES_PATH = DATA_DIR / "states.json"
GAPS_PATH = DATA_DIR / "knowledge_gaps.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for p in [PROFILES_PATH, STATES_PATH, GAPS_PATH]:
        if not p.exists():
            p.write_text("{}")


# ─────────────────────────────────────────────
# JSON helpers (handle date / datetime types)
# ─────────────────────────────────────────────

def _json_default(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Not serialisable: {type(obj)}")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, default=_json_default, indent=2))


# ─────────────────────────────────────────────
# StateStore class
# ─────────────────────────────────────────────

class StateStore:
    """
    Central persistence layer.
    One instance should be created at app start and shared across all agents.
    """

    def __init__(self):
        _ensure_data_dir()
        self._lock = threading.Lock()

    # ── Profile CRUD ──────────────────────────

    def create_profile(self, profile: JoinerProfile) -> str:
        """Persist a new joiner profile. Returns the joiner_id."""
        with self._lock:
            data = _load_json(PROFILES_PATH)
            data[profile.joiner_id] = json.loads(profile.model_dump_json())
            _save_json(PROFILES_PATH, data)
        return profile.joiner_id

    def get_profile(self, joiner_id: str) -> Optional[JoinerProfile]:
        data = _load_json(PROFILES_PATH)
        raw = data.get(joiner_id)
        if raw is None:
            return None
        return JoinerProfile.model_validate(raw)

    def list_profiles(self) -> list[JoinerProfile]:
        data = _load_json(PROFILES_PATH)
        return [JoinerProfile.model_validate(v) for v in data.values()]

    # ── State CRUD ────────────────────────────

    def create_state(self, joiner_id: str, profile: JoinerProfile) -> JoinerState:
        """
        Initialise a fresh JoinerState for a new joiner.
        Populates checklist items from phase definitions and sets Phase 1 active.
        """
        checklist_items: list[ChecklistItem] = []
        for phase in PHASES:
            for i, label in enumerate(phase.checklist):
                checklist_items.append(ChecklistItem(
                    item_id=f"phase{phase.phase_id}_item{i}",
                    phase_id=phase.phase_id,
                    label=label,
                ))

        state = JoinerState(
            joiner_id=joiner_id,
            checklist_items=checklist_items,
        )
        # Mark phase 1 start date as today
        state.phase_start_dates[1] = date.today()

        self._save_state(state)
        return state

    def get_state(self, joiner_id: str) -> Optional[JoinerState]:
        data = _load_json(STATES_PATH)
        raw = data.get(joiner_id)
        if raw is None:
            return None
        return JoinerState.model_validate(raw)

    def save_state(self, state: JoinerState) -> None:
        """Public save — acquires lock."""
        self._save_state(state)

    def _save_state(self, state: JoinerState) -> None:
        state.last_updated = datetime.utcnow()
        with self._lock:
            data = _load_json(STATES_PATH)
            data[state.joiner_id] = json.loads(state.model_dump_json())
            _save_json(STATES_PATH, data)

    def append_to_state(
        self,
        joiner_id: str,
        notifications: list[str] | None = None,
        access_requests: list | None = None,
        checklist_updates: dict | None = None,
    ) -> None:
        """
        Thread-safe append-only update for agent writes.
        Reads the latest state inside the lock, appends items, then saves.
        Avoids the read-modify-write race when multiple agents run concurrently.
        """
        with self._lock:
            data = _load_json(STATES_PATH)
            raw = data.get(joiner_id)
            if raw is None:
                return
            state = JoinerState.model_validate(raw)

            if notifications:
                state.app_notifications.extend(notifications)
            if access_requests:
                state.access_requests.extend(access_requests)
            if checklist_updates:
                for item in state.checklist_items:
                    if item.item_id in checklist_updates:
                        item.completed = checklist_updates[item.item_id]

            state.last_updated = datetime.utcnow()
            data[joiner_id] = json.loads(state.model_dump_json())
            _save_json(STATES_PATH, data)

    def list_states(self) -> list[JoinerState]:
        data = _load_json(STATES_PATH)
        return [JoinerState.model_validate(v) for v in data.values()]

    # ── Knowledge Gap log ─────────────────────

    def log_knowledge_gap(self, joiner_id: str, question: str) -> str:
        """Record an unanswered KB query. Returns the gap_id."""
        gap_id = str(uuid.uuid4())
        with self._lock:
            data = _load_json(GAPS_PATH)
            data[gap_id] = {
                "gap_id": gap_id,
                "joiner_id": joiner_id,
                "question": question,
                "asked_at": datetime.utcnow().isoformat(),
                "resolved": False,
                "resolution_note": "",
            }
            _save_json(GAPS_PATH, data)
        return gap_id

    def list_knowledge_gaps(self, resolved: Optional[bool] = None) -> list[dict]:
        data = _load_json(GAPS_PATH)
        gaps = list(data.values())
        if resolved is not None:
            gaps = [g for g in gaps if g["resolved"] == resolved]
        return gaps

    def resolve_gap(self, gap_id: str, note: str) -> None:
        with self._lock:
            data = _load_json(GAPS_PATH)
            if gap_id in data:
                data[gap_id]["resolved"] = True
                data[gap_id]["resolution_note"] = note
                _save_json(GAPS_PATH, data)

    # ── Helper: generate unique joiner_id ─────

    @staticmethod
    def new_joiner_id() -> str:
        return str(uuid.uuid4())
