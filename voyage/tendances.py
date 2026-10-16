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

HISTORY = Path(__file__).resolve().parent.parent / "data" / "historique.csv"
TRENDS = HISTORY.with_name("tendances.md")
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MIN_HOURS_PER_DAY = 6    # une journée compte pour l'effet « heure » à partir de 6 relevés
MIN_DAYS_PER_WEEK = 5    # une semaine compte pour l'effet « jour » à partir de 5 jours relevés
MIN_WEEKS = 2            # conclusions sur les jours : au moins 2 semaines complètes
MIN_DAYS = 5             # conclusions sur les heures : au moins 5 journées
MIN_GAP = 0.01           # écart sous 1 % : pas de différence réelle


def load(path: Path = HISTORY) -> list[tuple[datetime, float]]:
    try:
        with path.open(newline="") as f:
            return [(datetime.fromisoformat(r["horodatage"]), float(r["meilleur_total"]))
                    for r in csv.DictReader(f) if r["meilleur_total"]]
    except FileNotFoundError:
        return []


def by_hour(rows) -> tuple[dict[int, float], int]:
    """Écart moyen de chaque heure à la moyenne de sa journée (-0.02 = 2 % moins cher),
    et nombre de journées retenues."""
    days = defaultdict(list)
    for when, price in rows:
        days[when.date()].append((when.hour, price))
    ratios, used = defaultdict(list), 0
    for obs in days.values():
        if len(obs) < MIN_HOURS_PER_DAY:
            continue
        used += 1
        avg = mean(p for _, p in obs)
        for hour, price in obs:
            ratios[hour].append(price / avg - 1)
    return {h: mean(r) for h, r in ratios.items()}, used


def by_weekday(rows) -> tuple[dict[int, float], int]:
    """Écart moyen du prix le plus bas de chaque jour de la semaine à la moyenne de sa semaine,
    et nombre de semaines retenues."""
    low = defaultdict(lambda: float("inf"))
    for when, price in rows:
        low[when.date()] = min(low[when.date()], price)
    weeks = defaultdict(list)
    for d, price in low.items():
        weeks[d.isocalendar()[:2]].append((d.weekday(), price))
    ratios, used = defaultdict(list), 0
    for obs in weeks.values():
        if len(obs) < MIN_DAYS_PER_WEEK:
            continue
        used += 1
        avg = mean(p for _, p in obs)
        for weekday, price in obs:
            ratios[weekday].append(price / avg - 1)
    return {w: mean(r) for w, r in ratios.items()}, used


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


def hour_label(h: int) -> str:
    return f"vers {h} h"


def advice(rows=None) -> str:
    """Une ligne : quand acheter, ou pourquoi on ne peut pas encore le dire."""
    rows = load() if rows is None else rows
    hours, n_days = by_hour(rows)
    weekdays, n_weeks = by_weekday(rows)
    parts = []
    if n_days >= MIN_DAYS:
        parts.append("heure : " + (verdict(hours, hour_label) or "aucune différence nette"))
    if n_weeks >= MIN_WEEKS:
        parts.append("jour : " + (verdict(weekdays, DAYS.__getitem__) or "aucune différence nette"))
    if parts:
        return "Moment le moins cher pour acheter — " + " ; ".join(parts) + "."
    return (f"Tendances pas encore calculables ({n_days} journée(s) et {n_weeks} semaine(s) de "
            f"données ; il en faut {MIN_DAYS} et {MIN_WEEKS}).")


def table(effects: dict[int, float], label) -> list[str]:
    return [f"| {label(k)} | {pct(v)} |" for k, v in sorted(effects.items())]


def report(rows=None) -> str:
    """Contenu de data/tendances.md."""
    rows = load() if rows is None else rows
    hours, n_days = by_hour(rows)
    weekdays, n_weeks = by_weekday(rows)
    lines = ["## Tendances de prix", "", advice(rows), "",
             f"_{len(rows)} relevés. Écart = prix par rapport à la moyenne de la journée (heures) "
             "ou de la semaine (jours) ; négatif = moins cher. Indicatif : plus il y a de "
             "données, plus c'est fiable._"]
    if hours:
        lines += ["", f"### Par heure ({n_days} journées retenues)", "", "| Heure | Écart |",
                  "|---|---|", *table(hours, lambda h: f"{h} h")]
    if weekdays:
        lines += ["", f"### Par jour de la semaine ({n_weeks} semaines retenues)", "",
                  "| Jour | Écart |", "|---|---|", *table(weekdays, DAYS.__getitem__)]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(report())
