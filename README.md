# voyage — surveillance automatique du prix des vols

Toutes les heures, un serveur à Montréal interroge Google Flights pour le voyage décrit dans
[`config/voyage.yaml`](config/voyage.yaml). Le programme calcule le **coût réel avec les
valises**, puis enregistre le résultat dans ce dépôt. Dès qu'un meilleur prix apparaît, une
alerte est publiée dans un ticket GitHub, et GitHub envoie un courriel.

**Pourquoi un serveur à Montréal et pas GitHub Actions ?** Google affiche les prix selon le
pays de l'internaute. Depuis les serveurs américains de GitHub, les mêmes vols Air Canada
coûtaient 3 339 $ au lieu de 2 961 $ (mesuré le 15 oct. 2026). Les prix de TAP et
d'Air Transat, eux, étaient identiques. GitHub Actions sert donc à deux choses :
publier les alertes, pour que le courriel parte (GitHub ne notifie pas ses propres messages
au propriétaire), et faire le veilleur, avec un ticket « panne » si le serveur n'a rien
publié depuis 3 h.

Voyage surveillé actuellement : Montréal → Portugal (Lisbonne ou Porto), départ à partir du
25 mars 2027, retour le 3 avril au plus tard, au moins 6 nuits, 3 passagers, 2 valises en soute.

## Où voir les résultats

| Quoi | Où |
|---|---|
| Alertes (nouveau meilleur prix) | ticket **« ✈️ Alertes prix »** (étiquette `alerte-prix`) |
| Rappel quotidien à 17 h (meilleure offre de tous les temps + du jour) | même ticket, un commentaire par jour, même sans nouveau record |
| Tendances (meilleure heure / meilleur jour pour acheter) | [`data/tendances.md`](data/tendances.md), résumé dans le rappel de 17 h |
| Dernière recherche, top 5 détaillé | [`data/dernier_resultat.md`](data/dernier_resultat.md) |
| Historique heure par heure | [`data/historique.csv`](data/historique.csv) |
| Panne (serveur éteint, Google a changé…) | ticket **« ⚠️ … ne fonctionne plus »** (étiquette `panne`) |

Pour recevoir les courriels, il faut que les notifications GitHub par courriel soient
activées (Settings → Notifications). Chaque alerte mentionne le propriétaire du dépôt.

Le rappel de 17 h ne lance aucune recherche : il lit `data/etat.json` (record et meilleure
offre du jour). Cron du serveur : `0 17 * * * ~/voyage-serveur/scripts/serveur.sh rappel`.
Les tendances (`python -m voyage.tendances`) comparent chaque prix à la moyenne de sa journée
(effet heure) et le prix le plus bas de chaque jour à la moyenne de sa semaine (effet jour) ; elles
n'apparaissent qu'après 5 journées et 2 semaines de relevés.

## Comment le prix est calculé

1. **Prix Google Flights** : total taxes incluses pour tous les passagers, en $ CA.
   Il correspond au tarif le moins cher de la compagnie, souvent sans valise en soute.
2. **Vérification du tarif de base** : pour les meilleurs résultats, le programme redemande
   les mêmes vols en excluant l'« économie de base ». Si le prix ne bouge pas, le tarif
   affiché n'est pas un tarif de base. C'est le cas par exemple pour Air Canada Standard,
   qui inclut une valise. Si le prix monte, on obtient le prix exact du tarif suivant.
3. **Politique de chaque compagnie** ([`config/compagnies.yaml`](config/compagnies.yaml)) :
   pour chaque trajet, le programme compare deux options. Soit on garde le tarif affiché et
   on paie les valises, soit on passe au tarif qui les inclut. Il retient la moins chère et
   indique ce que le tarif suivant apporterait (choix du siège, modifications…).
4. **Préférence de qualité** : une compagnie peut être classée comme si elle coûtait plus
   cher (`penalite_qualite` dans `config/compagnies.yaml`). C'est le cas de **TAP (+10 %)** :
   3 étoiles Skytrax, 73e mondial en 2026, ponctualité parmi les plus faibles d'Europe.
   TAP reste proposée et passe en tête si elle est vraiment moins chère. Le prix affiché reste
   le vrai prix, et les alertes suivent ce classement.
5. **Escales** :
   - au plus une escale par trajet ;
   - correspondance de 60 min à 3 h ;
   - pas plus de 2 h de vol en plus qu'un direct ;
   - et seulement si le total est **au moins 15 % moins cher** que le meilleur direct.

Les types de résultats :

- **aller-retour** : prix exact de Google pour l'aller et le retour indiqués.
- **2 allers simples** : deux billets séparés (prix exact de chacun). Permet de mélanger les
  compagnies ou les villes.
- **multi-villes (estimé)** : arrivée dans une ville et départ d'une autre, avec la même
  compagnie. Depuis août 2026, Google ne laisse plus interroger ce mode sans navigateur.
  On l'estime donc selon la règle tarifaire des compagnies (moitié de l'aller-retour vers
  chaque ville). À réserver en « multi-destinations » sur le site de la compagnie.
- La meilleure option **villes différentes** est toujours affichée « pour info », même si son
  escale ne passe pas la règle des 15 %.

⚠️ Les montants marqués « estimé » (frais de valise de certains tarifs, écarts entre tarifs)
viennent des règles publiées ou observées. Il faut **vérifier le prix final sur le site de la
compagnie** avant d'acheter, puis corriger `config/compagnies.yaml` si un montant a changé.

## Réutiliser pour un autre voyage

Modifier [`config/voyage.yaml`](config/voyage.yaml) : aéroports, dates, nuits, passagers,
valises, règles d'escale. Si une nouvelle compagnie ressort souvent, ajouter ses tarifs dans
`config/compagnies.yaml` ; sinon une règle générique prudente s'applique. Supprimer
`data/etat.json` pour repartir de zéro dans les alertes.

## Installation sur un serveur

Il faut un serveur allumé en permanence, situé au Canada, avec `git` et `gh` connectés au
compte GitHub :

```bash
git clone https://github.com/neurocontrarian/voyage.git ~/voyage-serveur
~/voyage-serveur/scripts/serveur.sh          # premier essai (crée .venv, journal serveur.log)
crontab -e                                   # ajouter :
17 * * * * $HOME/voyage-serveur/scripts/serveur.sh
```

À chaque exécution, le script récupère la dernière version du programme, lance la
recherche, puis pousse `data/`.

## Lancer à la main

```bash
pip install -r requirements.txt
python -m voyage --essai     # affiche le résultat, sans alerte ni écriture dans data/
python -m pytest -q tests
```


## Sources et briques réutilisées

- [fli](https://github.com/punitarani/fli) : lecture de Google Flights (page publique),
  aller-retour détaillé, liens de réservation. Le paramètre « exclure l'économie de base »
  (champ 25) est ajouté ici.
- Idée de l'historique dans le dépôt et des alertes par ticket :
  [AndrewFoudree/flight-tracker](https://github.com/AndrewFoudree/flight-tracker).
  Ce projet passe par des API payantes ou à quota (SerpApi, Travelpayouts) ; ici, rien n'est payant.
- Politiques tarifaires : Air Canada (avis sur les frais de bagages, 14 mai 2026), Air Transat
  (options tarifaires), TAP (produits TAP). Voir `config/compagnies.yaml`.

Limites : Google Flights n'a pas d'API officielle, donc le format peut changer sans
préavis. Dans ce cas, le ticket « panne » s'ouvre après 3 échecs d'affilée, et il suffit
souvent de mettre à jour la version de fli dans `requirements.txt`.
