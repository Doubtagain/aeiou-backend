"""Situation catalog: load the YAML definitions under content/situations/ and
keep the DB `situations` table in sync (so Session.situation_id FK is valid)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy.orm import Session as OrmSession

from .config import SITUATIONS_DIR
from .models import Situation


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(SITUATIONS_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["_yaml_path"] = str(path)
        out[data["id"]] = data
    return out


def load_all_situations() -> list[dict]:
    return list(_load_all().values())


def load_situation(situation_id: str) -> dict:
    sit = _load_all().get(situation_id)
    if sit is None:
        raise KeyError(f"unknown situation: {situation_id}")
    return sit


def goal_for(situation_id: str, goal_id: str) -> dict:
    for g in load_situation(situation_id).get("goal_options", []):
        if g["id"] == goal_id:
            return g
    raise KeyError(f"unknown goal '{goal_id}' for situation '{situation_id}'")


def sync_situations_to_db(db: OrmSession) -> None:
    """Upsert one row per YAML so FKs resolve."""
    for sit in load_all_situations():
        existing = db.get(Situation, sit["id"])
        if existing is None:
            db.add(
                Situation(
                    id=sit["id"],
                    title=sit.get("title", sit["id"]),
                    yaml_path=sit.get("_yaml_path", ""),
                    active=True,
                )
            )
        else:
            existing.title = sit.get("title", existing.title)
            existing.yaml_path = sit.get("_yaml_path", existing.yaml_path)
    db.commit()
