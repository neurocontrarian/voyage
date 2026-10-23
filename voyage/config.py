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
class Scenario:
    """Une variante du voyage : dates permises et nombre d'escales par trajet."""
    numero: int
    nom: str
    depart_du: date
    retour_au: date  # arrivée à Montréal au plus tard
    escales_max: int
    depart_au: date | None = None  # par défaut : aucune limite autre que le retour
    retour_du: date | None = None  # arrivée à Montréal au plus tôt
    nuits_min: int = 0

    @property
    def titre(self) -> str:
        return f"Scénario {self.numero} : {self.nom}"

    @property
    def dernier_depart(self) -> date:
        return self.depart_au or self.retour_au

    @property
    def premier_retour(self) -> date:
        return self.retour_du or self.depart_du

    def date_pairs(self) -> list[tuple[date, date]]:
        """Couples (date de départ, date du vol retour). Les vols vers l'Europe arrivent le
        lendemain du départ, d'où le +1 pour compter les nuits sur place ; les retours arrivent
        à Montréal le jour même."""
        pairs, dep = [], self.depart_du
        while dep <= self.dernier_depart:
            ret = max(self.premier_retour, dep + timedelta(days=self.nuits_min + 1))
            while ret <= self.retour_au:
                pairs.append((dep, ret))
                ret += timedelta(days=1)
            dep += timedelta(days=1)
        return pairs


@dataclass(frozen=True)
class Trip:
    nom: str
    origine: str
    destinations: list[str]
    villes_differentes: bool
    scenarios: list[Scenario]
    passagers: int
    bagages_soute: int
    devise: str
    escales: dict
    recherche: dict
    alerte: dict

    @property
    def escales_max(self) -> int:
        return max(s.escales_max for s in self.scenarios)


def load_trip(path: Path | None = None) -> Trip:
    data = yaml.safe_load((path or ROOT / "config" / "voyage.yaml").read_text())
    data["scenarios"] = [Scenario(numero=n, **s) for n, s in enumerate(data["scenarios"], 1)]
    return Trip(**data)


def load_airlines(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or ROOT / "config" / "compagnies.yaml").read_text())
    for code, policy in data.items():
        if "meme_que" in policy:
            data[code] = {**data[policy["meme_que"]], "nom": policy["nom"], "source": policy["source"]}
    return data
