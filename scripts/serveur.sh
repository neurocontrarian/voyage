#!/bin/bash
# Recherche horaire depuis le serveur de Montréal (Google affiche les prix selon le pays de
# l'internaute ; depuis les serveurs américains de GitHub, Air Canada paraît plus chère).
# Lancé par cron :  17 * * * * <dossier>/scripts/serveur.sh
# Rappel quotidien (sans recherche) :  0 17 * * * <dossier>/scripts/serveur.sh rappel
set -uo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR" || exit 1
exec 9>"$DIR/.verrou"
case "${1:-recherche}" in
    rappel)                                # le rappel attend la fin d'une recherche en cours
        LOCK="-w 900"; MODULE=voyage.rappel; MSG="Rappel du %Y-%m-%d";;
    *)  LOCK="-n"; MODULE=voyage; MSG="Prix du %Y-%m-%d %H:%M";;
esac
flock $LOCK 9 || exit 0                    # une seule exécution à la fois
# Journal limité aux 2000 dernières lignes (raccourci avant de l'ouvrir en écriture).
tail -n 2000 serveur.log > serveur.log.tmp 2>/dev/null && mv serveur.log.tmp serveur.log
exec >>"$DIR/serveur.log" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M')"

git pull -q --rebase || exit 1             # récupère aussi les mises à jour du programme

# (Ré)installer les dépendances seulement si requirements.txt a changé.
[ -x .venv/bin/python ] || python3 -m venv .venv
if ! cmp -s requirements.txt .venv/requirements.txt; then
    .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/requirements.txt
fi

.venv/bin/python -m "$MODULE"

git add data
git diff --cached --quiet && exit 0
git commit -q -m "$(date "+$MSG")"   # horodatage pris après l'attente du verrou
git pull -q --rebase && git push -q
