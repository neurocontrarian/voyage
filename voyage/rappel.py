"""Rappel quotidien (17 h) : pour chaque scénario, meilleure offre de tous les temps et
meilleure offre du jour, même quand aucun nouveau record n'est tombé. Ne lance aucune
recherche : lit data/etat.json et data/historique.csv.

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


def scenario_block(number: str, mine: dict, now: datetime, shown: dict) -> str:
    """Record du scénario (fiche, sauf si un scénario précédent a le même), puis la meilleure
    offre du jour en une ligne. ``shown`` : (clé, total) -> numéro du scénario déjà affiché."""
    record, today = mine["record"], mine.get("jour")
    if today and not today["date"].startswith(f"{now:%Y-%m-%d}"):
        today = None  # dernière recherche réussie : un autre jour
    head = f"#### Scénario {number} : {mine['nom']}\n\n"
    same = (record["cle"], record["total"])
    if same in shown:
        body = f"Meilleure offre de tous les temps : {money(record['total'])}, la même qu'au scénario {shown[same]}."
    else:
        shown[same] = number
        body = (f"Meilleure offre de tous les temps (trouvée le {record['date']}) :\n\n"
                + (record.get("fiche") or f"### {money(record['total'])} tout compris"))
    if today is None:
        body += "\n\nAujourd'hui : aucune recherche réussie."
    elif (today["cle"], today["total"]) == same:
        body += "\n\nAujourd'hui : c'est aussi la meilleure offre du jour."
    else:
        body += f"\n\nMeilleure offre d'aujourd'hui : {today.get('resume') or money(today['total'])}"
    return head + body


def message(state: dict, now: datetime, advice: str) -> str:
    shown, blocks = {}, []
    for number, mine in state["scenarios"].items():
        if mine.get("record"):
            blocks.append(scenario_block(number, mine, now, shown))
        else:
            blocks.append(f"#### Scénario {number} : {mine['nom']}\n\nAucun vol trouvé jusqu'ici.")
    return "\n\n---\n\n".join(["**Rappel de 17 h**", *blocks, f"{advice}\n\n{FOOTER}"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    state = load_state()
    if not any(sc.get("record") for sc in state.get("scenarios", {}).values()):
        logging.info("Pas encore de résultat : pas de rappel")
        return 0
    advice, text = tendances.analyse()
    tendances.TRENDS.write_text(text)
    post_alerte(load_trip(), message(state, datetime.now(TZ), advice))
    return 0


if __name__ == "__main__":
    sys.exit(main())
