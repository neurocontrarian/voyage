"""Tendances de prix selon l'heure et le jour de la semaine, d'après data/historique.csv.

Les prix dérivent avec le temps (hausse, baisse). Pour ne pas confondre cette dérive avec un
effet « heure » ou « jour », chaque prix est comparé à la moyenne de sa propre journée
(effet heure) et le prix le plus bas de chaque jour à la moyenne de sa semaine (effet jour).

    python -m voyage.tendances
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

from voyage.config import DATA, HISTORY

TRENDS = DATA / "tendances.md"
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MIN_HOURS_PER_DAY = 6    # une journée compte pour l'effet « heure » à partir de 6 relevés
MIN_DAYS_PER_WEEK = 5    # une semaine compte pour l'effet « jour » à partir de 5 jours relevés
MIN_DAYS = 5             # conclusions sur les heures : au moins 5 journées retenues
MIN_WEEKS = 2            # conclusions sur les jours : au moins 2 semaines retenues
MIN_GAP = 0.01           # écart sous 1 % : pas de différence réelle


def load(path: Path = HISTORY) -> list[tuple[datetime, float]]:
    try:
        with path.open(newline="") as f:
            return [(datetime.fromisoformat(r["horodatage"]), float(r["meilleur_total"]))
                    for r in csv.DictReader(f) if r["meilleur_total"]]
    except FileNotFoundError:
        return []


def relative_effects(groups: dict, min_size: int) -> tuple[dict[int, float], int]:
    """Chaque groupe est une liste de (clé, prix). Écart moyen de chaque clé à la moyenne de
    son groupe (-0.02 = 2 % moins cher), et nombre de groupes retenus (assez grands)."""
    ratios, used = defaultdict(list), 0
    for obs in groups.values():
        if len(obs) < min_size:
            continue
        used += 1
        avg = mean(p for _, p in obs)
        for key, price in obs:
            ratios[key].append(price / avg - 1)
    return {k: mean(r) for k, r in ratios.items()}, used


def by_hour(rows) -> tuple[dict[int, float], int]:
    """Effet de l'heure : chaque prix comparé à la moyenne de sa journée."""
    days = defaultdict(list)
    for when, price in rows:
        days[when.date()].append((when.hour, price))
    return relative_effects(days, MIN_HOURS_PER_DAY)


def by_weekday(rows) -> tuple[dict[int, float], int]:
    """Effet du jour : prix le plus bas de chaque jour comparé à la moyenne de sa semaine."""
    low = {}
    for when, price in rows:
        low[when.date()] = min(price, low.get(when.date(), price))
    weeks = defaultdict(list)
    for d, price in low.items():
        weeks[d.isocalendar()[:2]].append((d.weekday(), price))
    return relative_effects(weeks, MIN_DAYS_PER_WEEK)


def pct(x: float) -> str:
    return f"{x * 100:+.1f} %".replace(".", ",")


def verdict(effects: dict[int, float], label) -> str | None:
    """« Le moins cher : X (−2,1 % …) » ou None si aucune différence nette."""
    if len(effects) < 2:
        return None
    best, worst = min(effects, key=effects.get), max(effects, key=effects.get)
    if effects[worst] - effects[best] < MIN_GAP:
        return None
    return f"{label(best)} ({pct(effects[best])} par rapport à la moyenne)"


def analyse(rows=None) -> tuple[str, str]:
    """(conseil en une ligne, contenu de data/tendances.md), calculés en une seule passe."""
    rows = load() if rows is None else rows
    hours, n_days = by_hour(rows)
    weekdays, n_weeks = by_weekday(rows)
    parts = []
    if n_days >= MIN_DAYS:
        parts.append("heure : " + (verdict(hours, lambda h: f"vers {h} h") or "aucune différence nette"))
    if n_weeks >= MIN_WEEKS:
        parts.append("jour : " + (verdict(weekdays, DAYS.__getitem__) or "aucune différence nette"))
    if parts:
        advice = "Moment le moins cher pour acheter — " + " ; ".join(parts) + "."
    else:
        advice = (f"Tendances pas encore calculables ({n_days} journée(s) et {n_weeks} semaine(s) "
                  f"de données ; il en faut {MIN_DAYS} et {MIN_WEEKS}).")
    lines = ["## Tendances de prix", "", advice, "",
             f"_{len(rows)} relevés. Écart = prix par rapport à la moyenne de la journée (heures) "
             "ou de la semaine (jours) ; négatif = moins cher. Indicatif : plus il y a de "
             "données, plus c'est fiable._"]
    for title, effects, used, unit, label in (
            (f"Par heure ({n_days} journées retenues)", hours, n_days, "Heure", lambda h: f"{h} h"),
            (f"Par jour de la semaine ({n_weeks} semaines retenues)", weekdays, n_weeks, "Jour",
             DAYS.__getitem__)):
        if effects:
            lines += ["", f"### {title}", "", f"| {unit} | Écart |", "|---|---|",
                      *(f"| {label(k)} | {pct(v)} |" for k, v in sorted(effects.items()))]
    return advice, "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(analyse()[1])
