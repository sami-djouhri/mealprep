#!/usr/bin/env python3
"""Holt die Schrift dieses Dienstes einmalig als WOFF2 und legt sie lokal ab.

MealPrep laeuft LAN-intern und soll ohne Internet funktionieren. Die Schrift
darf deshalb NICHT zur Laufzeit vom Google-CDN nachgeladen werden:

  - Der Abruf uebertraegt die IP jedes Aufrufers an einen Dritten ohne
    Einwilligung (LG Muenchen I, 20.01.2022, 3 O 17493/20).
  - Er bricht die Offline-Faehigkeit, die am 2026-09-26 zur Hausregel wurde.
  - Er blockiert das Rendern, bis er in einen Zeitfehler laeuft.

Dieses Werkzeug laeuft einmal auf einem Rechner mit Netz, danach liegen die
Dateien in app/static/schriften/ und das erzeugte schriften.css bindet sie mit
relativen Pfaden ein.

Es gibt bewusst KEIN geteiltes Hausschrift-Paket: jedes Projekt soll fuer sich
veroeffentlichbar bleiben. Dieselbe Datei liegt deshalb auch in `wissen`, mit
einer anderen Schriftliste.

Nur die Zeichensaetze latin und latin-ext werden behalten: latin traegt die
deutschen Umlaute, latin-ext die Zeichen, ueber die Zutaten- und Rezeptnamen
aus dem Nachbarland stolpern.

Aufruf:  python3 werkzeug/schriften-holen.py
"""
import pathlib
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
ZIEL = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "schriften"

# Eine Familie, variabel. Die Erkennbarkeit dieses Dienstes kommt aus seiner
# Farbe und seinen weichen Glasflaechen, nicht aus einer zweiten Schrift: eine
# Anzeigeschrift daneben haette Gewicht ohne Aussage hinzugefuegt. Outfit ist
# geometrisch und passt zu den runden Formen; ihre Ziffern stehen aufrecht und
# gleich breit, und genau darauf kommt es hier an - kcal, Gramm und Prozente
# werden den ganzen Tag ueber miteinander verglichen.
SCHRIFTEN = [
    ("Outfit", "Outfit:wght@300..700"),
]

BEHALTEN = {"latin", "latin-ext"}


def hole(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read()


def datei_name(familie: str, kursiv: bool, gewicht: str, block: str) -> str:
    kurz = familie.lower().replace(" ", "-")
    g = gewicht.strip().replace(" ", "-")
    return f"{kurz}-{'kursiv' if kursiv else 'gerade'}-{g}-{block}.woff2"


def main() -> int:
    ZIEL.mkdir(parents=True, exist_ok=True)
    regeln: list[str] = []
    geholt = 0

    for familie, anfrage in SCHRIFTEN:
        url = f"https://fonts.googleapis.com/css2?family={anfrage}&display=swap"
        try:
            css = hole(url).decode()
        except Exception as e:  # noqa: BLE001 - Werkzeug, Abbruch mit Klartext reicht
            print(f"FEHLER {familie}: {e}", file=sys.stderr)
            return 1

        for block_name, face in re.findall(r"/\* (\S+) \*/\s*(@font-face \{.*?\})", css, re.S):
            if block_name not in BEHALTEN:
                continue
            quelle = re.search(r"src: url\((\S+?)\) format", face)
            stil = re.search(r"font-style: (\S+?);", face)
            gewicht = re.search(r"font-weight: (.+?);", face)
            bereich = re.search(r"unicode-range: (.+?);", face)
            if not (quelle and stil and gewicht):
                continue

            kursiv = stil.group(1) == "italic"
            name = datei_name(familie, kursiv, gewicht.group(1), block_name)
            pfad = ZIEL / name
            if not pfad.exists():
                pfad.write_bytes(hole(quelle.group(1)))
                geholt += 1
                print(f"  {name}  {pfad.stat().st_size // 1024} KB")

            regel = [
                "@font-face {",
                f"  font-family: '{familie}';",
                f"  font-style: {stil.group(1)};",
                f"  font-weight: {gewicht.group(1)};",
                "  font-display: swap;",
                f"  src: url('schriften/{name}') format('woff2');",
            ]
            if bereich:
                regel.append(f"  unicode-range: {bereich.group(1)};")
            regel.append("}")
            regeln.append("\n".join(regel))

    kopf = (
        "/* Erzeugt von werkzeug/schriften-holen.py - nicht von Hand aendern.\n"
        "   Outfit steht unter der SIL Open Font License 1.1. */\n\n"
    )
    (ZIEL.parent / "schriften.css").write_text(kopf + "\n\n".join(regeln) + "\n")
    gesamt = sum(p.stat().st_size for p in ZIEL.glob("*.woff2"))
    print(f"\n{len(regeln)} Regeln, {geholt} neu geholt, {gesamt // 1024} KB gesamt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
