"""Shopping service: generates shopping lists from planned meals + stock rules.

Uses LagerAdapter for inventory availability instead of local StockBatch.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import DomainError
from app.models import (
    Ingredient,
    MealSlot,
    RecipeIngredient,
    ShoppingList,
    ShoppingListLine,
    ShoppingRule,
)
from app.schemas import StrategicInfo
from app.services.lager_adapter import LagerAdapter, LagerUnavailable

log = logging.getLogger(__name__)

#: Grund fuer Zeilen, die aus lagers eigener Vorschlagsrechnung stammen
#: (Mindestbestand, Wochenverbrauch, baldiges Ablaufdatum) und nicht aus einem
#: geplanten Rezept. Das ist Wissen, das nur lager hat: es kennt den Verbrauch
#: auch dann, wenn diese Woche kein Gericht die Zutat anfordert.
REASON_LAGER = "LAGER_VORSCHLAG"

# Keep only the newest N closed shopping lists per owner. Closed lists are never
# read back (get_current() returns only the open list), so without this they
# accumulate unbounded: auto_refresh() creates one on every plan mutation.
CLOSED_LIST_KEEP = max(int(os.environ.get("SHOPPING_LIST_CLOSED_KEEP", "30")), 0)


class ShoppingService:
    def __init__(self, db: Session, lager: LagerAdapter | None = None):
        self.db = db
        self.lager = lager or LagerAdapter()

    def generate_for_window(
        self, date_from: date, days_ahead: int = 3
    ) -> ShoppingList:
        """Neue Einkaufsliste erzeugen. Es gibt immer genau EINE offene.

        ★ Diese Methode liess die alte offene Liste frueher stehen, und danach
        war die Einkaufsliste tot: `get_current()` erwartet hoechstens eine
        offene und warf `MultipleResultsFound`, also lieferten `/shopping/current`
        und die Ansicht darunter 500. Zweimal „erzeugen" genuegte, und die App
        selbst war die einzige Quelle des Zustands. `auto_refresh()` machte es
        von Anfang an richtig; der Unterschied zwischen beiden Wegen war kein
        Entwurf, sondern ein Versehen - deshalb geht es jetzt durch dieselbe
        Stelle, statt das Schliessen ein zweites Mal hinzuschreiben.
        """
        return self.auto_refresh(date_from, days_ahead)

    def _generate_no_commit(
        self, date_from: date, days_ahead: int = 3
    ) -> ShoppingList:
        """Build a new ShoppingList and flush (but don't commit).

        ★★ Der Bestand wird **einmal** geholt und dann aus dem Schnappschuss
        beantwortet. Vorher rief diese Methode einmal je Zutat an, und bei 47
        Zutaten lief sie damit in lagers Deckel von 60 Anfragen je Minute.
        Die abgewiesenen Aufrufe kamen als 429 zurueck, ``get_available``
        machte daraus eine 0, und die Liste entstand aus lauter Nullen: alles
        zu kaufen, nichts vorhanden. Sie sah dabei voellig unauffaellig aus.

        Laesst sich der Bestand nicht messen, wird **keine** Liste gebaut.
        Eine Liste aus unbekanntem Bestand ist schlechter als keine: sie
        sieht aus wie eine Auskunft.
        """
        if self.lager.available and not self.lager.schnappschuss_laden(erneuern=True):
            raise LagerUnavailable(
                "Bestand nicht messbar. Eine Einkaufsliste aus unbekanntem "
                "Bestand waere eine Behauptung, keine Auskunft."
            )
        date_to = date_from + timedelta(days=days_ahead)

        # 1) Gather requirements from planned meals
        planned_slots = list(
            self.db.execute(
                select(MealSlot).where(
                    MealSlot.date >= date_from,
                    MealSlot.date < date_to,
                    MealSlot.planned_recipe_id.isnot(None),
                    MealSlot.status != "eaten",
                )
            ).scalars().all()
        )

        required: dict[int, dict] = {}  # ingredient_id -> {amount, unit, reasons, lager_product_id}
        for slot in planned_slots:
            ri_rows = list(
                self.db.execute(
                    select(RecipeIngredient).where(
                        RecipeIngredient.recipe_id == slot.planned_recipe_id
                    )
                ).scalars().all()
            )
            for ri in ri_rows:
                if ri.optional_bool:
                    continue
                ing = self.db.get(Ingredient, ri.ingredient_id)
                entry = required.setdefault(ri.ingredient_id, {
                    "amount": 0.0, "unit": ri.unit, "reasons": set(),
                    "lager_product_id": ing.lager_product_id if ing else None,
                })
                entry["amount"] += ri.amount
                entry["reasons"].add("MISSING_FOR_PLAN")

        # 2) Check shopping rules for min stock
        #
        # ★ Hier stand `entry["amount"] = max(entry["amount"], target - avail)`,
        # und Stufe 3 zog den Bestand danach ein ZWEITES Mal ab. Fuer eine
        # Zeile, die nur aus dieser Regel kommt, ergab das `target - 2*avail`:
        # je mehr man im Vorrat hatte, desto weiter unter dem Mindestbestand
        # landete man nach dem Einkauf. Aufgefallen ist es nie, weil bis zum
        # 2026-09-13 keine einzige Zutat mit dem Lager verknuepft war und
        # `avail` deshalb ueberall 0 lieferte. `required` fuehrt jetzt
        # durchweg den ROHEN Bedarf, abgezogen wird genau einmal in Stufe 3.
        rules = list(self.db.execute(select(ShoppingRule)).scalars().all())
        for rule in rules:
            ing = self.db.get(Ingredient, rule.ingredient_id)
            lager_pid = ing.lager_product_id if ing else None
            avail = self._get_available_from_lager(lager_pid, rule.unit)
            if avail < rule.min_stock:
                target = rule.target_stock or rule.min_stock
                entry = required.setdefault(rule.ingredient_id, {
                    "amount": 0.0, "unit": rule.unit, "reasons": set(),
                    "lager_product_id": lager_pid,
                })
                entry["amount"] = max(entry["amount"], target)
                entry["reasons"].add("BELOW_MIN_STOCK")

        # 3) Subtract available stock (from Lager)
        lines_data: list[dict] = []
        already_listed: set[int] = set()
        for ing_id, req in required.items():
            avail = self._get_available_from_lager(req.get("lager_product_id"), req["unit"])
            needed = req["amount"] - avail
            if needed <= 0.001:
                continue
            ingredient = self.db.get(Ingredient, ing_id)
            packs = self._suggest_packs(ingredient, needed) if ingredient else []
            lines_data.append({
                "ingredient_id": ing_id,
                "needed_amount": round(needed, 1),
                # Der rohe Bedarf reist mit, damit das Anzeigen ihn genau
                # einmal gegen den dann aktuellen Bestand halten kann.
                "bedarf_brutto": round(req["amount"], 1),
                "unit": req["unit"],
                "suggested_packs": packs,
                "reason_codes": sorted(req["reasons"]),
            })
            already_listed.add(ing_id)

        # 4) Min-stock runway: ensure enough stock for MIN_STOCK_RUNWAY_DAYS
        #    after all planned meals are cooked
        if days_ahead > 0:
            for ing_id, req in required.items():
                if ing_id in already_listed:
                    continue  # already on the list from Stage 3
                avail = self._get_available_from_lager(req.get("lager_product_id"), req["unit"])
                remaining_after_plan = avail - req["amount"]
                if remaining_after_plan < 0:
                    continue  # handled by Stage 3
                avg_daily = req["amount"] / days_ahead
                if avg_daily <= 0:
                    continue
                runway = remaining_after_plan / avg_daily
                if runway < settings.MIN_STOCK_RUNWAY_DAYS:
                    target = settings.MIN_STOCK_RUNWAY_DAYS * avg_daily
                    deficit = target - remaining_after_plan
                    if deficit > 0.001:
                        ingredient = self.db.get(Ingredient, ing_id)
                        packs = self._suggest_packs(ingredient, deficit) if ingredient else []
                        lines_data.append({
                            "ingredient_id": ing_id,
                            "needed_amount": round(deficit, 1),
                            # Roh heisst hier: was der Plan braucht PLUS der
                            # Vorlauf danach. Gegen den Bestand gehalten
                            # ergibt das wieder genau dieses Defizit.
                            "bedarf_brutto": round(req["amount"] + target, 1),
                            "unit": req["unit"],
                            "suggested_packs": packs,
                            "reason_codes": ["LOW_RUNWAY"],
                        })

        # 5) Lagers eigene Vorschlaege (Mindestbestand / Wochenverbrauch /
        #    baldiges Ablaufdatum). Das ist die Quelle, die mealprep bis
        #    2026-09-13 nicht gelesen hat: lager sieht Bedarf auch dann, wenn
        #    diese Woche kein geplantes Gericht die Zutat anfordert.
        #    Nur zuordenbare Vorschlaege zaehlen; was keiner Zutat entspricht,
        #    bleibt lagers Seite ueberlassen, statt hier eine Zeile ohne
        #    Rezeptbezug zu erfinden.
        schon_gelistet = {ld["ingredient_id"] for ld in lines_data}
        for ld in self._lager_vorschlaege(ausgenommen=schon_gelistet):
            lines_data.append(ld)

        # 6) Persist (flush only, caller decides when to commit)
        sl = ShoppingList(status="open")
        self.db.add(sl)
        self.db.flush()

        for ld in lines_data:
            line = ShoppingListLine(
                shopping_list_id=sl.id,
                ingredient_id=ld["ingredient_id"],
                needed_amount=ld["needed_amount"],
                bedarf_brutto=ld.get("bedarf_brutto"),
                unit=ld["unit"],
            )
            line.suggested_packs = ld["suggested_packs"]
            line.reason_codes = ld["reason_codes"]
            self.db.add(line)

        self.db.flush()
        return sl

    def _lager_vorschlaege(self, ausgenommen: set[int]) -> list[dict]:
        """Lagers Vorschlaege in Zeilen uebersetzen, soweit zuordenbar."""
        vorschlaege = self.lager.get_suggestions()
        if not vorschlaege:
            return []

        # Rueckwaerts: Lager-Produkt -> Zutat. Nur verknuepfte Zutaten koennen
        # getroffen werden, unverknuepfte sind hier strukturell unsichtbar.
        nach_produkt: dict[int, Ingredient] = {}
        for zutat in self.db.execute(
            select(Ingredient).where(Ingredient.lager_product_id.is_not(None))
        ).scalars().all():
            nach_produkt.setdefault(zutat.lager_product_id, zutat)

        gefunden: list[dict] = []
        for v in vorschlaege:
            try:
                pid = int(v["product_id"])
                menge = float(v.get("suggested_quantity") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            zutat = nach_produkt.get(pid)
            if zutat is None or zutat.id in ausgenommen or menge <= 0.001:
                continue
            einheit = str(v.get("unit") or zutat.default_unit)
            gefunden.append({
                "ingredient_id": zutat.id,
                "needed_amount": round(menge, 1),
                # ★ Bewusst None: lagers Zahl entsteht aus Mindestbestand,
                # Wochenverbrauch und Ablaufdatum. Sie noch einmal gegen den
                # Bestand zu halten hiesse, eine Rechnung zu wiederholen,
                # deren Eingangsdaten mealprep gar nicht hat, und ergaebe fuer
                # den Fall "laeuft bald ab" immer null: abgezogen wuerde
                # genau der Vorrat, dessen Verlust der Vorschlag ersetzt.
                "bedarf_brutto": None,
                "unit": einheit,
                "suggested_packs": self._suggest_packs(zutat, menge),
                "reason_codes": [REASON_LAGER],
            })
            ausgenommen.add(zutat.id)
        return gefunden

    def auto_refresh(self, date_from: date | None = None, days_ahead: int = 3) -> ShoppingList:
        """Close all open lists and regenerate from current plan + stock rules.

        Uses a single transaction: generate new list first, then close old ones,
        then commit together. If generation fails, old lists remain open.
        """
        date_from = date_from or date.today()

        # Collect IDs of currently open lists before generating
        old_ids = [
            sl.id for sl in self.db.execute(
                select(ShoppingList).where(ShoppingList.status == "open")
            ).scalars().all()
        ]

        # Generate new list (flush only, no commit). Scheitert das Messen des
        # Bestands, bleibt die alte Liste offen stehen: sie ist veraltet, aber
        # sie ist wenigstens einmal aus echten Zahlen entstanden.
        try:
            sl = self._generate_no_commit(date_from, days_ahead)
        finally:
            self.lager.schnappschuss_verwerfen()

        # Close old lists (the new one has a different id)
        for old_id in old_ids:
            old = self.db.get(ShoppingList, old_id)
            if old:
                old.status = "closed"

        self._prune_closed_lists()
        self.db.commit()
        return sl

    def _prune_closed_lists(self, keep: int = CLOSED_LIST_KEEP) -> int:
        """Delete closed shopping lists beyond the newest ``keep`` per owner.

        Bounds unbounded growth: auto_refresh() closes+regenerates a list on every
        plan mutation, but closed lists are never read again. Children first (no
        ON DELETE CASCADE). A window subquery drives both deletes so it stays
        SQL-param-limit-safe for any backlog size. Runs in the caller's
        transaction (no commit here); steady state removes at most one list.
        """
        keep = max(keep, 0)
        doomed = (
            "SELECT id FROM (SELECT id, ROW_NUMBER() OVER "
            "(PARTITION BY owner_sub ORDER BY created_at DESC, id DESC) AS rn "
            "FROM shopping_list WHERE status = 'closed') WHERE rn > :keep"
        )
        self.db.execute(
            text(f"DELETE FROM shopping_list_line WHERE shopping_list_id IN ({doomed})"),
            {"keep": keep},
        )
        res = self.db.execute(
            text(f"DELETE FROM shopping_list WHERE id IN ({doomed})"),
            {"keep": keep},
        )
        n = res.rowcount or 0
        if n:
            log.info("pruned %d closed shopping lists (keep=%d per owner)", n, keep)
        return n

    def get_current(self) -> ShoppingList | None:
        """Die aktuelle Liste, auch wenn versehentlich mehrere offen sind.

        ★ Hier stand `scalar_one_or_none()`, und das ist eine Behauptung ueber
        die Daten, keine Frage an sie: sobald zwei offene Listen existierten,
        warf der Lesepfad und die Einkaufsliste war fuer den Nutzer weg (500,
        nicht etwa eine Liste zu viel). Ein Anzeigeweg darf an einem Zustand,
        den er vorfindet, nicht sterben - er nimmt die neueste, wofuer die
        Sortierung ohnehin schon da war. Dass es nur eine geben SOLL, ist die
        Aufgabe der schreibenden Seite (`auto_refresh`), und dort steht sie.
        """
        return self.db.execute(
            select(ShoppingList)
            .where(ShoppingList.status == "open")
            .order_by(ShoppingList.created_at.desc(), ShoppingList.id.desc())
        ).scalars().first()

    # ----- Abhaken und Restbedarf -----

    def zeilen_mit_restbedarf(self, sl: ShoppingList) -> list[dict]:
        """Zeilen der Liste, gegen den AKTUELLEN Bestand nachgerechnet.

        ★ Warum beim Abruf und nicht beim Erzeugen: ``generate_for_window``
        rechnet ``noetig = Bedarf - verfuegbar`` und **speichert** das
        Ergebnis. Der Bestandsabzug ist damit eine Momentaufnahme vom
        Erzeugungszeitpunkt. Wer danach von Hand in lager einbucht, sieht die
        Liste unveraendert und kauft, was schon da ist.

        Der Gegenvorschlag war, bei jeder Bestandsaenderung ``auto_refresh``
        auszuloesen. Das ist billiger, haengt aber daran, dass kein Ereignis
        verloren geht - und lager schickt hierher keine Ereignisse. Nachrechnen
        beim Abruf kann kein Ereignis verpassen, weil es keines braucht.

        ★★ Abgezogen wird **genau einmal**, naemlich hier, und deshalb vom
        ROHEN Bedarf (``bedarf_brutto``). Der erste Anlauf am 2026-09-13 zog
        vom bereits abgezogenen ``needed_amount`` noch einmal ab; live
        standen danach elf von dreiundzwanzig Zeilen auf "0 noch noetig",
        obwohl sie auf der Liste standen. Zwei Abzuege desselben Vorrats
        sehen aus wie ein gut gefuellter Vorrat.

        ``bedarf_brutto is None`` heisst ausdruecklich "nicht nachrechnen":
        die Zahl stammt aus lagers eigener Rechnung und wird uebernommen.

        Die gespeicherte Zeile bleibt die Absicht (``geplant``), der
        nachgerechnete Wert ist die Lage (``noch_noetig``).

        ⚠️ ``bestand_unbekannt`` ist nicht dasselbe wie "nichts da": faellt
        lager aus, wird NICHT auf null gerechnet, sondern der geplante Wert
        gezeigt und die Unsicherheit benannt.
        """
        bestand = self.lager.bestand_gesamt()
        nicht_gemessen = bestand is None
        # Innerhalb einer Liste kann dieselbe Zutat nur einmal vorkommen, aber
        # der Vorrat wird ueber alle Zeilen desselben Produkts geteilt.
        verbraucht: dict[tuple[int, str], float] = {}

        zeilen: list[dict] = []
        for line in sorted(sl.lines, key=lambda x: x.id):
            zutat = self.db.get(Ingredient, line.ingredient_id)
            pid = zutat.lager_product_id if zutat else None
            schluessel = (pid, line.unit) if pid else None

            brutto = line.bedarf_brutto
            if line.gekauft_am is not None:
                noch_noetig = 0.0
                unbekannt = False
            elif brutto is None or schluessel is None or nicht_gemessen:
                # Drei verschiedene Gruende, denselben Wert zu zeigen:
                # lagers eigene Zahl wird nicht nachgerechnet, eine nicht
                # verknuepfte Zutat hat keinen Bestand zum Gegenrechnen, und
                # ein ausgefallenes Lager ist keine Messung. Nur der letzte
                # Fall ist eine Unsicherheit.
                noch_noetig = line.needed_amount
                unbekannt = nicht_gemessen and schluessel is not None and brutto is not None
            else:
                frei = bestand.get(schluessel, 0.0) - verbraucht.get(schluessel, 0.0)
                genommen = max(0.0, min(frei, brutto))
                verbraucht[schluessel] = verbraucht.get(schluessel, 0.0) + genommen
                noch_noetig = max(0.0, brutto - genommen)
                unbekannt = False

            zeilen.append({
                "id": line.id,
                "ingredient_id": line.ingredient_id,
                "ingredient_name": zutat.name_canonical if zutat else "",
                "geplant": round(line.needed_amount, 1),
                "bedarf_brutto": round(brutto, 1) if brutto is not None else None,
                "noch_noetig": round(noch_noetig, 1),
                "unit": line.unit,
                "suggested_packs": line.suggested_packs,
                "reason_codes": line.reason_codes,
                "gekauft_am": line.gekauft_am,
                "gekaufte_menge": line.gekaufte_menge,
                "verknuepft": pid is not None,
                "bestand_unbekannt": unbekannt,
            })
        return zeilen

    def abhaken(
        self,
        line_id: int,
        menge: float | None = None,
        mhd: str | None = None,
        ort: str | None = None,
    ) -> ShoppingListLine:
        """Eine Zeile als gekauft markieren und in den Bestand buchen.

        Das ist die Stelle, an der sich der Kreis schliesst: bis hierher
        buchte mealprep beim Kochen ab und nie wieder auf.

        Fehlt die Verknuepfung zur Lager-Seite, wird **nicht** stillschweigend
        nur der Haken gesetzt. Ein Haken ohne Buchung saehe aus wie ein
        geschlossener Kreis und waere keiner.
        """
        line = self.db.get(ShoppingListLine, line_id)
        if line is None:
            raise DomainError("Einkaufszeile nicht gefunden", {"line_id": line_id})
        if line.gekauft_am is not None:
            raise DomainError(
                "Zeile ist bereits abgehakt",
                {"line_id": line_id, "gekauft_am": line.gekauft_am.isoformat()},
            )

        zutat = self.db.get(Ingredient, line.ingredient_id)
        if zutat is None or not zutat.lager_product_id:
            raise DomainError(
                "Zutat ist nicht mit einem Lager-Produkt verknuepft. "
                "Ohne diese Verbindung gibt es keinen Bestand, in den gebucht "
                "werden koennte.",
                {
                    "line_id": line_id,
                    "ingredient_id": line.ingredient_id,
                    "ingredient_name": zutat.name_canonical if zutat else "",
                    "hinweis": "GET /inventory/lager-abgleich schlaegt Paare vor",
                },
            )

        gekauft = line.needed_amount if menge is None else float(menge)
        if gekauft <= 0:
            raise DomainError(
                "Gekaufte Menge muss groesser als null sein",
                {"line_id": line_id, "menge": gekauft},
            )

        eintrag = self.lager.einbuchen(
            product_id=zutat.lager_product_id,
            menge=gekauft,
            unit=line.unit,
            mhd=mhd,
            ort=ort,
            notiz=f"Einkaufsliste #{line.shopping_list_id}",
        )

        line.gekauft_am = datetime.now()
        line.gekaufte_menge = round(gekauft, 2)
        line.lager_stock_entry_id = eintrag.get("id") if isinstance(eintrag, dict) else None
        self.db.commit()
        self.db.refresh(line)
        return line

    def haken_zuruecknehmen(self, line_id: int) -> ShoppingListLine:
        """Einen Haken zuruecknehmen und den erzeugten Bestandseintrag loeschen.

        Entfernt wird genau der gemerkte Eintrag, nichts Gesuchtes. Ist er im
        Lager schon weg (von Hand geloescht, verbraucht), gilt der Haken
        trotzdem als zurueckgenommen: der Zustand, den diese Zeile
        beschreiben soll, ist dann ohnehin nicht mehr ihrer.
        """
        line = self.db.get(ShoppingListLine, line_id)
        if line is None:
            raise DomainError("Einkaufszeile nicht gefunden", {"line_id": line_id})
        if line.gekauft_am is None:
            raise DomainError("Zeile ist nicht abgehakt", {"line_id": line_id})

        if line.lager_stock_entry_id:
            self.lager.einbuchung_zuruecknehmen(line.lager_stock_entry_id)

        line.gekauft_am = None
        line.gekaufte_menge = None
        line.lager_stock_entry_id = None
        self.db.commit()
        self.db.refresh(line)
        return line

    def compute_strategic_info(
        self, date_from: date, days_ahead: int = 3
    ) -> dict[int, StrategicInfo]:
        """Compute strategic shopping info per ingredient_id.

        Returns dict mapping ingredient_id -> StrategicInfo.
        """
        date_to = date_from + timedelta(days=days_ahead)

        # Gather planned slots in window
        planned_slots = list(
            self.db.execute(
                select(MealSlot).where(
                    MealSlot.date >= date_from,
                    MealSlot.date < date_to,
                    MealSlot.planned_recipe_id.isnot(None),
                    MealSlot.status != "eaten",
                )
            ).scalars().all()
        )

        # Count meals per ingredient and sum daily usage
        ing_meals: dict[int, int] = {}  # ingredient_id -> count of meals
        ing_total: dict[int, float] = {}  # ingredient_id -> total amount needed
        ing_unit: dict[int, str] = {}

        for slot in planned_slots:
            ri_rows = list(
                self.db.execute(
                    select(RecipeIngredient).where(
                        RecipeIngredient.recipe_id == slot.planned_recipe_id
                    )
                ).scalars().all()
            )
            for ri in ri_rows:
                if ri.optional_bool:
                    continue
                ing_meals[ri.ingredient_id] = ing_meals.get(ri.ingredient_id, 0) + 1
                ing_total[ri.ingredient_id] = ing_total.get(ri.ingredient_id, 0) + ri.amount
                ing_unit[ri.ingredient_id] = ri.unit

        result: dict[int, StrategicInfo] = {}
        for ing_id, total_amount in ing_total.items():
            meals_count = ing_meals.get(ing_id, 0)
            daily_avg = total_amount / max(days_ahead, 1)

            # Determine primary nutrient
            ing = self.db.get(Ingredient, ing_id)
            primary_nutrient = ""
            if ing and ing.nutrition_per_100:
                n = ing.nutrition_per_100
                nutrients = [
                    (n.get("protein_g", 0) if isinstance(n, dict) else 0, "Protein"),
                    (n.get("carbs_g", 0) if isinstance(n, dict) else 0, "Kohlenhydrate"),
                    (n.get("fat_g", 0) if isinstance(n, dict) else 0, "Fett"),
                ]
                nutrients.sort(key=lambda x: x[0], reverse=True)
                if nutrients[0][0] > 0:
                    primary_nutrient = nutrients[0][1]

            # Impact days: how many days this amount covers
            impact_days = total_amount / daily_avg if daily_avg > 0 else 0

            # Efficiency hint
            name = ing.name_canonical if ing else f"#{ing_id}"
            unit = ing_unit.get(ing_id, "g")
            hint = ""
            if primary_nutrient and impact_days >= 2:
                hint = f"Mit {total_amount:.0f}{unit} {name} deckst du {impact_days:.0f} Tage {primary_nutrient}bedarf"
            elif meals_count > 1:
                hint = f"Fuer {meals_count} geplante Mahlzeiten benoetigt"

            result[ing_id] = StrategicInfo(
                impact_days=round(impact_days, 1),
                impact_meals=meals_count,
                primary_nutrient=primary_nutrient,
                efficiency_hint=hint,
            )

        return result

    def get_weekly_shopping_list(
        self, start_date: date, days: int = 7
    ) -> list[dict]:
        """Aggregate all ingredients needed across planned meals for a date range.

        Groups by ingredient, sums quantities, checks Lager stock,
        and returns a list of items with: ingredient_name, total_needed,
        unit, in_stock, to_buy.

        ★ Der Bestand kommt aus einem Schnappschuss, nicht aus einem Aufruf
        je Zutat: dieselbe Schleife, die beim Erzeugen der Einkaufsliste in
        lagers Anfragedeckel lief (429 je Aufruf, stillschweigend als 0
        gelesen). Anders als dort ist eine unvollstaendige Wochenuebersicht
        keine Katastrophe, deshalb wird hier nicht abgebrochen, sondern
        weitergerechnet wie bisher.
        """
        self.lager.schnappschuss_laden()
        date_to = start_date + timedelta(days=days)

        # Gather planned slots in the range
        planned_slots = list(
            self.db.execute(
                select(MealSlot).where(
                    MealSlot.date >= start_date,
                    MealSlot.date < date_to,
                    MealSlot.planned_recipe_id.isnot(None),
                    MealSlot.status != "eaten",
                )
            ).scalars().all()
        )

        # Aggregate ingredient requirements
        required: dict[int, dict] = {}
        for slot in planned_slots:
            ri_rows = list(
                self.db.execute(
                    select(RecipeIngredient).where(
                        RecipeIngredient.recipe_id == slot.planned_recipe_id
                    )
                ).scalars().all()
            )
            for ri in ri_rows:
                if ri.optional_bool:
                    continue
                ing = self.db.get(Ingredient, ri.ingredient_id)
                entry = required.setdefault(ri.ingredient_id, {
                    "amount": 0.0,
                    "unit": ri.unit,
                    "lager_product_id": ing.lager_product_id if ing else None,
                    "name": ing.name_canonical if ing else f"#{ri.ingredient_id}",
                    "category": ing.category if ing else None,
                })
                entry["amount"] += ri.amount

        # Build result with stock comparison
        result: list[dict] = []
        for ing_id, req in required.items():
            in_stock = self._get_available_from_lager(
                req.get("lager_product_id"), req["unit"]
            )
            to_buy = max(0.0, req["amount"] - in_stock)
            result.append({
                "ingredient_id": ing_id,
                "ingredient_name": req["name"],
                "category": req.get("category") or "",
                "total_needed": round(req["amount"], 1),
                "unit": req["unit"],
                "in_stock": round(in_stock, 1),
                "to_buy": round(to_buy, 1),
            })

        # Sort: items to buy first, then alphabetically
        result.sort(key=lambda x: (-x["to_buy"], x["ingredient_name"]))
        self.lager.schnappschuss_verwerfen()
        return result

    # ----- internal -----

    def _get_available_from_lager(self, lager_product_id: int | None, unit: str) -> float:
        if not lager_product_id:
            return 0.0
        return self.lager.get_available(lager_product_id, unit)

    @staticmethod
    def _suggest_packs(ingredient: Ingredient, needed: float) -> list[int]:
        sizes = ingredient.typical_pack_sizes
        if not sizes:
            return []
        sizes_sorted = sorted(sizes, reverse=True)
        packs: list[int] = []
        remaining = needed
        for size in sizes_sorted:
            while remaining >= size - 0.001:  # FIXED: prevent infinite loop
                packs.append(size)
                remaining -= size
        if remaining > 0.001 and sizes_sorted:
            packs.append(sizes_sorted[-1])
        return packs
