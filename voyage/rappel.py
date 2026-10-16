"""Rappel quotidien (17 h) : meilleure offre de tous les temps et meilleure offre du jour,
même quand aucun nouveau record n'est tombé. Ne lance aucune recherche : lit data/etat.json
et data/historique.csv.

    python -m voyage.rappel
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from voyage import tendances
from voyage.config import TZ, load_state, load_trip, money
from voyage.notify import post_alerte

FOOTER = "_Vérifier le prix sur le site de la compagnie avant d'acheter._"


def section(title: str, entry: dict | None) -> str:
    if not entry:
        return f"#### {title}\n\nAucune recherche réussie aujourd'hui."
    return f"#### {title}\n\n" + (entry.get("fiche") or f"### {money(entry['total'])} tout compris")


def message(state: dict, now: datetime, advice: str) -> str:
    record, today = state["record"], state.get("jour")
    if today and not today["date"].startswith(f"{now:%Y-%m-%d}"):
        today = None  # dernière recherche réussie : un autre jour
    if today and (today.get("cle"), today.get("total")) == (record["cle"], record["total"]):
        body = section("Meilleure offre — de tous les temps ET d'aujourd'hui "
                       f"(trouvée le {record['date']})", record)
    else:
        body = (section(f"Meilleure offre de tous les temps (trouvée le {record['date']})", record)
                + "\n\n" + section("Meilleure offre d'aujourd'hui", today))
    return f"**Rappel de 17 h**\n\n{body}\n\n{advice}\n\n{FOOTER}"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    state = load_state()
    if not state.get("record"):
        logging.info("Pas encore de résultat : pas de rappel")
        return 0
    advice, text = tendances.analyse()
    tendances.TRENDS.write_text(text)
    post_alerte(load_trip(), message(state, datetime.now(TZ), advice))
    return 0


if __name__ == "__main__":
    sys.exit(main())
