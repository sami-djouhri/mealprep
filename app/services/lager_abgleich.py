"""Zutaten mit Lager-Produkten verknuepfen, per Namensvorschlag.

Warum es das braucht: ``Ingredient.lager_product_id`` ist die einzige
Verbindung zwischen einer Zutat hier und einem Produkt im Lager. Ohne sie
liefert ``LagerAdapter.get_available`` fuer jede Zutat 0, und das hat Folgen
an jeder Stelle, an der der Adapter haengt: die Machbarkeit eines Rezepts ist
immer "nichts da", und die Einkaufsliste zieht den Vorrat nie ab. Man kauft,
was man hat.

Gemessen am 2026-09-12: **null von 47 Zutaten** waren verknuepft, bei 45
Rezepten und 679 geplanten Mahlzeiten. Die Kopplung war also vollstaendig
gebaut und trug nichts. Verknuepft wird ueber
``PUT /inventory/ingredients/{id}/link-lager``, eine Zutat nach der anderen,
von Hand. Genau diese Art Arbeit macht niemand.

Der Abgleich hier schlaegt vor, er entscheidet nicht. Zwei Gruende:

1. Die Zuordnung ist unscharf. "Milch (1.5%)" und "Milch" sind wahrscheinlich
   dasselbe, "Paprika" in Stueck und "Paprika" in Gramm sind es nicht.
2. Eine falsche Verknuepfung ist schlimmer als keine: sie rechnet einen
   Vorrat gegen, den es nicht gibt, und streicht Dinge von der Einkaufsliste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import DomainError
from app.models import Ingredient
from app.services.lager_adapter import LagerAdapter, LagerUnavailable


def normalisieren(name: str) -> str:
    """Namen auf eine vergleichbare Form bringen.

    Umlaute muessen umgeschrieben werden, nicht entfernt: die beiden Dienste
    schreiben sie unterschiedlich. Lager fuehrt "Kaese" und "Haehnchenbrust",
    mealprep "Kaese (gerieben)" und "Haehnchenbrust". Ein Vergleich ohne diese
    Umschrift findet je nach Datenbestand die Haelfte nicht.
    """
    s = name.lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(alt, neu)
    s = re.sub(r"\(.*?\)", "", s)  # "Milch (1.5%)" -> "milch"
    return re.sub(r"[^a-z0-9]", "", s)


@dataclass
class ProduktOhneZutat:
    """Ein Produkt im Lager, zu dem es hier keine Zutat gibt.

    Die Gegenrichtung zu ``Vorschlag``, und sie fehlte bis zum 2026-10-24.
    ``vorschlaege()`` laeuft ueber die **unverknuepften Zutaten** und sucht
    je Zutat ein Produkt. Ein Produkt, zu dem es hier ueberhaupt keine Zutat
    gibt, kann diese Schleife nie erreichen: es gibt keinen Durchlauf, der es
    finden koennte. Gemessen am 2026-10-24 lagen so **6 von 20 Produkten**
    mit echtem Bestand ausserhalb des Blickfelds (Joghurt, Karotten, Mehl,
    Salz, Zucker, dazu Paprika am Einheitenkonflikt), darunter vier
    Grundzutaten.

    Beide Richtungen zusammen sind die ganze Frage: ``vorschlaege()``
    beantwortet "Zutat da, Verknuepfung fehlt", diese hier "Zutat fehlt
    ganz". Eine Pruefung, die nur eine Richtung laeuft, meldet null Funde und
    sieht dabei aus wie eine vollstaendige Auskunft.
    """

    lager_product_id: int
    lager_product_name: str
    lager_unit: str | None
    kategorie: str | None = None
    #: Summe ueber alle Bestandseintraege in der Standardeinheit des Produkts.
    #: ``None`` heisst **nicht gemessen**, nicht "nichts da" - derselbe
    #: Unterschied, den ``bestand_gesamt`` traegt.
    bestand: float | None = None


@dataclass
class Vorschlag:
    ingredient_id: int
    ingredient_name: str
    ingredient_unit: str
    lager_product_id: int
    lager_product_name: str
    lager_unit: str | None
    #: "name" = Name stimmt nach Normalisierung, "synonym" = ueber ein Synonym
    treffer_art: str
    #: Einheiten stimmen ueberein. False heisst nicht falsch, aber pruefen.
    einheit_gleich: bool
    hinweis: str | None = None


def vorschlaege(db: Session, lager: LagerAdapter | None = None) -> list[Vorschlag]:
    """Unverknuepfte Zutaten gegen die Lager-Produkte halten."""
    lager = lager or LagerAdapter()
    produkte = lager.search_products()
    if not produkte:
        return []

    # Index ueber Namen UND Synonyme. Der erste Eintrag gewinnt, damit ein
    # Synonym einen echten Namen nicht verdraengt.
    index: dict[str, dict] = {}
    for p in produkte:
        index.setdefault(normalisieren(p.get("name", "")), p)
    for p in produkte:
        for syn in p.get("synonyms") or []:
            index.setdefault(normalisieren(syn), p)

    namen = {normalisieren(p.get("name", "")) for p in produkte}

    gefunden: list[Vorschlag] = []
    zutaten = db.execute(
        select(Ingredient).where(Ingredient.lager_product_id.is_(None))
    ).scalars().all()

    for zutat in zutaten:
        schluessel = normalisieren(zutat.name_canonical)
        produkt = index.get(schluessel)
        if not produkt:
            continue

        lager_einheit = produkt.get("default_unit")
        einheit_gleich = bool(lager_einheit) and zutat.default_unit == lager_einheit
        hinweis = None
        if not einheit_gleich:
            hinweis = (
                f"Einheiten unterschiedlich: hier {zutat.default_unit}, "
                f"im Lager {lager_einheit}. Der Bestand wuerde falsch gerechnet."
            )

        gefunden.append(Vorschlag(
            ingredient_id=zutat.id,
            ingredient_name=zutat.name_canonical,
            ingredient_unit=zutat.default_unit,
            lager_product_id=produkt["id"],
            lager_product_name=produkt.get("name", ""),
            lager_unit=lager_einheit,
            treffer_art="name" if schluessel in namen else "synonym",
            einheit_gleich=einheit_gleich,
            hinweis=hinweis,
        ))

    # Was Aufmerksamkeit braucht, steht oben: False sortiert vor True, also
    # kommen die Einheiten-Konflikte zuerst. (Mit ``not`` davor waeren sie
    # ans Ende gerutscht, genau dorthin, wo man sie uebersieht.)
    gefunden.sort(key=lambda v: (v.einheit_gleich, v.ingredient_name))
    return gefunden


def produkte_ohne_zutat(
    db: Session, lager: LagerAdapter | None = None
) -> list[ProduktOhneZutat]:
    """Produkte im Lager, zu denen es hier keine Zutat gibt.

    Die Gegenrichtung zu ``vorschlaege()``. Zusammen decken beide die ganze
    Frage ab, ob mealprep mit dem arbeitet, was im Haus liegt; einzeln decken
    sie je eine Haelfte und sehen beide nach einer vollstaendigen Auskunft
    aus. Begruendung in ``ProduktOhneZutat``.

    Ein Produkt zaehlt nur dann als fehlend, wenn **weder** eine Zutat
    darauf verknuepft ist **noch** ein Zutatenname oder Synonym darauf
    passt. Der zweite Teil ist der Schnitt zwischen den beiden Listen: ohne
    ihn stuende "Paprika" in beiden, hier als fehlende Zutat und dort als
    Vorschlag mit Einheitenkonflikt, und zwei Listen, die dasselbe Ding
    verschieden benennen, sind schlechter als eine.

    Der Bestand kommt aus **einem** Abruf (``bestand_gesamt``), nicht aus
    einem je Produkt: 20 Produkte waeren 20 Anfragen und liefen in lagers
    Deckel von 60 Anfragen je Minute, in den dieselbe Kette am 2026-09-12
    schon einmal gelaufen ist.
    """
    lager = lager or LagerAdapter()
    produkte = lager.search_products()
    if not produkte:
        return []

    zutaten = db.execute(select(Ingredient)).scalars().all()
    verknuepfte_ids = {
        z.lager_product_id for z in zutaten if z.lager_product_id is not None
    }
    zutaten_namen: set[str] = set()
    for zutat in zutaten:
        zutaten_namen.add(normalisieren(zutat.name_canonical))
        for syn in zutat.synonyms or []:
            zutaten_namen.add(normalisieren(syn))

    # ``None`` heisst nicht gemessen und wird so weitergegeben, statt als 0 zu
    # erscheinen: "liegt ungenutzt im Vorrat" und "Bestand unbekannt" sind
    # verschiedene Auskuenfte.
    bestaende = lager.bestand_gesamt()

    fehlend: list[ProduktOhneZutat] = []
    for produkt in produkte:
        pid = produkt.get("id")
        if pid is None or pid in verknuepfte_ids:
            continue
        name = produkt.get("name", "")
        kandidaten = {normalisieren(name)}
        for syn in produkt.get("synonyms") or []:
            kandidaten.add(normalisieren(syn))
        if kandidaten & zutaten_namen:
            continue  # vorschlaege() deckt diesen Fall ab

        einheit = produkt.get("default_unit")
        bestand = None
        if bestaende is not None:
            bestand = bestaende.get((pid, einheit or "g"), 0.0)

        fehlend.append(ProduktOhneZutat(
            lager_product_id=pid,
            lager_product_name=name,
            lager_unit=einheit,
            kategorie=produkt.get("category"),
            bestand=bestand,
        ))

    # Was im Vorrat liegt, steht oben: ungenutzter Bestand ist der Grund, aus
    # dem diese Liste ueberhaupt gelesen wird. Ein unbekannter Bestand sortiert
    # wie 0, weil er keine Dringlichkeit begruendet, die man messen konnte.
    fehlend.sort(key=lambda p: (-(p.bestand or 0.0), p.lager_product_name))
    return fehlend


def zutat_aus_produkt(
    db: Session, lager_product_id: int, lager: LagerAdapter | None = None
) -> Ingredient:
    """Eine Zutat aus einem vorhandenen Lager-Produkt anlegen und verknuepfen.

    Die Richtung ist Absicht und folgt der Vorgabe vom 2026-10-24:
    "eingekaufte Zutaten landen im Lager, mealprep arbeitet mit dem was es
    gibt." mealprep legt deshalb **keine Sorte im Lager an**, sondern
    uebernimmt eine, die es dort schon gibt. Das Lager bleibt Besitzer des
    Bestands, hier entsteht nur die Zutat, mit der geplant werden kann.

    Uebernommen wird, was drueben steht: Name, Kategorie, Einheit,
    Naehrwerte, Packungsgroessen, Haltbarkeitstyp und Synonyme. Nichts davon
    wird geraten.

    ⚠️ ``allergens`` bleibt **leer**. Die Allergene sind hier bei 0 von 47
    Zutaten gesetzt, und das Lager fuehrt sie nicht; ein erfundener Wert waere
    bei einem Gesundheitsmerkmal die schlechteste Wahl. Leer heisst
    "unbekannt" und ist als solches lesbar.
    """
    lager = lager or LagerAdapter()
    produkte = lager.search_products()
    if not produkte:
        raise LagerUnavailable(
            "Lager liefert keine Produktliste. Es wurde keine Zutat angelegt, "
            "weil sich sonst nicht pruefen laesst, ob es das Produkt gibt."
        )

    produkt = next((p for p in produkte if p.get("id") == lager_product_id), None)
    if produkt is None:
        raise DomainError(
            "Dieses Produkt gibt es im Lager nicht",
            {"lager_product_id": lager_product_id},
        )

    # Zwei Wege hierher sind falsch und muessen getrennt abgewiesen werden,
    # weil der Ausweg jeweils ein anderer ist: ist das Produkt schon
    # verknuepft, gibt es nichts zu tun; traegt eine Zutat den Namen bereits,
    # ist das ein Verknuepfungsfall fuer ``uebernehmen()`` und kein
    # Anlegefall. Ein gemeinsames "geht nicht" wuerde beide in dieselbe
    # Sackgasse schicken.
    schon_verknuepft = db.execute(
        select(Ingredient).where(Ingredient.lager_product_id == lager_product_id)
    ).scalars().first()
    if schon_verknuepft is not None:
        raise DomainError(
            "Dieses Produkt ist schon mit einer Zutat verknuepft",
            {
                "lager_product_id": lager_product_id,
                "ingredient_id": schon_verknuepft.id,
                "ingredient_name": schon_verknuepft.name_canonical,
            },
        )

    name = produkt.get("name") or ""
    schluessel = normalisieren(name)
    for zutat in db.execute(select(Ingredient)).scalars().all():
        namen = {normalisieren(zutat.name_canonical)} | {
            normalisieren(s) for s in (zutat.synonyms or [])
        }
        if schluessel in namen:
            raise DomainError(
                "Eine Zutat mit diesem Namen gibt es hier schon. Sie muss "
                "verknuepft werden, nicht neu angelegt.",
                {
                    "lager_product_id": lager_product_id,
                    "ingredient_id": zutat.id,
                    "ingredient_name": zutat.name_canonical,
                    "hinweis": "POST /inventory/lager-abgleich verknuepft Paare",
                },
            )

    zutat = Ingredient(
        name_canonical=name,
        category=produkt.get("category"),
        default_unit=produkt.get("default_unit") or "g",
        shelf_life_type=produkt.get("shelf_life_type") or "MHD",
        lager_product_id=lager_product_id,
    )
    if produkt.get("nutrition_per_100"):
        zutat.nutrition_per_100 = produkt["nutrition_per_100"]
    zutat.typical_pack_sizes = [
        int(g) for g in (produkt.get("typical_pack_sizes") or [])
    ]
    zutat.synonyms = list(produkt.get("synonyms") or [])
    db.add(zutat)
    db.flush()
    return zutat


def bekannte_produkt_ids(lager: LagerAdapter) -> set[int] | None:
    """Die Produktnummern, die es im Lager wirklich gibt.

    Gegen die wird jede neue Verknuepfung gehalten. Eine Verknuepfung auf
    eine Nummer ins Leere scheitert naemlich nirgends: ``get_available``
    liefert dafuer 0, und 0 liest sich als "nichts da". Man kauft dann
    dauerhaft etwas nach, das im Vorrat liegt.

    ``None`` heisst: lager ist nicht angebunden, es kann nicht geprueft
    werden. Antwortet ein angebundenes lager nicht, gibt es eine Ausnahme
    statt einer leeren Menge, sonst hiesse "kein Produkt bekannt" dasselbe wie
    "alles unbekannt", und jede Uebernahme fiele still aus.

    Ein Abruf fuer alle Paare, nicht einer je Paar: 33 Paare waeren 33
    Anfragen und liefen in den Anfragedeckel von lager, den derselbe Tag schon
    einmal gerissen hat.
    """
    if not lager.available:
        return None
    produkte = lager.search_products()
    if not produkte:
        raise LagerUnavailable(
            "Lager liefert keine Produktliste. Es wurde nichts verknuepft, "
            "weil sich sonst nicht pruefen laesst, ob es die Produkte gibt."
        )
    return {p["id"] for p in produkte if "id" in p}


def uebernehmen(
    db: Session,
    paare: list[tuple[int, int]],
    lager: LagerAdapter | None = None,
) -> list[Ingredient]:
    """Bestaetigte Paare verknuepfen (Zutat, Lager-Produkt).

    Nur unverknuepfte Zutaten werden angefasst: eine bestehende Zuordnung
    wird nie stillschweigend ueberschrieben, auch nicht von einem besseren
    Vorschlag.

    Seit dem 2026-09-13 wird geprueft, ob es das Produkt drueben ueberhaupt
    gibt. Eine Verknuepfung auf eine Nummer ins Leere scheitert naemlich
    nirgends: ``get_available`` liefert dafuer 0, und 0 liest sich als "nichts
    da". Man kauft dann dauerhaft etwas nach, das im Vorrat liegt. Genau diese
    Sorte Fehler hat die Kette am 12.09. monatelang unsichtbar getragen.

    Geprueft wird gegen **einen** Abruf des Katalogs, nicht mit einer Anfrage
    je Paar: 33 Paare waeren 33 Anfragen und liefen in den Anfragedeckel von
    lager, den derselbe Tag schon einmal gerissen hat.

    Antwortet lager nicht, wird **nichts** verknuepft und ``LagerUnavailable``
    geworfen. Das ist die unbequemere, aber richtige Wahl, und die Ausnahme
    gehoert dazu: eine leere Rueckgabe hiesse sonst zweierlei zugleich,
    naemlich "nichts passte" und "nicht geprueft". Genau diese Doppeldeutigkeit
    ist der Fehler, gegen den hier ueberhaupt geprueft wird.
    """
    if not paare:
        return []

    bekannte_ids = bekannte_produkt_ids(lager or LagerAdapter())

    geaendert: list[Ingredient] = []
    for ingredient_id, lager_product_id in paare:
        if bekannte_ids is not None and lager_product_id not in bekannte_ids:
            continue
        zutat = db.get(Ingredient, ingredient_id)
        if zutat is None or zutat.lager_product_id is not None:
            continue
        zutat.lager_product_id = lager_product_id
        geaendert.append(zutat)
    return geaendert
