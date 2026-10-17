"""Lecture des fichiers de configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = DATA / "etat.json"
HISTORY = DATA / "historique.csv"
TZ = ZoneInfo("America/Toronto")


def money(amount: float) -> str:
    return f"{amount:,.0f} $".replace(",", " ")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@dataclass(frozen=True)
class Trip:
    nom: str
    origine: str
    destinations: list[str]
    villes_differentes: bool
    depart: date
    retour_au_plus_tard: date
    nuits: int
    nuit_en_moins_economie_min: float
    passagers: int
    bagages_soute: int
    devise: str
    escales: dict
    recherche: dict
    alerte: dict

    def date_pairs(self) -> list[tuple[date, date]]:
        """Couples (date de départ, date du vol retour) : le nombre de nuits prévu, et une nuit
        de moins. Les vols vers l'Europe arrivent le lendemain du départ, d'où le +1."""
        returns = (self.depart + timedelta(days=self.nuits + 1 - fewer) for fewer in (0, 1))
        return [(self.depart, r) for r in returns if r <= self.retour_au_plus_tard]


def load_trip(path: Path | None = None) -> Trip:
    data = yaml.safe_load((path or ROOT / "config" / "voyage.yaml").read_text())
    return Trip(**data)


def load_airlines(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or ROOT / "config" / "compagnies.yaml").read_text())
    for code, policy in data.items():
        if "meme_que" in policy:
            data[code] = {**data[policy["meme_que"]], "nom": policy["nom"], "source": policy["source"]}
    return data
