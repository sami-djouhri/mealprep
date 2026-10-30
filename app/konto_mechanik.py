"""Mechanik fuer das Loeschen eines Mandanten. Eigenstaendig, ohne Saganta-Paket.

HERKUNFT UND PFLEGE
===================

Diese Datei ist der Zwilling von ``saganta_dienst/loeschen.py`` im saganta-Repo,
auf das Noetige eingedampft. Sie liegt hier als Kopie und nicht als Abhaengigkeit,
aus demselben Grund wie ``backend_auth.py`` und ``mandant_ableiten.py``: dieser
Dienst muss **ohne das saganta-Repo baubar** bleiben, auch weil er veroeffentlicht
werden soll.

Damit die vier Kopien nicht auseinanderlaufen, sind sie **byte-identisch** und
werden von aussen abgeglichen:
``python3 ~/docker/saganta/scripts/loeschwege-abgleichen.py``
Nur ``app/konto.py`` daneben ist je Dienst verschieden, denn nur dort steht, was
dieser Dienst ueber seine eigenen Tabellen weiss. Wer hier etwas aendert, aendert
es in allen vier und laesst den Abgleich laufen.

KEINE NETZROUTE, UND DAS IST ABSICHT
======================================

Anders als die Saganta-Backends haben diese Dienste einen gewollten headerlosen
Pfad: ``get_db`` faellt fuer interne Aufrufer auf ``DEFAULT_OWNER_SUB`` zurueck.
Eine Loeschroute dahinter waere eine Fernbedienung, die beim ersten headerlosen
Aufruf **den Owner** trifft. Deshalb gibt es hier nur den Betreiberweg:

    docker exec -w /app <container> python -m app.konto --sub X [--loeschen]

Er verlangt Zugriff auf den Wirt, den hat ohnehin nur, wer die Platte auch so
loeschen koennte. Gerufen wird er ueber
``~/docker/saganta/scripts/konto-loeschen.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MANDANTEN_SPALTEN = frozenset({"owner_sub", "sub", "owner", "created_by_sub", "user_sub"})


@dataclass(frozen=True)
class Schritt:
    """Eine Tabelle und die Bedingung, die darin den Mandanten trifft.

    ``wo`` ist eine SQL-Bedingung mit genau einem Parameter ``:sub``, aus dem
    Quelltext und nicht aus einer Anfrage; der Mandant kommt gebunden.
    """

    tabelle: str
    wo: str
    warum: str = ""


def eigene(tabelle: str, spalte: str = "owner_sub", warum: str = "") -> Schritt:
    return Schritt(tabelle=tabelle, wo=f"{spalte} = :sub", warum=warum)


@dataclass(frozen=True)
class Plan:
    """Der Loeschweg dieses Dienstes. Reihenfolge = Kinder vor Eltern."""

    dienst: str
    schritte: tuple[Schritt, ...]
    #: Tabellen, die bewusst allen gehoeren: Zutaten, Uebungskatalog,
    #: Seed-Rezepte. Je Eintrag gehoert die Begruendung in ``konto.py``.
    gemeinsam: frozenset[str] = frozenset()
    #: Tabellen ausserhalb der Modelle, die ein Datenbank-Trigger mitfuehrt
    #: (FTS5-Indizes). Sie stehen hier, damit die Pruefungen sie als bedacht
    #: verbuchen koennen, statt sie gar nicht zu sehen. ⚠️ Ein Volltextindex ist
    #: dabei kein Nebenschauplatz: er traegt den Klartext mit.
    per_trigger: frozenset[str] = frozenset()


@dataclass
class Bericht:
    dienst: str
    sub: str
    trockenlauf: bool
    zeilen: dict[str, int] = field(default_factory=dict)
    nebenwirkungen: list[str] = field(default_factory=list)
    luecken: list[str] = field(default_factory=list)
    reste: dict[str, int] = field(default_factory=dict)
    dateifehler: list[str] = field(default_factory=list)

    @property
    def summe(self) -> int:
        return sum(self.zeilen.values())

    @property
    def sauber(self) -> bool:
        return not self.luecken and not self.reste and not self.dateifehler

    def als_dict(self) -> dict[str, Any]:
        return {
            "dienst": self.dienst, "sub": self.sub, "trockenlauf": self.trockenlauf,
            "zeilen": self.zeilen, "summe": self.summe,
            "nebenwirkungen": self.nebenwirkungen, "luecken": self.luecken,
            "reste": self.reste, "dateifehler": self.dateifehler, "sauber": self.sauber,
        }


def abdeckung_pruefen(plan: Plan, metadata: Any) -> list[str]:
    """Welche Tabelle faellt aus dem Loeschweg? Klartext-Befunde, leer ist gut.

    Das Soll kommt aus den SQLAlchemy-Metadaten und damit aus den Modellen,
    nicht aus einer zweiten Liste. Eine neu hinzugefuegte Tabelle mit
    Mandantenspalte erscheint hier sofort, auch wenn sie noch keine Zeile
    traegt: der Befund soll vor den Daten da sein. Ohne das faellt sie still aus
    dem Loeschweg, und ein Lauf meldet weiterhin Erfolg.

    Eine Tabelle gilt als abgedeckt, wenn sie in einem Schritt steht,
    ausdruecklich als gemeinsam erklaert ist, oder per ``ondelete="CASCADE"`` an
    einer abgedeckten Tabelle haengt. Das Letzte transitiv, denn Ketten sind
    laenger als ein Glied.
    """
    if not metadata.tables:
        raise RuntimeError(
            "Die Metadaten sind leer. Vermutlich wurde app.models nicht importiert. "
            "Ohne Tabellen laufen Abdeckungs- und Restpruefung blind."
        )

    befunde: list[str] = []
    abgedeckt = ({s.tabelle for s in plan.schritte} | set(plan.gemeinsam)
                 | set(plan.per_trigger))

    kanten: dict[str, list[tuple[str, str | None]]] = {}
    for name, tabelle in metadata.tables.items():
        for spalte in tabelle.columns:
            for fk in spalte.foreign_keys:
                kanten.setdefault(name, []).append((fk.column.table.name, fk.ondelete))

    gewachsen = True
    while gewachsen:
        gewachsen = False
        for name in metadata.tables:
            if name in abgedeckt:
                continue
            for eltern, ondelete in kanten.get(name, []):
                if eltern in abgedeckt and (ondelete or "").upper() == "CASCADE":
                    abgedeckt.add(name)
                    gewachsen = True
                    break

    for name, tabelle in sorted(metadata.tables.items()):
        if name in abgedeckt:
            continue
        eigene_spalten = [c.name for c in tabelle.columns if c.name in MANDANTEN_SPALTEN]
        if eigene_spalten:
            befunde.append(
                f"{name} traegt {'/'.join(eigene_spalten)}, steht aber in keinem Schritt: "
                f"Bestand dieses Mandanten bliebe stehen."
            )
            continue
        eltern_liste = kanten.get(name, [])
        if not eltern_liste:
            befunde.append(
                f"{name} hat keine Mandantenspalte und keinen Fremdschluessel. "
                f"Wenn das gemeinsamer Bestand ist, gehoert es in `gemeinsam`."
            )
            continue
        beschreibung = ", ".join(
            f"{eltern} ({ondelete or 'ohne ondelete'})" for eltern, ondelete in eltern_liste
        )
        befunde.append(
            f"{name} haengt an {beschreibung} und wird dadurch nicht mitgeloescht. "
            f"Entweder CASCADE setzen oder einen eigenen Schritt ergaenzen."
        )
    return befunde


def ungedeckte_live_tabellen(plan: Plan, db: Any, metadata: Any) -> list[str]:
    """Welche Tabelle gibt es in der Datenbank, die der Plan nicht kennt?

    WARUM DAS ZUSAETZLICH ZU ``abdeckung_pruefen`` NOETIG IST

    ``abdeckung_pruefen`` liest die SQLAlchemy-Metadaten, also die **Modelle**.
    Alles, was ein Dienst per rohem SQL anlegt, steht dort nicht und ist fuer
    sie unsichtbar. Das ist keine theoretische Grenze: gemessen am 2026-10-06
    behielt der ``briefkasten`` nach einem als "sauber" gemeldeten Loeschlauf
    das **Embedding des geloeschten Briefs** in ``letter_vec`` (eine
    ``vec0``-Virtualtabelle, die keinen Fremdschluessel haben kann). Ein
    384-dimensionaler Vektor kodiert den Inhalt und erlaubt
    Aehnlichkeitssuche; er ist Nutzerinhalt, nicht Verwaltung.

    Diese Pruefung fragt deshalb die **Datenbank** und nicht die Modelle. Sie
    braucht eine Verbindung und laeuft darum nicht im reinen Abdeckungstest,
    sondern bei jedem Lauf und im Abgleich-Werkzeug.

    Schattentabellen von Virtualtabellen (``letter_fts_data``,
    ``letter_vec_rowids`` und ihre Geschwister) werden ihrem Elternteil
    zugerechnet, sobald der erklaert ist: sie werden von FTS5 bzw. vec0 selbst
    verwaltet, und sie einzeln aufzuzaehlen waere eine Liste, die mit der
    naechsten SQLite-Fassung veraltet.

    ⚠️ ``ondelete`` wird auch hier aufgeloest, aus der Datenbank statt aus den
    Modellen. Die erste Fassung tat das nicht und meldete sofort einen
    Fehlalarm (``paperless_import_map``, das sein ``ON DELETE CASCADE`` hat und
    sauber mitfaellt). Eine Pruefung, die bei jeder per-SQL angelegten Tabelle
    mit CASCADE anschlaegt, wird nach dem dritten Mal ignoriert, und dann ist
    sie schlechter als keine.
    """
    from sqlalchemy import text

    erklaert = ({s.tabelle for s in plan.schritte} | set(plan.gemeinsam)
                | set(plan.per_trigger) | set(metadata.tables))

    zeilen = db.execute(text(
        "SELECT name, COALESCE(sql, '') FROM sqlite_master WHERE type='table'"
    )).all()
    alle = {name: ddl for name, ddl in zeilen
            if not name.startswith("sqlite_") and not name.startswith("alembic")}

    # Kanten aus der Datenbank: Kind -> [(Eltern, on_delete), ...]
    kanten: dict[str, list[tuple[str, str]]] = {}
    for name in alle:
        try:
            fks = db.execute(text(f"PRAGMA foreign_key_list({name})")).all()
        except Exception:
            continue  # Virtualtabellen antworten hier nicht
        for reihe in fks:
            # (id, seq, table, from, to, on_update, on_delete, match)
            kanten.setdefault(name, []).append((reihe[2], (reihe[6] or "").upper()))

    abgedeckt = set(erklaert)
    gewachsen = True
    while gewachsen:
        gewachsen = False
        for name in alle:
            if name in abgedeckt:
                continue
            for eltern, on_delete in kanten.get(name, []):
                if eltern in abgedeckt and on_delete == "CASCADE":
                    abgedeckt.add(name)
                    gewachsen = True
                    break

    # ⚠️ Schatten gehoeren nur zu einer **Virtualtabelle**, nie zu einer
    # gewoehnlichen. Die erste Fassung prüfte nur den Namensanfang gegen alles
    # Abgedeckte, und damit verbuchte sie ``notizen_fts`` als Schatten von
    # ``notizen``: der Volltextindex, also genau die Tabelle, die den Klartext
    # traegt, waere still durchgefallen. Gefunden hat das die Positivkontrolle
    # im Test, nicht das Nachdenken.
    virtuelle_eltern = {name for name, ddl in alle.items()
                        if "VIRTUAL TABLE" in ddl.upper() and name in abgedeckt}

    befunde: list[str] = []
    for name, ddl in sorted(alle.items()):
        if name in abgedeckt:
            continue
        if any(name.startswith(f"{eltern}_") for eltern in virtuelle_eltern):
            continue
        art = "Virtualtabelle" if "VIRTUAL TABLE" in ddl.upper() else "Tabelle"
        befunde.append(
            f"{name}: {art} in der Datenbank, aber in keinem Modell, in keinem "
            f"Schritt und an keiner CASCADE-Kante. Sie wird per rohem SQL angelegt "
            f"und bleibt beim Loeschen stehen, bis sie einen Schritt bekommt oder "
            f"als gemeinsam erklaert ist."
        )
    return befunde


def _zaehlen(db: Any, tabelle: str, wo: str, sub: str) -> int:
    from sqlalchemy import text

    treffer = db.execute(text(f"SELECT count(*) FROM {tabelle} WHERE {wo}"),
                         {"sub": sub}).scalar()
    return int(treffer or 0)


def _reste_suchen(db: Any, plan: Plan, metadata: Any, sub: str) -> dict[str, int]:
    """Traegt nach dem Loeschen noch eine Tabelle den Mandanten?

    Fragt die Datenbank, nicht den Plan. Ein Schritt, der seine Tabelle
    verfehlt (falsche Spalte, Bedingung die nie greift), meldet sonst 0
    geloeschte Zeilen und sieht wie "war nichts da" aus.
    """
    reste: dict[str, int] = {}
    for name, tabelle in sorted(metadata.tables.items()):
        if name in plan.gemeinsam:
            continue
        for spalte in tabelle.columns:
            if spalte.name not in MANDANTEN_SPALTEN:
                continue
            uebrig = _zaehlen(db, name, f"{spalte.name} = :sub", sub)
            if uebrig:
                reste[f"{name}.{spalte.name}"] = uebrig
    return reste


def ausfuehren(db: Any, plan: Plan, metadata: Any, sub: str,
               trockenlauf: bool = False,
               dateien: Any = None) -> Bericht:
    """Den Plan abarbeiten und berichten.

    Alles in einer Transaktion: bricht ein Schritt, ist nichts geloescht. Ein
    halb geloeschtes Konto waere schlimmer als ein nicht geloeschtes, weil es
    danach keinen Zustand gibt, von dem aus man es nochmal versuchen kann.

    ``dateien`` ist eine Funktion ``(db, sub) -> [Path]``. Sie wird **vor** den
    Schritten gerufen (danach nennt keine Zeile mehr einen Pfad) und erst **nach**
    erfolgreichem Commit vollzogen: eine Datenbankzeile ohne ihre Datei ist ein
    Defekt, den niemand mehr reparieren kann, eine Datei ohne Zeile kostet Platz.
    """
    from sqlalchemy import text

    bericht = Bericht(dienst=plan.dienst, sub=sub, trockenlauf=trockenlauf)
    # Zwei Pruefungen, zwei Quellen: die Modelle und die Datenbank. Die erste
    # findet eine vergessene Modell-Tabelle ohne jede Daten, die zweite alles,
    # was per rohem SQL entstanden ist und in keinem Modell steht.
    bericht.luecken = abdeckung_pruefen(plan, metadata)
    bericht.luecken += ungedeckte_live_tabellen(plan, db, metadata)

    pfade = dateien(db, sub) if dateien is not None else []

    for schritt in plan.schritte:
        if trockenlauf:
            bericht.zeilen[schritt.tabelle] = _zaehlen(db, schritt.tabelle, schritt.wo, sub)
            continue
        ergebnis = db.execute(
            text(f"DELETE FROM {schritt.tabelle} WHERE {schritt.wo}"), {"sub": sub})
        bericht.zeilen[schritt.tabelle] = int(ergebnis.rowcount or 0)

    if trockenlauf:
        bericht.nebenwirkungen, bericht.dateifehler = dateien_entfernen(pfade, True)
        return bericht

    bericht.reste = _reste_suchen(db, plan, metadata, sub)
    if bericht.reste:
        db.rollback()
        bericht.nebenwirkungen = (
            [f"{len(pfade)} Pfad(e) unberuehrt gelassen, der Lauf wurde zurueckgerollt"]
            if pfade else [])
        return bericht

    db.commit()
    bericht.nebenwirkungen, bericht.dateifehler = dateien_entfernen(pfade, False)
    return bericht


def dateien_entfernen(pfade: Any, trockenlauf: bool) -> tuple[list[str], list[str]]:
    """Pfade aus einer Ablage entfernen. Gibt (Berichtszeilen, Fehler) zurueck.

    Ein fehlender Pfad ist kein Fehler: die Datenbank sagt, was es geben soll,
    und eine Datei, die schon weg ist, erfuellt genau den Zweck. Ein Fehlschlag
    beim Loeschen wird dagegen gemeldet und nicht verschluckt, sonst meldet der
    Lauf ein geloeschtes Konto, und die Inhalte liegen weiter auf der Platte.
    """
    import shutil

    zeilen: list[str] = []
    entfernt = fehlend = 0
    fehler: list[str] = []
    for pfad in pfade:
        if not pfad.exists():
            fehlend += 1
            continue
        if not trockenlauf:
            try:
                shutil.rmtree(pfad) if pfad.is_dir() else pfad.unlink()
            except OSError as problem:
                fehler.append(f"{pfad}: {problem}")
                continue
        entfernt += 1
    if entfernt:
        zeilen.append(f"{entfernt} Datei(en)/Ordner in der Ablage "
                      f"{'waeren zu loeschen' if trockenlauf else 'geloescht'}")
    if fehlend:
        zeilen.append(f"{fehlend} Pfad(e) lagen nicht mehr in der Ablage")
    return zeilen, fehler


def als_programm(plan: Plan, metadata: Any, sitzung_fabrik: Any,
                 dateien: Any = None, argumente: list[str] | None = None) -> int:
    """Der Betreiberweg. Rueckgabewert 0 nur, wenn der Lauf sauber war."""
    import argparse
    import json

    zerleger = argparse.ArgumentParser(
        prog=f"python -m app.konto  ({plan.dienst})",
        description="Den Bestand eines Mandanten anzeigen oder entfernen.")
    zerleger.add_argument("--sub", required=True, help="Mandant (sub aus der Anmeldung)")
    zerleger.add_argument("--loeschen", action="store_true",
                          help="wirklich loeschen. Ohne diesen Schalter nur anzeigen.")
    args = zerleger.parse_args(argumente)

    db = sitzung_fabrik()
    try:
        bericht = ausfuehren(db, plan, metadata, args.sub,
                            trockenlauf=not args.loeschen, dateien=dateien)
    finally:
        db.close()
    print(json.dumps(bericht.als_dict(), indent=2, ensure_ascii=False))
    return 0 if bericht.sauber else 1
