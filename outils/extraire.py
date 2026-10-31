#!/usr/bin/env python3
"""Extraction OpenStreetMap (API Overpass publique) des distributeurs et des toilettes, préfecture par préfecture.

    python3 outils/extraire.py [--rafraichir] [JP-13 JP-27 ...]

Une requête par préfecture (zone `ISO3166-2`), réponse gardée telle quelle dans `cache/overpass/JP-XX.json` (avec la
requête, le serveur et l'horodatage des données d'OSM). Une préfecture déjà en cache n'est pas redemandée, sauf avec
`--rafraichir` ou si la requête a changé (empreinte `requete_sha`).

Politesse : une seule requête à la fois par serveur (deux serveurs publics au plus en même temps), une pause entre deux
requêtes, et des réessais espacés sur les erreurs 429/5xx ou sur une réponse Overpass incomplète (`remark`).

Bibliothèque standard seulement (Python 3.12).
"""
from __future__ import annotations

import hashlib
import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CACHE = RACINE / "cache" / "overpass"
JOURNAL = RACINE / "cache" / "extraction.log"

# Deux instances publiques (wiki OSM « Overpass API », liste des instances), avec le nombre de requêtes simultanées :
# overpass-api.de annonce 2 créneaux par adresse IP (/api/status, « Rate limit: 2 ») ; une seule sur l'instance de VK.
SERVEURS = [
    ("https://overpass-api.de/api/interpreter", 2),
    ("https://maps.mail.ru/osm/tools/overpass/api/interpreter", 1),
]
AGENT = "planjapon-carte-distributeurs-toilettes/1.0 (+https://planjapon.com)"
PAUSE = 8           # secondes entre deux requêtes d'un même serveur
ESSAIS = 15         # tentatives par préfecture, tous serveurs confondus (31/10 : serveurs saturés, refus de connexion)
DELAI_HTTP = 1000   # secondes ; la requête Overpass a son propre [timeout:600]

# Ce qu'on demande : les distributeurs (magasins et bureaux qui les abritent, distributeurs isolés, agences des
# banques visées) et les toilettes. Le tri fin (réseau, accès) se fait en local, dans construire.py.
REQUETE = """[out:json][timeout:600];
area["ISO3166-2"="{code}"]["admin_level"="4"]->.a;
(
  nwr["amenity"~"^(atm|post_office|toilets)$"](area.a);
  nwr["amenity"="bank"]["name"~"ゆうちょ|イオン銀行|セブン銀行|ローソン銀行"](area.a);
  nwr["shop"="convenience"](area.a);
  nwr["shop"]["brand:wikidata"~"^(Q259340|Q1557223|Q11285951|Q11286068)$"](area.a);
  nwr["shop"~"^(supermarket|mall|department_store|general|variety_store)$"]["name"~"イオン|AEON",i](area.a);
);
out center tags;
"""

# Les 47 préfectures (code ISO 3166-2) : les plus lourdes d'abord, pour voir tôt si un serveur cale.
ORDRE = [13, 27, 14, 23, 1, 11, 12, 28, 40, 22, 26, 34, 4, 8, 15, 20, 21, 9, 10, 43, 7, 33, 24, 46, 47, 25, 38,
         35, 42, 17, 44, 3, 2, 45, 5, 6, 37, 30, 19, 16, 29, 18, 36, 39, 41, 32, 31]


def code(n: int) -> str:
    return f"JP-{n:02d}"


def empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]


def noter(message: str) -> None:
    ligne = f"{datetime.now().strftime('%H:%M:%S')} {message}"
    print(ligne, flush=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def en_cache(cle: str, sha: str) -> bool:
    chemin = CACHE / f"{cle}.json"
    if not chemin.exists():
        return False
    try:
        with chemin.open(encoding="utf-8") as f:
            entete = json.load(f)
        return entete.get("requete_sha") == sha
    except (OSError, ValueError):
        return False


def demander(serveur: str, requete: str) -> dict:
    corps = urllib.parse.urlencode({"data": requete}).encode("utf-8")
    req = urllib.request.Request(serveur, data=corps, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=DELAI_HTTP) as r:
        brut = r.read()
    reponse = json.loads(brut)
    remarque = reponse.get("remark")
    # Overpass répond 200 avec une remarque quand la requête a été coupée (temps, mémoire) : la réponse est incomplète.
    if remarque and ("error" in remarque.lower() or "timed out" in remarque.lower()):
        raise RuntimeError(f"réponse incomplète : {remarque}")
    if "elements" not in reponse:
        raise RuntimeError("réponse sans « elements »")
    return reponse


def travailleur(serveur: str, file: "queue.Queue[tuple[str, int]]", erreurs: dict, verrou: threading.Lock,
                rafraichir: bool = False) -> None:
    nom = urllib.parse.urlparse(serveur).netloc
    while True:
        try:
            cle, essai = file.get_nowait()
        except queue.Empty:
            return
        requete = REQUETE.format(code=cle)
        # Un autre processus ou un autre fil a pu la ramener entre-temps.
        if not rafraichir and en_cache(cle, empreinte(requete)):
            continue
        debut = time.time()
        try:
            reponse = demander(serveur, requete)
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
            duree = time.time() - debut
            code_http = getattr(e, "code", None)
            # Serveur fermé (connexion refusée) : la préfecture retourne dans la file sans compter un essai, et ce
            # travailleur s'arrête (31/10 : overpass-api.de injoignable à partir de 21 h 29).
            if "refused" in str(e).lower() or "failed to connect" in str(e).lower():
                noter(f"{cle} : {nom} refuse la connexion, ce serveur est laissé de côté")
                file.put((cle, essai))
                return
            noter(f"{cle} : échec sur {nom} après {duree:.0f} s ({code_http or ''} {e}) — essai {essai + 1}/{ESSAIS}")
            with verrou:
                erreurs[cle] = f"{nom}: {e}"
            if essai + 1 < ESSAIS:
                file.put((cle, essai + 1))
            # Serveur saturé (429, 502, 503, 504) : une pause qui s'allonge doucement (30 s, puis 60 s, 90 s… 2 min au
            # plus) avant de reprendre une préfecture.
            time.sleep(min(120, 30 * (1 + essai // 3)))
            continue
        duree = time.time() - debut
        sortie = {
            "prefecture": cle,
            "requete_sha": empreinte(requete),
            "requete": requete,
            "serveur": serveur,
            "recu_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "osm_base": reponse.get("osm3s", {}).get("timestamp_osm_base"),
            "copyright": reponse.get("osm3s", {}).get("copyright"),
            "elements": reponse["elements"],
        }
        temporaire = CACHE / f"{cle}.json.part"
        temporaire.write_text(json.dumps(sortie, ensure_ascii=False), encoding="utf-8")
        temporaire.replace(CACHE / f"{cle}.json")
        with verrou:
            erreurs.pop(cle, None)
        noter(f"{cle} : {len(reponse['elements'])} éléments en {duree:.0f} s ({nom}, OSM {sortie['osm_base']})")
        time.sleep(PAUSE)


def joignable(serveur: str) -> bool:
    """Le serveur répond-il à /api/status ? (sinon, inutile d'y user les essais)"""
    try:
        req = urllib.request.Request(serveur.replace("/interpreter", "/status"), headers={"User-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read(200)
        return True
    except urllib.error.HTTPError:
        return True  # il répond, même saturé
    except (urllib.error.URLError, OSError):
        return False


def main(arguments: list[str]) -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    rafraichir = "--rafraichir" in arguments
    voulues = [a for a in arguments if a.startswith("JP-")] or [code(n) for n in ORDRE]
    file: "queue.Queue[tuple[str, int]]" = queue.Queue()
    for cle in voulues:
        if not rafraichir and en_cache(cle, empreinte(REQUETE.format(code=cle))):
            continue
        file.put((cle, 0))
    if file.empty():
        noter("tout est en cache")
        return 0
    noter(f"{file.qsize()} préfectures à demander, {sum(n for _, n in SERVEURS)} requêtes simultanées au plus")
    erreurs: dict[str, str] = {}
    verrou = threading.Lock()
    # Une préfecture remise dans la file après le départ des travailleurs (échec en fin de liste) : on relance un tour.
    while not file.empty():
        actifs = [(s, n) for s, n in SERVEURS if joignable(s)]
        for s, _ in SERVEURS:
            if (s, _) not in actifs:
                noter(f"{urllib.parse.urlparse(s).netloc} injoignable : laissé de côté pour ce tour")
        if not actifs:
            noter("aucun serveur joignable : nouvel essai dans 2 minutes")
            time.sleep(120)
            continue
        fils = [threading.Thread(target=travailleur, args=(s, file, erreurs, verrou, rafraichir))
                for s, n in actifs for _ in range(n)]
        for i, f in enumerate(fils):
            f.start()
            time.sleep(3 + i)
        for f in fils:
            f.join()
    manquantes = [c for c in voulues if not (CACHE / f"{c}.json").exists()]
    noter(f"fin : {len(voulues) - len(manquantes)}/{len(voulues)} en cache" + (f", manquantes {manquantes}" if manquantes else ""))
    return 1 if manquantes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
