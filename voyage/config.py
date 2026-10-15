"""Lecture des fichiers de configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Trip:
    nom: str
    origine: str
    destinations: list[str]
    villes_differentes: bool
    depart_au_plus_tot: date
    retour_au_plus_tard: date
    nuits_min: int
    passagers: int
    bagages_soute: int
    devise: str
    escales: dict
    recherche: dict
    alerte: dict

    def date_pairs(self) -> list[tuple[date, date]]:
        """Couples (date de départ, date du vol retour). Les vols vers l'Europe arrivent le
        lendemain du départ, d'où le +1 pour compter les nuits sur place."""
        pairs = []
        dep = self.depart_au_plus_tot
        while dep + timedelta(days=self.nuits_min + 1) <= self.retour_au_plus_tard:
            ret = dep + timedelta(days=self.nuits_min + 1)
            while ret <= self.retour_au_plus_tard:
                pairs.append((dep, ret))
                ret += timedelta(days=1)
            dep += timedelta(days=1)
        return pairs


def load_trip(path: Path | None = None) -> Trip:
    data = yaml.safe_load((path or ROOT / "config" / "voyage.yaml").read_text())
    return Trip(**data)


def load_airlines(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or ROOT / "config" / "compagnies.yaml").read_text())
    for code, policy in data.items():
        if "meme_que" in policy:
            data[code] = {**data[policy["meme_que"]], "nom": policy["nom"], "source": policy["source"]}
    return data
