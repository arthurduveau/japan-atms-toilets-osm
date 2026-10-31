# Japan: ATMs for foreign cards and public toilets

Two datasets built from [OpenStreetMap](https://www.openstreetmap.org) for the 47 prefectures of Japan. They power the map of the PlanJapan travel app, offline.

| File | What it holds | Points |
|---|---|---|
| [`data/distributeurs.json`](data/distributeurs.json) | ATMs that accept cards issued abroad: Seven Bank (7-Eleven), Japan Post Bank (post offices), Lawson Bank, AEON Bank, with each network's conditions from its official pages | 53,242 |
| [`data/toilettes.json`](data/toilettes.json) | Public toilets, with price, wheelchair access and baby changing table when OpenStreetMap knows them | 31,145 |

OpenStreetMap data as of 31 October 2026.

[Français](#français) · [Español](#español)

## License

© OpenStreetMap contributors. These files are a derivative database of OpenStreetMap, made available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). The full text is in [`LICENSE`](LICENSE).

If you use them, credit « © OpenStreetMap contributors », link to <https://www.openstreetmap.org/copyright>, and share any database you derive from them under the same license.

## How the files are made

Python 3.12, standard library only.

1. `python3 outils/extraire.py` asks the public [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) for one prefecture at a time (`ISO3166-2` areas) and keeps each answer in `cache/overpass/`. It sends one request at a time per server, pauses between requests and retries politely.
2. `python3 outils/construire.py` turns the cache into `sortie/distributeurs.json` and `sortie/toilettes.json`, plus counts and checks in `stats/`.

The rules sit at the top of [`outils/construire.py`](outils/construire.py):

- **A network is kept only if its official pages say it takes foreign cards.** That leaves Seven Bank, Japan Post Bank, Lawson Bank and AEON Bank. E-net (in FamilyMart stores), city banks and regional banks are left out.
- **Each store stands for its network's ATM.** A 7-Eleven counts as a Seven Bank ATM and a post office as a Japan Post Bank ATM. A Lawson is marked `incertain` (Lawson Bank says some stores have no compatible ATM), and so is an AEON store. A mapped ATM (`amenity=atm`) a few metres from its store merges into it, and the store gets `atm: true`.
- **Toilets come from `amenity=toilets`.** Private, closed, emergency and customers-only toilets (`access=customers`) are left out.
- **No Japanese characters in displayed names.** Japanese names stay in `stats/`.

[`sources/officielles/comptes-officiels.json`](sources/officielles/comptes-officiels.json) holds the official store counts used to measure coverage. As of 31 October 2026, it is about 78 % of 7-Eleven stores and 77 % of Lawson stores. Post offices are about 100 %, but most come from a 2006 import.

## Format

- **Top level**:
  - `version`;
  - `verifie_le`, the day the network conditions were checked;
  - `rubrique`;
  - `reseaux` (ATMs only): `id`, `nom`, `conditions`, `cartes`, `plafond`, `frais`, `conseil`, and `source` (official page, date read);
  - `genres`, the name of each kind of point;
  - `jeux.osm`: attribution, license, OSM data date (`donnees_du`), and this repository (`copie`);
  - `points`.
- **Every point**:
  - `id`: the OSM element, `n` node, `w` way, `r` relation, followed by its number;
  - `type`, `lat`, `lon`;
  - `nom` and `carte` (name and short map label), in `fr`, `en` and `es`;
  - `horaires`, OSM `opening_hours` as written;
  - `rang`, the display priority;
  - `z`, the zoom from which the point shows, three points at most per 128-point map cell.
- **ATMs**: `reseaux` (network ids), `atm` (ATM confirmed in OSM), `incertain` (the ATM may be missing).
- **Toilets**: `prix` (`gratuit` free, `payant` paid, `don` donation), `fauteuil` (`oui`, `non`, `limite`), `bebe`, `femmes`, `hommes`, `mixte`.

Texts are written in French (`fr`), English (`en`) and Spanish (`es`).

---

## Français

Deux jeux de données tirés d'OpenStreetMap pour les 47 préfectures du Japon, utilisés hors ligne par la carte de l'app PlanJapon :

- `data/distributeurs.json` : 53 242 distributeurs qui acceptent les cartes émises à l'étranger (Seven Bank dans les 7-Eleven, Japan Post Bank dans les bureaux de poste, Lawson Bank, AEON Bank), avec les conditions de chaque réseau d'après ses pages officielles ;
- `data/toilettes.json` : 31 145 toilettes publiques (sans les toilettes privées, fermées, de secours ou réservées aux clients).

Données d'OpenStreetMap du 31 octobre 2026. © les contributeurs d'OpenStreetMap. Ces fichiers forment une base de données dérivée, sous [licence ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) (texte complet dans `LICENSE`). Pour les réutiliser : citer « © les contributeurs d'OpenStreetMap » et partager toute base qui en dérive sous la même licence.

La méthode est décrite plus haut, en anglais. `outils/extraire.py` interroge l'API Overpass préfecture par préfecture, puis `outils/construire.py` fabrique les deux fichiers ; ses règles sont en tête du script.

## Español

Dos conjuntos de datos extraídos de OpenStreetMap para las 47 prefecturas de Japón, usados sin conexión por el mapa de la app PlanJapon:

- `data/distributeurs.json`: 53.242 cajeros que aceptan tarjetas emitidas en el extranjero (Seven Bank en los 7-Eleven, Japan Post Bank en las oficinas de correos, Lawson Bank, AEON Bank), con las condiciones de cada red según sus páginas oficiales;
- `data/toilettes.json`: 31.145 baños públicos (sin los privados, cerrados, de emergencia ni los reservados a clientes).

Datos de OpenStreetMap del 31 de octubre de 2026. © colaboradores de OpenStreetMap. Estos archivos forman una base de datos derivada, bajo [licencia ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) (texto completo en `LICENSE`). Para reutilizarlos: citar « © colaboradores de OpenStreetMap » y compartir toda base derivada bajo la misma licencia.

El método se describe arriba, en inglés. `outils/extraire.py` consulta la API Overpass prefectura por prefectura y `outils/construire.py` genera los dos archivos; sus reglas están al principio del script.
