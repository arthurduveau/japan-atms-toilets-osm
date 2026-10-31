#!/usr/bin/env python3
"""Fabrique les deux couches de la carte (format lu par l'app PlanJapon), depuis le cache Overpass :

- sortie/distributeurs.json : les distributeurs qui acceptent les cartes émises à l'étranger (Seven Bank, Japan Post
  Bank, Lawson Bank, AEON Bank), rubrique proposée `autre.distributeurs` ;
- sortie/toilettes.json : les toilettes publiques, rubrique proposée `autre.toilettes` ;
- stats/comptes.json : les comptes par réseau, région et préfecture, la couverture d'OSM face aux chiffres officiels,
  ce qui a été écarté et pourquoi ; stats/extraction-distributeurs.json et stats/extraction-toilettes.json : chaque point
  avec son id OSM, ses noms japonais et anglais et les étiquettes lues (pour le travail, pas pour l'app).

    python3 outils/construire.py

Bibliothèque standard seulement. Données d'OpenStreetMap (ODbL 1.0) : voir README.md et LICENSE.

Règles :
- un réseau n'entre que si une source officielle dit qu'il accepte les cartes étrangères (pages officielles des réseaux : liens dans `reseaux[].source`) :
  Seven Bank, Japan Post Bank, Lawson Bank, AEON Bank. E-net, les banques de ville et régionales restent dehors ;
- un 7-Eleven = un distributeur Seven Bank ; un bureau de poste = un distributeur Japan Post Bank ; un Lawson = un
  distributeur Lawson Bank « qui peut manquer » ; un magasin AEON = un distributeur AEON Bank « à vérifier » ; un
  distributeur cartographié (`amenity=atm`) dont l'opérateur est l'un de ces réseaux ; `atm=no` écarte le magasin ;
- un distributeur cartographié à quelques mètres de son magasin (ou de son bureau) s'y fond : le point garde le
  magasin, marqué `atm` (distributeur confirmé par OSM) ;
- toilettes : `amenity=toilets` sauf `access=private|no` et `access=customers` (réservées aux clients : écartées,
  comptées), sauf les toilettes de secours (マンホールトイレ, 災害, 防災) et ce qui est fermé.
- jamais de caractère japonais dans un texte montré : les noms japonais restent dans stats/.
"""
from __future__ import annotations

import gzip
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CACHE = RACINE / "cache" / "overpass"
SORTIE = RACINE / "sortie"
STATS = RACINE / "stats"
OFFICIELS = RACINE / "sources" / "officielles" / "comptes-officiels.json"

VERIFIE_LE = "2026-10-31"  # conditions des réseaux : pages officielles lues le 16/10/2026, Japan Post Bank relue le 31/10/2026

# Les 47 préfectures (ISO 3166-2) et les huit régions traditionnelles (Mie dans le Kansai, Okinawa avec Kyūshū).
PREFECTURES = {
    1: ("Hokkaidō", "hokkaido"), 2: ("Aomori", "tohoku"), 3: ("Iwate", "tohoku"), 4: ("Miyagi", "tohoku"),
    5: ("Akita", "tohoku"), 6: ("Yamagata", "tohoku"), 7: ("Fukushima", "tohoku"), 8: ("Ibaraki", "kanto"),
    9: ("Tochigi", "kanto"), 10: ("Gunma", "kanto"), 11: ("Saitama", "kanto"), 12: ("Chiba", "kanto"),
    13: ("Tōkyō", "kanto"), 14: ("Kanagawa", "kanto"), 15: ("Niigata", "chubu"), 16: ("Toyama", "chubu"),
    17: ("Ishikawa", "chubu"), 18: ("Fukui", "chubu"), 19: ("Yamanashi", "chubu"), 20: ("Nagano", "chubu"),
    21: ("Gifu", "chubu"), 22: ("Shizuoka", "chubu"), 23: ("Aichi", "chubu"), 24: ("Mie", "kansai"),
    25: ("Shiga", "kansai"), 26: ("Kyōto", "kansai"), 27: ("Ōsaka", "kansai"), 28: ("Hyōgo", "kansai"),
    29: ("Nara", "kansai"), 30: ("Wakayama", "kansai"), 31: ("Tottori", "chugoku"), 32: ("Shimane", "chugoku"),
    33: ("Okayama", "chugoku"), 34: ("Hiroshima", "chugoku"), 35: ("Yamaguchi", "chugoku"),
    36: ("Tokushima", "shikoku"), 37: ("Kagawa", "shikoku"), 38: ("Ehime", "shikoku"), 39: ("Kōchi", "shikoku"),
    40: ("Fukuoka", "kyushu"), 41: ("Saga", "kyushu"), 42: ("Nagasaki", "kyushu"), 43: ("Kumamoto", "kyushu"),
    44: ("Ōita", "kyushu"), 45: ("Miyazaki", "kyushu"), 46: ("Kagoshima", "kyushu"), 47: ("Okinawa", "kyushu"),
}
REGIONS = {"hokkaido": "Hokkaidō", "tohoku": "Tōhoku", "kanto": "Kantō", "chubu": "Chūbu", "kansai": "Kansai",
           "chugoku": "Chūgoku", "shikoku": "Shikoku", "kyushu": "Kyūshū et Okinawa"}


def trois(fr: str, en: str, es: str) -> dict:
    return {"fr": fr, "en": en, "es": es}


# ---------------------------------------------------------------------------------------------------------------
# Les réseaux et leurs conditions : sources officielles lues le 16/10/2026, Japan Post Bank
# relu le 31/10/2026 (page « International ATM service ») et son communiqué du 06/10/2026 (FamilyMart).
RESEAUX = [
    {
        "id": "seven-bank",
        "nom": trois("Seven Bank", "Seven Bank", "Seven Bank"),
        "conditions": trois("Visa et Mastercard 24 h/24 · 100 000 ¥ par retrait · frais selon la carte",
                            "Visa and Mastercard 24/7 · ¥100,000 per withdrawal · fees depend on the card",
                            "Visa y Mastercard 24 h · 100.000 ¥ por retiro · comisión según la tarjeta"),
        "cartes": trois("Visa et Mastercard 24 h/24 ; American Express et Diners de 0 h 05 à 23 h 50-23 h 55 ; "
                        "JCB, Discover et UnionPay de 0 h 10 à 23 h 50",
                        "Visa and Mastercard 24/7; American Express and Diners 12:05 am to 11:50-11:55 pm; "
                        "JCB, Discover and UnionPay 12:10 am to 11:50 pm",
                        "Visa y Mastercard 24 h; American Express y Diners de 0:05 a 23:50-23:55; "
                        "JCB, Discover y UnionPay de 0:10 a 23:50"),
        "plafond": trois("100 000 ¥ par retrait (30 000 ¥ avec une carte à piste magnétique)",
                         "¥100,000 per withdrawal (¥30,000 with a magnetic-stripe card)",
                         "100.000 ¥ por retiro (30.000 ¥ con tarjeta de banda magnética)"),
        "frais": trois("Selon la carte ; votre banque peut ajouter les siens",
                       "Depends on the card; your bank may add its own fees",
                       "Según la tarjeta; tu banco puede añadir sus propias comisiones"),
        "conseil": trois("Visa ou Mastercard : l'écran propose votre devise ou le yen ; en général, le yen coûte moins cher",
                         "Visa or Mastercard: the screen offers your currency or yen; yen is usually cheaper",
                         "Visa o Mastercard: la pantalla ofrece tu moneda o el yen; en general, el yen sale más barato"),
        "source": {"nom": trois("Seven Bank", "Seven Bank", "Seven Bank"),
                   "url": "https://www.sevenbank.co.jp/intlcard/card2.html", "le": "2026-10-16"},
    },
    {
        "id": "japan-post-bank",
        "nom": trois("Japan Post Bank", "Japan Post Bank", "Japan Post Bank"),
        "conditions": trois("Selon le distributeur, entre 7 h et 23 h au plus · 50 000 ¥ par opération · 220 ¥ avec certaines cartes",
                            "Depends on the ATM, 7 am to 11 pm at most · ¥50,000 per transaction · ¥220 with some cards",
                            "Según el cajero, de 7:00 a 23:00 como máximo · 50.000 ¥ por operación · 220 ¥ con algunas tarjetas"),
        "cartes": trois("Cartes émises à l'étranger acceptées dans tous les distributeurs Japan Post Bank ; "
                        "certains peuvent ne pas l'être selon l'emplacement",
                        "Cards issued abroad work at all Japan Post Bank ATMs; some may not, depending on location",
                        "Las tarjetas emitidas en el extranjero funcionan en todos los cajeros de Japan Post Bank; "
                        "algunos pueden no aceptarlas según el lugar"),
        "plafond": trois("50 000 ¥ par opération", "¥50,000 per transaction", "50.000 ¥ por operación"),
        "frais": trois("220 ¥ par retrait avec certaines cartes étrangères, plus les frais de votre banque",
                       "¥220 per withdrawal with some foreign cards, plus your bank's fees",
                       "220 ¥ por retiro con algunas tarjetas extranjeras, más las comisiones de tu banco"),
        "horaires": trois("Selon le distributeur ; au plus 7 h-23 h du lundi au samedi, 7 h-21 h le dimanche, les jours "
                          "fériés, le 31/12 et du 1er au 3/01",
                          "Depends on the ATM; at most 7 am-11 pm Monday to Saturday, 7 am-9 pm on Sundays, holidays, "
                          "Dec 31 and Jan 1-3",
                          "Según el cajero; como máximo de 7:00 a 23:00 de lunes a sábado y de 7:00 a 21:00 los domingos, "
                          "festivos, el 31/12 y del 1 al 3/01"),
        "attention": trois("Distributeurs compacts dans certains FamilyMart (0 h 05-23 h 55) : fermeture progressive "
                           "à partir de janvier 2027",
                           "Compact ATMs in some FamilyMart stores (12:05 am-11:55 pm): closing gradually from January 2027",
                           "Cajeros compactos en algunos FamilyMart (0:05-23:55): cierre progresivo desde enero de 2027"),
        "source": {"nom": trois("Japan Post Bank", "Japan Post Bank", "Japan Post Bank"),
                   "url": "https://www.jp-bank.japanpost.jp/en/ias/en_ias_index.html", "le": "2026-10-31"},
    },
    {
        "id": "aeon-bank",
        "nom": trois("AEON Bank", "AEON Bank", "AEON Bank"),
        "conditions": trois("Visa, Mastercard, JCB… · 50 000 ¥ par retrait · aux heures du magasin",
                            "Visa, Mastercard, JCB… · ¥50,000 per withdrawal · during store hours",
                            "Visa, Mastercard, JCB… · 50.000 ¥ por retiro · en el horario de la tienda"),
        "cartes": trois("Visa, Mastercard, JCB, Discover, UnionPay", "Visa, Mastercard, JCB, Discover, UnionPay",
                        "Visa, Mastercard, JCB, Discover, UnionPay"),
        "plafond": trois("50 000 ¥ par retrait", "¥50,000 per withdrawal", "50.000 ¥ por retiro"),
        "frais": trois("Selon l'émetteur de la carte (UnionPay : 75 ¥ de plus)",
                       "Depends on the card issuer (UnionPay: ¥75 extra)",
                       "Según el emisor de la tarjeta (UnionPay: 75 ¥ más)"),
        "horaires": trois("24 h/24, dans la limite des heures du magasin", "24/7, within the store's opening hours",
                          "24 h, dentro del horario de la tienda"),
        "attention": trois("Présence du distributeur à vérifier sur place", "Check on site that there is an ATM",
                           "Comprueba en el lugar que haya cajero"),
        "source": {"nom": trois("AEON Bank", "AEON Bank", "AEON Bank"),
                   "url": "https://www.aeonbank.co.jp/atm/en/", "le": "2026-10-16"},
    },
    {
        "id": "lawson-bank",
        "nom": trois("Lawson Bank", "Lawson Bank", "Lawson Bank"),
        "conditions": trois("24 h/24 · 50 000 ¥ par retrait · pas dans tous les Lawson",
                            "24/7 · ¥50,000 per withdrawal · not in every Lawson",
                            "24 h · 50.000 ¥ por retiro · no en todos los Lawson"),
        "cartes": trois("Cartes émises à l'étranger", "Cards issued abroad", "Tarjetas emitidas en el extranjero"),
        "plafond": trois("50 000 ¥ par retrait, par tranches de 10 000 ¥", "¥50,000 per withdrawal, in ¥10,000 steps",
                         "50.000 ¥ por retiro, en tramos de 10.000 ¥"),
        "frais": trois("Selon la carte et la banque émettrice, affichés avant validation",
                       "Depends on the card and the issuing bank, shown before you confirm",
                       "Según la tarjeta y el banco emisor, se muestran antes de confirmar"),
        "horaires": trois("24 h/24, sauf 15 min entre 3 h et 4 h", "24/7, except 15 min between 3 and 4 am",
                          "24 h, salvo 15 min entre las 3:00 y las 4:00"),
        "langues": trois("Écran en japonais, anglais, chinois ou coréen", "Screen in Japanese, English, Chinese or Korean",
                         "Pantalla en japonés, inglés, chino o coreano"),
        "attention": trois("Certains Lawson n'ont pas de distributeur compatible",
                           "Some Lawson stores have no compatible ATM",
                           "Algunos Lawson no tienen cajero compatible"),
        "source": {"nom": trois("Lawson Bank", "Lawson Bank", "Lawson Bank"),
                   "url": "https://www.lawsonbank.jp/international/en/", "le": "2026-10-16"},
    },
]

GENRES_DISTRIBUTEURS = {
    "seven_eleven": trois("7-Eleven", "7-Eleven", "7-Eleven"),
    "bureau_poste": trois("Bureau de poste", "Post office", "Oficina de correos"),
    "aeon": trois("AEON", "AEON", "AEON"),
    "lawson": trois("Lawson", "Lawson", "Lawson"),
    "distributeur": trois("Distributeur de billets", "ATM", "Cajero automático"),
    "agence": trois("Agence bancaire", "Bank branch", "Sucursal bancaria"),
}
GENRES_TOILETTES = {"toilettes": trois("Toilettes publiques", "Public toilets", "Baños públicos")}

JEU_OSM = {
    "editeur": trois("contributeurs d'OpenStreetMap", "OpenStreetMap contributors", "colaboradores de OpenStreetMap"),
    "attribution": trois("© les contributeurs d'OpenStreetMap", "© OpenStreetMap contributors",
                         "© colaboradores de OpenStreetMap"),
    "licence": "ODbL 1.0",
    "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
    "page": "https://www.openstreetmap.org/copyright",
    # Notre copie publique de la base dérivée (ODbL § 4.6).
    "copie": "https://github.com/arthurduveau/japan-atms-toilets-osm",
}

# ---------------------------------------------------------------------------------------------------------------
# Reconnaissance des réseaux dans les étiquettes d'OSM.
R_SEVEN = re.compile(r"セブン[\s\-‐‑–—－−ー・]?イレブン|7[\s\-‐‑–—－]?eleven|seven[\s\-‐‑–—－]?eleven", re.I)
R_SEVEN_BANK = re.compile(r"セブン銀行|seven\s*bank", re.I)
R_LAWSON = re.compile(r"ローソン|lawson", re.I)
R_LAWSON_BANK = re.compile(r"ローソン銀行|lawson\s*bank|ローソン・?エイティエム|lawson\s*atm", re.I)
R_YUCHO = re.compile(r"ゆうちょ|japan\s*post\s*(bank|atm)|jp\s*bank|郵便局", re.I)
R_AEON_BANK = re.compile(r"イオン銀行|(aeon|ÆON)\s*bank", re.I)
R_AEON = re.compile(r"^\s*(イオン|ＡＥＯＮ|AEON|ÆON)", re.I)
R_JP_POST = re.compile(r"日本郵便|日本郵政|japan\s*post(?!\s*bank)", re.I)
# Fermé : dans le nom, les mots courants ; dans une note ou une description, seulement une fermeture définitive
# (« Closed on Sundays » ou « 年末年始休業 » ne ferment rien).
R_FERME = re.compile(r"閉鎖|閉局|閉店|休止|廃止|休業|移転のため|\(closed\)|（closed）|\bclosed\b", re.I)
R_FERME_NOTE = re.compile(r"閉店しました|閉局しました|閉鎖されました|廃止されました|閉店済|閉局済|permanently\s+closed|has\s+closed|now\s+closed", re.I)
R_SECOURS = re.compile(r"マンホールトイレ|災害|防災|非常用")
# Réservé à un public restreint (base militaire, employés, membres, prison) ; « 自衛隊前店 » (devant la base) reste.
R_RESERVE = re.compile(r"(基地|駐屯地|自衛隊)[^前]*内|関係者(のみ|専用|以外)|(社員|職員|会員)(のみ|専用)|only\s+at\s+jasdf|刑務所|拘置所", re.I)
R_TOILETTE_GENERIQUE = re.compile(r"toilet|toiret|restroom|rest\s*room|lavator|\bwc\b|public|washroom|bathroom", re.I)
JAPONAIS = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
QID_SEVEN = {"Q259340"}
QID_LAWSON = {"Q1557223", "Q116957010", "Q11350960", "Q24866804", "Q11323850", "Q115868119"}
QID_AEON = {"Q11285951", "Q11286068"}
MARQUES_AEON_EXCLUES = re.compile(r"マックスバリュ|maxvalu|ザ・ビッグ|the\s*big|まいばすけっと|ミニストップ|ministop", re.I)

# Rayons de fusion (mètres).
R_DOUBLON = {"seven_eleven": 25, "lawson": 25, "bureau_poste": 40, "aeon": 300}
R_HOTE = {"seven_eleven": 60, "lawson": 60, "bureau_poste": 80, "aeon": 300}
HOTE_DU_RESEAU = {"seven-bank": "seven_eleven", "lawson-bank": "lawson", "japan-post-bank": "bureau_poste",
                  "aeon-bank": "aeon"}
ORDRE_RESEAUX = ["seven-bank", "japan-post-bank", "aeon-bank", "lawson-bank"]

# Zoom d'entrée : la règle de wifi_carte.py (trois points par case de 128 points d'écran, du zoom 4 à 16,5 ; 17 : tous).
PAR_CASE = 3
ZOOMS = [z / 2 for z in range(8, 34)]
ZOOM_MAX = 17.0


def champ(t: dict, *cles: str) -> str:
    return " | ".join(t[k] for k in cles if t.get(k))


def latin(texte: str | None) -> str | None:
    """Un texte montrable : sans japonais, sans espaces en trop ; sinon None."""
    if not texte:
        return None
    texte = re.sub(r"\s+", " ", texte).strip()
    if not texte or JAPONAIS.search(texte):
        return None
    return texte


def de(lieu: str) -> str:
    return ("d'" if lieu[:1].upper() in "AEIOUÂÊÎÔÛĀĒĪŌŪÉÈ" else "de ") + lieu


def reserve(t: dict) -> bool:
    # `access=customers` est la règle de tout magasin (on y entre en client) : il ne réserve rien ici.
    if (t.get("access") or "").strip().lower() in ("private", "no", "military", "permit"):
        return True
    return bool(R_RESERVE.search(champ(t, "name", "name:ja", "name:en", "note", "description", "access:description")))


def ferme(t: dict) -> bool:
    if any(k.startswith(("disused", "abandoned", "was:", "removed", "demolished")) for k in t):
        return True
    if t.get("opening_hours", "").strip().lower() in ("closed", "off"):
        return True
    return bool(R_FERME.search(champ(t, "name", "name:ja", "name:en")) or R_FERME_NOTE.search(champ(t, "note", "description")))


def horaires_montrables(h: str | None) -> str | None:
    """La valeur `opening_hours` telle quelle, si elle est courte, sur une ligne et sans japonais (montrée à l'écran)."""
    if not h:
        return None
    h = h.strip()
    return h if h and len(h) <= 120 and "\n" not in h and not JAPONAIS.search(h) else None


def distance_m(a: dict, b: dict) -> float:
    x = math.radians(b["lon"] - a["lon"]) * math.cos(math.radians((a["lat"] + b["lat"]) / 2))
    y = math.radians(b["lat"] - a["lat"])
    return 6371000 * math.hypot(x, y)


class Grille:
    """Index spatial simple : cases de 0,005° (≈ 500 m)."""

    def __init__(self, pas: float = 0.005):
        self.pas = pas
        self.cases: dict[tuple[int, int], list[dict]] = defaultdict(list)

    def _cle(self, lat: float, lon: float) -> tuple[int, int]:
        return int(math.floor(lat / self.pas)), int(math.floor(lon / self.pas))

    def ajouter(self, o: dict) -> None:
        self.cases[self._cle(o["lat"], o["lon"])].append(o)

    def retirer(self, o: dict) -> None:
        self.cases[self._cle(o["lat"], o["lon"])].remove(o)

    def proche(self, o: dict, rayon: float, filtre=lambda x: True) -> dict | None:
        n = max(1, math.ceil(rayon / (self.pas * 90000)))
        i, j = self._cle(o["lat"], o["lon"])
        meilleur, d_min = None, rayon
        for di in range(-n, n + 1):
            for dj in range(-n, n + 1):
                for x in self.cases.get((i + di, j + dj), ()):
                    if x is o or not filtre(x):
                        continue
                    d = distance_m(o, x)
                    if d <= d_min:
                        meilleur, d_min = x, d
        return meilleur


def mercator(lat: float, lon: float) -> tuple[float, float]:
    x = (lon + 180) / 360
    s = math.sin(math.radians(lat))
    return x, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def zooms_d_entree(points: list[dict]) -> dict[str, float]:
    """Le zoom d'entrée de chaque point : le premier demi-niveau où il est parmi les trois meilleurs de sa case."""
    tries = sorted(points, key=lambda p: p["rang"])
    positions = {p["id"]: mercator(p["lat"], p["lon"]) for p in tries}
    entree: dict[str, float] = {}
    for z in ZOOMS:
        cases = 4 * 2 ** z
        prises: dict[tuple[int, int], int] = {}
        for p in tries:
            x, y = positions[p["id"]]
            case = (int(x * cases), int(y * cases))
            if prises.get(case, 0) >= PAR_CASE:
                continue
            prises[case] = prises.get(case, 0) + 1
            entree.setdefault(p["id"], z)
    for p in tries:
        entree.setdefault(p["id"], ZOOM_MAX)
    return entree


# ---------------------------------------------------------------------------------------------------------------
def lire_cache() -> tuple[list[tuple[int, dict]], dict]:
    """Les éléments de toutes les préfectures, chacun une seule fois (la première préfecture qui le contient)."""
    vus: set[str] = set()
    elements: list[tuple[int, dict]] = []
    infos = {"osm_base": [], "prefectures": [], "manquantes": []}
    for n in sorted(PREFECTURES):
        chemin = CACHE / f"JP-{n:02d}.json"
        if not chemin.exists():
            infos["manquantes"].append(f"JP-{n:02d}")
            continue
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        infos["osm_base"].append(donnees.get("osm_base"))
        infos["prefectures"].append(f"JP-{n:02d}")
        for e in donnees["elements"]:
            cle = f"{e['type'][0]}{e['id']}"
            if cle in vus:
                continue
            vus.add(cle)
            if "lat" not in e and "center" not in e:
                continue
            elements.append((n, e))
    return elements, infos


def position(e: dict) -> tuple[float, float]:
    if "lat" in e:
        return e["lat"], e["lon"]
    return e["center"]["lat"], e["center"]["lon"]


def base(n: int, e: dict, t: dict) -> dict:
    lat, lon = position(e)
    return {"osm": f"{e['type'][0]}{e['id']}", "pref": n, "lat": lat, "lon": lon,
            "nom_ja": t.get("name:ja") or t.get("name"), "nom_en": t.get("name:en"), "tags": t}


def reseaux_atm(t: dict, cles: tuple[str, ...]) -> list[str]:
    texte = champ(t, *cles)
    r = set()
    if R_SEVEN_BANK.search(texte) or R_SEVEN.search(texte):
        r.add("seven-bank")
    if R_YUCHO.search(texte):
        r.add("japan-post-bank")
    if R_AEON_BANK.search(texte) or any(t.get(k, "").strip().upper() in ("イオン", "AEON") for k in ("operator", "brand")):
        r.add("aeon-bank")
    if R_LAWSON_BANK.search(texte) or R_LAWSON.search(texte):
        r.add("lawson-bank")
    return [x for x in ORDRE_RESEAUX if x in r]


# Pas `network` ni `description` : on y lit les réseaux où une carte est acceptée (« エポスカード(Enet,セブン銀行,
# ローソン銀行) » sur un distributeur EPOS), pas l'exploitant du distributeur.
CLES_ATM = ("operator", "operator:en", "operator:ja", "brand", "brand:en", "brand:ja", "name", "name:en", "name:ja")
CLES_ATM_HOTE = ("atm:operator", "atm:brand", "atm:name")


def classer_distributeurs(elements: list[tuple[int, dict]]) -> tuple[list[dict], list[dict], Counter]:
    """Les hôtes (magasins, bureaux de poste) et les distributeurs ou agences cartographiés, plus les écartés."""
    hotes: list[dict] = []
    atms: list[dict] = []
    ecartes: Counter = Counter()
    for n, e in elements:
        t = e.get("tags", {})
        amenity, shop = t.get("amenity"), t.get("shop")
        if amenity == "toilets":
            continue
        if shop == "convenience":
            marque = champ(t, "brand", "brand:en", "brand:ja", "name", "name:en", "name:ja")
            qid = t.get("brand:wikidata", "")
            if qid in QID_SEVEN or R_SEVEN.search(marque):
                genre = "seven_eleven"
            elif qid in QID_LAWSON or R_LAWSON.search(marque):
                genre = "lawson"
            else:
                autre = champ(t, *CLES_ATM_HOTE)
                if autre and reseaux_atm(t, CLES_ATM_HOTE):
                    o = base(n, e, t) | {"genre": "distributeur", "reseaux": reseaux_atm(t, CLES_ATM_HOTE),
                                         "atm": True, "hote": "konbini"}
                    atms.append(o)
                else:
                    m = re.search(r"famil|ファミリー|ministop|ミニストップ|daily|デイリー|newdays|seicomart|セイコーマート|poplar|ポプラ",
                                  marque, re.I)
                    ecartes[f"konbini hors réseau ({'FamilyMart' if m and re.search('famil|ファミリー', m.group(0), re.I) else 'autres enseignes ou sans marque'})"] += 1
                continue
            if ferme(t):
                ecartes[f"{genre} fermé"] += 1
                continue
            if reserve(t):
                ecartes[f"{genre} à accès réservé"] += 1
                continue
            if t.get("atm") == "no":
                ecartes[f"{genre} avec atm=no"] += 1
                continue
            o = base(n, e, t) | {"genre": genre, "atm": t.get("atm") == "yes"}
            if genre == "lawson":
                o["sous_marque"] = ("natural" if re.search(r"ナチュラル|natural", marque, re.I) else
                                    "store100" if re.search(r"ストア\s*100|store\s*100", marque, re.I) else
                                    "lawson")
            hotes.append(o)
        elif amenity == "post_office":
            nom = champ(t, "name", "name:ja")
            operateur = champ(t, "operator", "operator:en", "brand", "brand:en")
            japan_post = t.get("operator:wikidata") == "Q11509260" or bool(R_JP_POST.search(operateur))
            if operateur and not japan_post and "郵便局" not in operateur:
                ecartes["bureau d'un autre opérateur (Yamato, Sagawa…)"] += 1
                continue
            if not japan_post and "郵便局" not in nom and not re.search(r"post\s*office", t.get("name:en", ""), re.I):
                ecartes["« post_office » sans nom ni opérateur (réseau inconnu)"] += 1
                continue
            if nom and "郵便局" not in nom and not re.search(r"post\s*office", champ(t, "name", "name:en"), re.I):
                ecartes["Japan Post sans « 郵便局 » dans le nom (centre, agence…)"] += 1
                continue
            if ferme(t):
                ecartes["bureau de poste fermé"] += 1
                continue
            if reserve(t):
                ecartes["bureau de poste à accès réservé"] += 1
                continue
            if t.get("atm") == "no":
                ecartes["bureau de poste avec atm=no"] += 1
                continue
            simple = "簡易郵便局" in nom or bool(re.search(r"(summary|simple|simplified|contract(ed)?)\s+post\s*office",
                                                          t.get("name:en", ""), re.I))
            o = base(n, e, t) | {"genre": "bureau_poste", "atm": t.get("atm") == "yes", "simple": simple}
            hotes.append(o)
        elif amenity in ("atm", "bank"):
            r = reseaux_atm(t, CLES_ATM)
            if amenity == "bank" and not r:
                continue
            if not r:
                ecartes["distributeur d'une autre banque ou sans opérateur"] += 1
                continue
            if ferme(t):
                ecartes["distributeur fermé"] += 1
                continue
            if reserve(t):
                ecartes["distributeur à accès réservé (base, employés…)"] += 1
                continue
            genre = "agence" if amenity == "bank" and not re.search(r"ATM|ＡＴＭ|出張所", champ(t, "name")) else "distributeur"
            if genre == "agence" and set(r) - {"japan-post-bank", "aeon-bank"}:
                genre = "distributeur"  # Seven Bank et Lawson Bank n'ont pas de guichets : ce sont des distributeurs
            atms.append(base(n, e, t) | {"genre": genre, "reseaux": r, "atm": True})
        elif shop:
            marque = champ(t, "name", "brand", "name:en", "brand:en")
            qid = t.get("brand:wikidata", "")
            if not (R_AEON.search(t.get("name", "")) or R_AEON.search(t.get("brand", "")) or
                    R_AEON.search(t.get("name:en", "")) or (qid in QID_AEON and not t.get("name"))):
                continue
            if MARQUES_AEON_EXCLUES.search(marque) and not R_AEON.search(t.get("name", "")):
                ecartes["magasin du groupe AEON hors enseigne AEON (Maxvalu…)"] += 1
                continue
            if ferme(t):
                ecartes["aeon fermé"] += 1
                continue
            if t.get("atm") == "no":
                ecartes["aeon avec atm=no"] += 1
                continue
            hotes.append(base(n, e, t) | {"genre": "aeon", "atm": t.get("atm") == "yes", "galerie": shop == "mall"})
    return hotes, atms, ecartes


def richesse(o: dict) -> int:
    return len(o["tags"]) + (5 if o.get("nom_en") else 0) + (3 if o.get("galerie") else 0)


def fusionner(hotes: list[dict], atms: list[dict]) -> tuple[list[dict], Counter]:
    journal: Counter = Counter()
    # 1. Doublons d'un même magasin ou bureau (un nœud et le bâtiment, deux nœuds) : on garde le plus renseigné.
    gardes: list[dict] = []
    grille = Grille()
    for o in sorted(hotes, key=lambda o: (o["genre"], -richesse(o), o["osm"])):
        double = grille.proche(o, R_DOUBLON[o["genre"]], lambda x: x["genre"] == o["genre"])
        if double:
            double["atm"] = double["atm"] or o["atm"]
            double.setdefault("fusion", []).append(o["osm"])
            journal[f"doublon fondu ({o['genre']})"] += 1
            continue
        grille.ajouter(o)
        gardes.append(o)
    # 2. Un distributeur ou une agence à côté de son magasin ou de son bureau s'y fond : l'hôte est confirmé.
    restants: list[dict] = []
    for a in atms:
        reste = []
        for r in a["reseaux"]:
            genre_hote = HOTE_DU_RESEAU[r]
            hote = grille.proche(a, R_HOTE[genre_hote], lambda x: x["genre"] == genre_hote)
            if hote is None:
                reste.append(r)
                continue
            hote["atm"] = True
            horaires = a["tags"].get("opening_hours")
            if horaires and (genre_hote == "bureau_poste" or not hote["tags"].get("opening_hours")):
                hote["horaires_atm"] = horaires
            hote.setdefault("fusion", []).append(a["osm"])
            journal[f"{a['genre']} {r} fondu dans son hôte ({genre_hote})"] += 1
        if reste:
            a["reseaux"] = reste
            restants.append(a)
    # 3. Doublons entre distributeurs isolés d'un même réseau (plusieurs nœuds pour un même coin ATM).
    grille_atm = Grille()
    isoles: list[dict] = []
    for a in sorted(restants, key=lambda o: (-richesse(o), o["osm"])):
        double = grille_atm.proche(a, 15, lambda x: x["reseaux"] == a["reseaux"])
        if double:
            double.setdefault("fusion", []).append(a["osm"])
            journal["distributeur en double fondu"] += 1
            continue
        grille_atm.ajouter(a)
        isoles.append(a)
    return gardes + isoles, journal


def noms_distributeur(o: dict) -> tuple[dict | None, dict | None]:
    """Le nom de la fiche et le libellé court de la carte, seulement quand OSM donne un vrai nom en anglais."""
    t = o["tags"]
    if o["genre"] == "bureau_poste":
        en = latin(t.get("name:en"))
        if not en:
            m = re.search(r"[（(]([^（）()]*post\s*office[^（）()]*)[）)]", t.get("name", ""), re.I)
            en = latin(m.group(1)) if m else None
        if not en:
            return None, None
        m = re.fullmatch(r"(.+?)[\s,]+(?:(?:summary|simple|simplified|contract(?:ed)?)\s+)?post\s*office", en, re.I)
        if not m:
            return None, None
        lieu = m.group(1).strip(" ,-")
        if lieu.islower():
            lieu = lieu.title()
        if not lieu or re.search(r"japan\s*post", lieu, re.I):
            return None, None
        return trois(f"Bureau de poste {de(lieu)}", f"{lieu} Post Office", f"Oficina de correos de {lieu}"), trois(lieu, lieu, lieu)
    if o["genre"] in ("seven_eleven", "lawson"):
        # La succursale en anglais (`branch:en`, rare) : nom de la fiche seulement, pas de libellé sur la carte (ce
        # sont des mots anglais, « Hakata Station East », qu'on n'écrit pas sur une carte française).
        branche = latin(t.get("branch:en"))
        if branche and re.search(r"hogehoge|fixme|test", branche, re.I):
            branche = None
        if branche:
            branche = re.sub(r"\s+(shop|store|branch)$", "", branche, flags=re.I).strip()
            if branche.islower():
                branche = branche.title()
        marque = "7-Eleven" if o["genre"] == "seven_eleven" else {
            "natural": "Natural Lawson", "store100": "Lawson Store 100"}.get(o.get("sous_marque"), "Lawson")
        if branche:
            return trois(*[f"{marque} {branche}"] * 3), None
        if marque not in ("7-Eleven", "Lawson"):
            return trois(marque, marque, marque), None
        return None, None
    if o["genre"] == "aeon":
        en = latin(t.get("name:en")) or latin(t.get("name"))
        generiques = {"aeon", "æon", "aeonmall", "æonmall", "aeonstyle", "aeontown", "aeonfoodstyle",
                      "aeonsupercenter", "aeonbigextra", "aeonshoppingcenter"}
        if en and re.sub(r"[\s\-]", "", en.lower()) not in generiques:
            # La marque écrite d'une seule façon (« ÆON MALL », « Aeonmall » → « AEON Mall ») ; le reste en
            # majuscules passe en casse de titre (« AEON MALL HANYU » → « AEON Mall Hanyu »).
            m = re.match(r"^(?:aeon|æon)\s*(mall|style|town|food\s*style|super\s*center)?\b\s*(.*)$", en, re.I)
            if m:
                sous = {"mall": "Mall", "style": "Style", "town": "Town"}.get((m.group(1) or "").lower().replace(" ", ""),
                                                                            (m.group(1) or "").title())
                reste = re.sub(r"\s+(store|shop)$", "", m.group(2).strip(), flags=re.I)
                if reste.isupper() or reste.islower():
                    reste = reste.title()
                en = " ".join(x for x in ("AEON", sous, reste) if x)
            return trois(en, en, en), trois(en, en, en)
        return None, None
    en = latin(t.get("name:en"))
    if en and not re.fullmatch(r"(atm|.*\bbank\b(\s+atm)?)", en, re.I):
        return trois(en, en, en), None
    return None, None


def construire_distributeurs(elements) -> tuple[dict, list[dict], dict]:
    hotes, atms, ecartes = classer_distributeurs(elements)
    points_bruts, journal = fusionner(hotes, atms)
    sortie, travail = [], []
    for o in points_bruts:
        t = o["tags"]
        genre = o["genre"]
        reseaux = o.get("reseaux") or [next(r for r, g in HOTE_DU_RESEAU.items() if g == genre)]
        if genre == "bureau_poste":
            horaires = o.get("horaires_atm") or t.get("opening_hours:atm") or t.get("atm:opening_hours")
        else:
            horaires = o.get("horaires_atm") or t.get("opening_hours")
        horaires = horaires_montrables(horaires)
        incertain = not o["atm"] and (genre in ("lawson", "aeon") or (genre == "bureau_poste" and o.get("simple")))
        nom, carte = noms_distributeur(o)
        # Le rang : Seven Bank (100 000 ¥, 24 h/24) d'abord, puis Japan Post Bank, AEON, Lawson ; les agences
        # postales (簡易郵便局) en dernier ; dans chaque palier, les distributeurs confirmés par OSM d'abord.
        palier = {"seven-bank": 0, "japan-post-bank": 1, "aeon-bank": 2, "lawson-bank": 3}[reseaux[0]]
        if genre == "bureau_poste" and o.get("simple"):
            palier = 4
        point = {"id": o["osm"], "type": genre, "nom": nom, "carte": carte,
                 "lat": round(o["lat"], 6), "lon": round(o["lon"], 6),
                 "reseaux": [{"id": r} for r in reseaux],
                 "atm": True if o["atm"] and genre not in ("distributeur", "agence") else None,
                 "incertain": True if incertain else None,
                 "horaires": horaires,
                 "_cle": (palier, 0 if o["atm"] else 1, 0 if nom else 1, int(o["osm"][1:]))}
        sortie.append(point)
        travail.append({"id": o["osm"], "type": genre, "reseaux": reseaux, "prefecture": f"JP-{o['pref']:02d}",
                        "lat": point["lat"], "lon": point["lon"], "nom_ja": o.get("nom_ja"), "nom_en": o.get("nom_en"),
                        "nom": nom, "atm_confirme": o["atm"], "incertain": incertain, "simple": o.get("simple"),
                        "sous_marque": o.get("sous_marque"), "horaires": horaires,
                        "fusionnes": o.get("fusion"), "etiquettes": t})
    for rang, p in enumerate(sorted(sortie, key=lambda p: p["_cle"]), start=1):
        p["rang"] = rang
        del p["_cle"]
    entree = zooms_d_entree(sortie)
    for p in sortie:
        p["z"] = entree[p["id"]]
    sortie.sort(key=lambda p: p["rang"])
    points = [{k: v for k, v in p.items() if v is not None} for p in sortie]
    doc = {"version": 1, "verifie_le": VERIFIE_LE, "rubrique": "autre.distributeurs", "reseaux": RESEAUX,
           "genres": GENRES_DISTRIBUTEURS, "jeux": {"osm": JEU_OSM}, "points": points}
    return doc, travail, {"ecartes": ecartes, "fusions": journal}


def construire_toilettes(elements) -> tuple[dict, list[dict], dict]:
    sortie, travail = [], []
    ecartes: Counter = Counter()
    gardees: Counter = Counter()
    for n, e in elements:
        t = e.get("tags", {})
        if t.get("amenity") != "toilets":
            continue
        acces = (t.get("access") or t.get("toilets:access") or "").strip().lower()
        if acces in ("private", "no"):
            ecartes[f"access={acces}"] += 1
            continue
        if acces == "customers":
            ecartes["access=customers (réservées aux clients)"] += 1
            continue
        if acces in ("military", "delivery", "agricultural", "forestry", "emergency", "permit"):
            ecartes[f"access={acces}"] += 1
            continue
        if ferme(t):
            ecartes["fermées ou désaffectées"] += 1
            continue
        if R_SECOURS.search(champ(t, "name", "name:ja", "description", "note")):
            ecartes["toilettes de secours (catastrophes)"] += 1
            continue
        lat, lon = position(e)
        fee = (t.get("fee") or "").strip().lower()
        prix = {"no": "gratuit", "yes": "payant", "donation": "don"}.get(fee)
        roulant = (t.get("wheelchair") or t.get("toilets:wheelchair") or "").strip().lower()
        fauteuil = {"yes": "oui", "designated": "oui", "limited": "limite", "no": "non"}.get(roulant)
        table = (t.get("changing_table") or t.get("diaper") or "").strip().lower()
        bebe = True if table in ("yes", "limited") else False if table == "no" else None
        def oui_non(v):
            v = (v or "").strip().lower()
            return True if v == "yes" else False if v == "no" else None
        horaires = horaires_montrables(t.get("opening_hours"))
        en = latin(t.get("name:en"))
        nom = trois(en, en, en) if en and not R_TOILETTE_GENERIQUE.search(en) else None
        point = {"id": f"{e['type'][0]}{e['id']}", "type": "toilettes", "nom": nom,
                 "lat": round(lat, 6), "lon": round(lon, 6), "prix": prix, "fauteuil": fauteuil, "bebe": bebe,
                 "mixte": oui_non(t.get("unisex")), "hommes": oui_non(t.get("male")), "femmes": oui_non(t.get("female")),
                 "horaires": horaires}
        connus = sum(1 for k in ("prix", "fauteuil", "bebe", "mixte", "hommes", "femmes", "horaires") if point[k] is not None)
        palier = (0 if fauteuil == "oui" and prix != "payant" else 1 if fauteuil == "oui" else
                  2 if prix == "gratuit" else 4 if prix == "payant" else 3)
        point["_cle"] = (palier, -connus, e["id"])
        if acces in ("yes", "public", "permissive", "designated", "destination", ""):
            gardees["access=" + (acces or "(non renseigné)")] += 1
        else:
            gardees[f"access={acces} (gardées)"] += 1
        if t.get("portable") == "yes":
            gardees["dont portable=yes (cabines mobiles)"] += 1
        sortie.append(point)
        travail.append({"id": point["id"], "prefecture": f"JP-{n:02d}", "lat": point["lat"], "lon": point["lon"],
                        "nom_ja": t.get("name:ja") or t.get("name"), "nom_en": t.get("name:en"), "etiquettes": t})
    for rang, p in enumerate(sorted(sortie, key=lambda p: p["_cle"]), start=1):
        p["rang"] = rang
        del p["_cle"]
    entree = zooms_d_entree(sortie)
    for p in sortie:
        p["z"] = entree[p["id"]]
    sortie.sort(key=lambda p: p["rang"])
    points = [{k: v for k, v in p.items() if v is not None} for p in sortie]
    doc = {"version": 1, "verifie_le": VERIFIE_LE, "rubrique": "autre.toilettes", "genres": GENRES_TOILETTES,
           "jeux": {"osm": JEU_OSM}, "points": points}
    return doc, travail, {"ecartes": ecartes, "gardees": gardees}


# ---------------------------------------------------------------------------------------------------------------
def verifier(chemin: Path, doc: dict) -> None:
    """Garde-fous du format : ids uniques, rangs 1..N, coordonnées au Japon, aucun champ vide."""
    ids = [p["id"] for p in doc["points"]]
    if len(ids) != len(set(ids)):
        sys.exit(f"{chemin.name} : ids en double")
    if [p["rang"] for p in doc["points"]] != list(range(1, len(ids) + 1)):
        sys.exit(f"{chemin.name} : rangs non contigus")
    for p in doc["points"]:
        if not (20 <= p["lat"] <= 46.5 and 122 <= p["lon"] <= 154.5):
            sys.exit(f"{chemin.name} : point {p['id']} hors du Japon")
        for k, v in p.items():
            if v is None or v == "" or v == [] or v == {}:
                sys.exit(f"{chemin.name} : champ vide {k} au point {p['id']}")
        if "reseaux" in doc and not p.get("reseaux"):
            sys.exit(f"{chemin.name} : point {p['id']} sans réseau")


def ecrire(chemin: Path, doc: dict) -> dict:
    verifier(chemin, doc)
    texte = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    for p in doc.get("points", []):  # garde-fou : aucun japonais dans un texte montré
        for cle in ("nom", "carte"):
            for v in (p.get(cle) or {}).values():
                if JAPONAIS.search(v):
                    sys.exit(f"japonais dans {chemin.name}, point {p['id']}, {cle} : {v}")
    brut = texte.encode("utf-8")
    chemin.write_bytes(brut)
    return {"octets": len(brut), "gzip": len(gzip.compress(brut, 9))}


def pourcent(a: int, b: int | None) -> float | None:
    return round(100 * a / b, 1) if b else None


def statistiques(distributeurs: dict, travail_d: list[dict], toilettes: dict, travail_t: list[dict],
                 notes_d: dict, notes_t: dict, infos: dict, poids: dict) -> dict:
    officiels = json.loads(OFFICIELS.read_text(encoding="utf-8"))
    par_type = Counter(p["type"] for p in travail_d)
    par_reseau = Counter(r for p in travail_d for r in p["reseaux"])
    confirmes = Counter(p["type"] for p in travail_d if p["atm_confirme"])
    incertains = Counter(p["type"] for p in travail_d if p["incertain"])
    simples = sum(1 for p in travail_d if p["type"] == "bureau_poste" and p["simple"])
    lawson_sous = Counter(p["sous_marque"] for p in travail_d if p["type"] == "lawson")
    isoles = Counter(f"{p['type']} {'+'.join(p['reseaux'])}" for p in travail_d if p["type"] in ("distributeur", "agence"))
    # Par préfecture et par région.
    pref: dict[str, Counter] = defaultdict(Counter)
    for p in travail_d:
        pref[p["prefecture"]][p["type"]] += 1
        if p["type"] == "bureau_poste" and p["simple"]:
            pref[p["prefecture"]]["bureau_poste_simple"] += 1
        for r in p["reseaux"]:
            pref[p["prefecture"]]["reseau:" + r] += 1
    for p in travail_t:
        pref[p["prefecture"]]["toilettes"] += 1
    regions: dict[str, Counter] = defaultdict(Counter)
    for code, c in pref.items():
        regions[PREFECTURES[int(code[3:])][1]].update(c)
    o7 = officiels["magasins"]["seven-eleven"]["par_prefecture"]
    ol = officiels["magasins"]["lawson"]["par_prefecture"]
    op = {k: v["ouverts"] for k, v in officiels["magasins"]["bureaux-de-poste"]["par_prefecture"].items()}
    table_pref = []
    for n, (nom, region) in PREFECTURES.items():
        code = f"JP-{n:02d}"
        c = pref.get(code, Counter())
        table_pref.append({"code": code, "nom": nom, "region": region,
                           "seven_eleven": c["seven_eleven"], "seven_eleven_officiel": o7[code],
                           "seven_eleven_couverture": pourcent(c["seven_eleven"], o7[code]),
                           "lawson": c["lawson"], "lawson_officiel": ol[code],
                           "lawson_couverture": pourcent(c["lawson"], ol[code]),
                           "bureau_poste": c["bureau_poste"], "bureau_poste_officiel": op[code],
                           "bureau_poste_couverture": pourcent(c["bureau_poste"], op[code]),
                           "aeon": c["aeon"],
                           "distributeurs_isoles": c["distributeur"] + c["agence"],
                           "points_distributeurs": sum(c[g] for g in GENRES_DISTRIBUTEURS),
                           "toilettes": c["toilettes"]})
    table_reg = []
    for region, nom in REGIONS.items():
        c = regions.get(region, Counter())
        codes = [f"JP-{n:02d}" for n, (_, r) in PREFECTURES.items() if r == region]
        off7 = sum(o7[k] for k in codes)
        offl = sum(ol[k] for k in codes)
        offp = sum(op[k] for k in codes)
        table_reg.append({"region": region, "nom": nom, "seven_eleven": c["seven_eleven"], "seven_eleven_officiel": off7,
                          "seven_eleven_couverture": pourcent(c["seven_eleven"], off7),
                          "lawson": c["lawson"], "lawson_officiel": offl, "lawson_couverture": pourcent(c["lawson"], offl),
                          "bureau_poste": c["bureau_poste"], "bureau_poste_officiel": offp,
                          "bureau_poste_couverture": pourcent(c["bureau_poste"], offp), "aeon": c["aeon"],
                          "distributeurs_isoles": c["distributeur"] + c["agence"],
                          "points_distributeurs": sum(c[g] for g in GENRES_DISTRIBUTEURS), "toilettes": c["toilettes"],
                          **{f"reseau_{r}": c["reseau:" + r] for r in ORDRE_RESEAUX}})
    seven_bank = par_reseau["seven-bank"]
    aeon_bank = par_reseau["aeon-bank"]
    couverture = {
        "seven-eleven (magasins)": {"osm": par_type["seven_eleven"], "officiel": officiels["magasins"]["seven-eleven"]["total"],
                                     "au": officiels["magasins"]["seven-eleven"]["au"],
                                     "pourcent": pourcent(par_type["seven_eleven"], officiels["magasins"]["seven-eleven"]["total"])},
        "seven-bank (distributeurs)": {"osm": seven_bank, "officiel": "plus de 28 000",
                                       "pourcent_au_plus": pourcent(seven_bank, 28000)},
        "lawson (magasins)": {"osm": par_type["lawson"], "officiel": officiels["magasins"]["lawson"]["total"],
                              "au": officiels["magasins"]["lawson"]["au"],
                              "pourcent": pourcent(par_type["lawson"], officiels["magasins"]["lawson"]["total"])},
        "aeon-bank (distributeurs)": {"osm": aeon_bank, "officiel": "plus de 6 500", "pourcent_au_plus": pourcent(aeon_bank, 6500)},
        "bureaux de poste": {"osm": par_type["bureau_poste"], "officiel": officiels["magasins"]["bureaux-de-poste"]["total"],
                             "au": officiels["magasins"]["bureaux-de-poste"]["au"],
                             "pourcent": pourcent(par_type["bureau_poste"], officiels["magasins"]["bureaux-de-poste"]["total"]),
                             "directs_osm": par_type["bureau_poste"] - simples,
                             "directs_officiel": officiels["magasins"]["bureaux-de-poste"]["direct"],
                             "directs_pourcent": pourcent(par_type["bureau_poste"] - simples, officiels["magasins"]["bureaux-de-poste"]["direct"]),
                             "simples_osm": simples, "simples_officiel": officiels["magasins"]["bureaux-de-poste"]["simple"],
                             "simples_pourcent": pourcent(simples, officiels["magasins"]["bureaux-de-poste"]["simple"]),
                             "fermes_temporairement": officiels["magasins"]["bureaux-de-poste"]["fermes_temporairement"]},
        "japan-post-bank": {"osm": par_reseau["japan-post-bank"], "officiel": None,
                            "note": officiels["distributeurs"]["japan-post-bank"]["note"]},
    }
    return {
        "genere_avec": {"osm_base_min": min(x for x in infos["osm_base"] if x) if infos["osm_base"] else None,
                        "osm_base_max": max(x for x in infos["osm_base"] if x) if infos["osm_base"] else None,
                        "prefectures": len(infos["prefectures"]), "manquantes": infos["manquantes"]},
        "distributeurs": {"points": len(travail_d), "par_type": dict(par_type), "par_reseau": dict(par_reseau),
                          "atm_confirme_par_osm": dict(confirmes), "incertains": dict(incertains),
                          "bureaux_simples": simples, "lawson_sous_marques": dict(lawson_sous),
                          "isoles": dict(isoles), "ecartes": dict(notes_d["ecartes"].most_common()),
                          "fusions": dict(notes_d["fusions"].most_common()),
                          "avec_nom": sum(1 for p in travail_d if p["nom"]),
                          # Bureaux de poste venus de l'import de 2006 (国土数値情報, « source=KSJ2 ») : des bureaux fermés
                          # depuis peuvent y rester (OSM compte plus d'agences que Japan Post n'en a d'ouvertes).
                          "bureaux_import_2006": sum(1 for p in travail_d if p["type"] == "bureau_poste" and (
                              "KSJ" in (p["etiquettes"].get("source") or "") or "2006" in (p["etiquettes"].get("note") or ""))),
                          "bureaux_import_2006_revus": sum(1 for p in travail_d if p["type"] == "bureau_poste" and (
                              "KSJ" in (p["etiquettes"].get("source") or "") or "2006" in (p["etiquettes"].get("note") or ""))
                              and (p["etiquettes"].get("check_date") or p["etiquettes"].get("survey:date"))),
                          "avec_horaires": sum(1 for p in travail_d if p["horaires"])},
        "toilettes": {"points": len(travail_t), "ecartees": dict(notes_t["ecartes"].most_common()),
                      "gardees": dict(notes_t["gardees"].most_common()),
                      "attributs": {k: dict(Counter(p.get(k) for p in toilettes["points"] if k in p))
                                    for k in ("prix", "fauteuil", "bebe", "mixte", "hommes", "femmes")},
                      "avec_horaires": sum(1 for p in toilettes["points"] if "horaires" in p),
                      "avec_nom": sum(1 for p in toilettes["points"] if "nom" in p)},
        "couverture": couverture,
        "regions": table_reg,
        "prefectures": table_pref,
        "zooms_entree": {
            "distributeurs": dict(sorted(Counter(p["z"] for p in distributeurs["points"]).items())),
            "toilettes": dict(sorted(Counter(p["z"] for p in toilettes["points"]).items()))},
        "poids": poids,
    }


def main() -> int:
    elements, infos = lire_cache()
    if infos["manquantes"]:
        print(f"attention : {len(infos['manquantes'])} préfectures manquent au cache : {', '.join(infos['manquantes'])}")
    SORTIE.mkdir(exist_ok=True)
    STATS.mkdir(exist_ok=True)
    distributeurs, travail_d, notes_d = construire_distributeurs(elements)
    toilettes, travail_t, notes_t = construire_toilettes(elements)
    osm_du = min(x for x in infos["osm_base"] if x) if infos["osm_base"] else None
    for doc in (distributeurs, toilettes):
        doc["jeux"]["osm"] = doc["jeux"]["osm"] | {"donnees_du": osm_du}
    poids = {"distributeurs.json": ecrire(SORTIE / "distributeurs.json", distributeurs),
             "toilettes.json": ecrire(SORTIE / "toilettes.json", toilettes)}
    for nom, travail in (("extraction-distributeurs.json", travail_d), ("extraction-toilettes.json", travail_t)):
        (STATS / nom).write_text(json.dumps(travail, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    stats = statistiques(distributeurs, travail_d, toilettes, travail_t, notes_d, notes_t, infos, poids)
    (STATS / "comptes.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    d, t = stats["distributeurs"], stats["toilettes"]
    print(f"distributeurs : {d['points']} points {d['par_type']} ; réseaux {d['par_reseau']}")
    print(f"toilettes : {t['points']} points ; écartées {t['ecartees']}")
    for nom, p in poids.items():
        print(f"{nom} : {p['octets'] / 1e6:.2f} Mo, {p['gzip'] / 1e6:.2f} Mo en gzip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
