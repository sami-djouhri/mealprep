"""Profile service: BMR/TDEE/macro calculations based on UserProfile."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import BodyMetric, UserProfile
from app.schemas import DailyMacroTargets
from app.services.fitness_adapter import FitnessAdapter

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Activity multipliers (Harris-Benedict / standard TDEE factors)
# ---------------------------------------------------------------------------

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


class ProfileService:
    def __init__(self, db: Session):
        self.db = db

    # ----- CRUD -----

    def get_or_create(self) -> UserProfile:
        # Multi-Tenant: pro sub ein Profil; Query ist owner_sub-gescoped.
        profile = self.db.execute(
            select(UserProfile).order_by(UserProfile.id).limit(1)
        ).scalar_one_or_none()
        if profile is None:
            profile = UserProfile()
            self.db.add(profile)
            self.db.flush()
        return profile

    def update(self, data: dict) -> UserProfile:
        profile = self.get_or_create()
        for key, val in data.items():
            if hasattr(profile, key) and key != "id":
                setattr(profile, key, val)
        self.db.flush()
        return profile

    # ----- Body metrics -----

    def add_body_metric(
        self,
        weight_kg: float,
        metric_date: date | None = None,
        body_fat_pct: float | None = None,
        waist_cm: float | None = None,
    ) -> BodyMetric:
        bm = BodyMetric(
            date=metric_date or date.today(),
            weight_kg=weight_kg,
            body_fat_pct=body_fat_pct,
            waist_cm=waist_cm,
        )
        self.db.add(bm)
        self.db.flush()

        # Sync weight (and optionally KFA) to profile
        profile = self.get_or_create()
        profile.weight_kg = weight_kg
        if body_fat_pct is not None:
            profile.body_fat_pct = body_fat_pct
        if waist_cm is not None:
            profile.waist_cm = waist_cm
        self.db.flush()
        return bm

    def get_metrics(self, limit: int = 90) -> list[BodyMetric]:
        return list(
            self.db.execute(
                select(BodyMetric)
                .order_by(BodyMetric.date.desc())
                .limit(limit)
            ).scalars().all()
        )

    # ----- BMR calculation -----

    def calc_bmr(self, profile: UserProfile | None = None) -> float:
        """Calculate Basal Metabolic Rate.

        Uses Katch-McArdle if body_fat_pct is available, otherwise Mifflin-St Jeor.
        """
        p = profile or self.get_or_create()

        if p.body_fat_pct is not None and p.body_fat_pct > 0:
            # Katch-McArdle
            lbm = p.weight_kg * (1 - p.body_fat_pct / 100)
            bmr = 370 + 21.6 * lbm
        else:
            # Mifflin-St Jeor (requires age)
            age = self._calc_age(p.birth_date) if p.birth_date else 30  # default age
            if p.sex == "female":
                bmr = 10 * p.weight_kg + 6.25 * p.height_cm - 5 * age - 161
            else:
                bmr = 10 * p.weight_kg + 6.25 * p.height_cm - 5 * age + 5

        # Never return a negative or unrealistically low BMR
        return max(bmr, 500.0)

    def calc_tdee(self, profile: UserProfile | None = None) -> float:
        """TDEE = BMR * activity multiplier."""
        p = profile or self.get_or_create()
        bmr = self.calc_bmr(p)
        mult = ACTIVITY_MULTIPLIERS.get(p.activity_level, 1.55)
        return bmr * mult

    # ----- Macro targets -----

    def derive_daily_targets(self, profile: UserProfile | None = None) -> DailyMacroTargets:
        """Compute daily macro targets based on profile, goal, and TDEE."""
        p = profile or self.get_or_create()
        tdee = self.calc_tdee(p)

        # Determine goal from target_weight_kg vs current weight
        if p.kcal_target_override:
            kcal = float(p.kcal_target_override)
        elif p.target_weight_kg is not None and p.target_weight_kg < p.weight_kg - 1:
            # Abnehmen
            kcal = tdee - 500
        elif p.target_weight_kg is not None and p.target_weight_kg > p.weight_kg + 1:
            # Aufbauen
            kcal = tdee + 300
        else:
            # Halten
            kcal = tdee

        # Determine protein/fat g/kg based on goal direction
        if p.target_weight_kg is not None and p.target_weight_kg < p.weight_kg - 1:
            protein_per_kg = 2.2  # mid of 2.0-2.4
            fat_per_kg = 0.9     # mid of 0.8-1.0
        elif p.target_weight_kg is not None and p.target_weight_kg > p.weight_kg + 1:
            protein_per_kg = 2.0  # mid of 1.8-2.2
            fat_per_kg = 0.8
        else:
            protein_per_kg = 1.8  # mid of 1.6-2.0
            fat_per_kg = 0.8

        protein_g = p.weight_kg * protein_per_kg
        fat_g = p.weight_kg * fat_per_kg

        # Carbs fill remaining kcal
        protein_kcal = protein_g * 4
        fat_kcal = fat_g * 9
        remaining_kcal = max(0, kcal - protein_kcal - fat_kcal)
        carbs_g = remaining_kcal / 4

        fiber_g = 30.0  # general recommendation

        return DailyMacroTargets(
            kcal=round(kcal, 1),
            protein_g=round(protein_g, 1),
            carbs_g=round(carbs_g, 1),
            fat_g=round(fat_g, 1),
            fiber_g=fiber_g,
        )

    # ----- Tagesbezogene Ziele -----

    def tagesziele(
        self,
        tag: date,
        profile: UserProfile | None = None,
        fitness: FitnessAdapter | None = None,
    ) -> tuple[DailyMacroTargets, dict]:
        """Tagesziele fuer einen konkreten Tag, plus Begruendung.

        ★★ **Verschoben, nicht draufgerechnet.** Der Aktivitaetsfaktor im
        TDEE (``ACTIVITY_MULTIPLIERS``) bildet das Training bereits ab; er
        kommt seit dem 2026-09-12 aus der echten Trainingshaeufigkeit. Ein
        Aufschlag am Trainingstag wuerde dasselbe Training ein zweites Mal
        zaehlen. Stattdessen wandert ein Anteil ``p`` vom Ruhetag auf den
        Trainingstag, so dass die Wochensumme unveraendert bleibt::

            Trainingstag = Basis x (1 + p)
            Ruhetag      = Basis x (1 - p x t / (7 - t))

        bei ``t`` Trainingstagen je Woche. Protein und Fett haengen am
        Koerpergewicht und bleiben, die Kohlenhydrate tragen den Unterschied
        - das ist auch die Naehrstoffgruppe, um die es am Trainingstag geht.

        ⚠️ **Bei duenner Grundlage passiert nichts.** Verschoben wird nur,
        wenn fitness antwortet, selbst ``belastbar`` meldet und ``t``
        zwischen 1 und 6 liegt. Sonst bleibt es beim statischen Ziel, und der
        Grund steht im zweiten Rueckgabewert, nicht bloss im Protokoll. Ein
        frisch eingerichtetes System darf den Bedarf eines Menschen, der
        weiter trainiert, nicht nach unten schieben.
        """
        p = profile or self.get_or_create()
        basis = self.derive_daily_targets(p)
        grund: dict = {
            "datum": tag.isoformat(),
            "verschoben": False,
            "trainingstag": None,
            "anteil": 0.0,
        }

        anteil = float(settings.TRAININGSTAG_ANTEIL or 0.0)
        if anteil <= 0:
            grund["grund"] = "Tagesunterscheidung ist abgeschaltet (TRAININGSTAG_ANTEIL=0)"
            return basis, grund

        adapter = fitness or FitnessAdapter()
        niveau = adapter.aktivitaetsniveau()
        if niveau is None:
            grund["grund"] = "Fitness antwortet nicht. Es bleibt beim statischen Ziel."
            return basis, grund
        if not niveau.get("belastbar"):
            grund["grund"] = niveau.get("begruendung") or (
                "Fitness meldet die Trainingshaeufigkeit noch nicht als belastbar."
            )
            return basis, grund

        try:
            t = float(niveau.get("trainings_pro_woche") or 0.0)
        except (TypeError, ValueError):
            t = 0.0
        if not (1.0 <= t <= 6.0):
            # Bei 0 gibt es keinen Trainingstag, bei 7 keinen Ruhetag, auf den
            # verschoben werden koennte. In beiden Faellen ist die Rechnung
            # nicht definiert, statt sie zu deckeln.
            grund["grund"] = (
                f"{t:.1f} Trainings je Woche. Verschoben wird nur zwischen 1 und 6, "
                "sonst gibt es keine Gegenseite."
            )
            return basis, grund

        tagesinfo = adapter.ist_trainingstag(tag)
        if not tagesinfo.get("erreichbar"):
            grund["grund"] = "Fitness antwortet nicht. Es bleibt beim statischen Ziel."
            return basis, grund

        ist_training = bool(tagesinfo.get("training"))
        faktor = (1 + anteil) if ist_training else (1 - anteil * t / (7.0 - t))
        # Ein Ruhetag darf nie unter den Grundumsatz fallen. Bei sechs
        # Trainingstagen und grossem Anteil waere das sonst rechnerisch
        # moeglich, und ein Ziel unter dem Grundumsatz ist keine Empfehlung.
        untergrenze = self.calc_bmr(p)
        kcal = max(basis.kcal * faktor, untergrenze)

        protein_kcal = basis.protein_g * 4
        fat_kcal = basis.fat_g * 9
        carbs_g = max(0.0, kcal - protein_kcal - fat_kcal) / 4

        grund.update({
            "verschoben": True,
            "trainingstag": ist_training,
            "quelle": tagesinfo.get("quelle"),
            "anteil": anteil,
            "trainings_pro_woche": round(t, 2),
            "faktor": round(faktor, 4),
            "basis_kcal": basis.kcal,
            "grund": (
                "Trainingstag: Kohlenhydrate hoch, dafuer an den Ruhetagen "
                "entsprechend niedriger. Die Wochensumme bleibt gleich."
                if ist_training else
                "Ruhetag: Kohlenhydrate niedriger, dafuer an den Trainingstagen "
                "hoeher. Die Wochensumme bleibt gleich."
            ),
        })

        return DailyMacroTargets(
            kcal=round(kcal, 1),
            protein_g=basis.protein_g,
            carbs_g=round(carbs_g, 1),
            fat_g=basis.fat_g,
            fiber_g=basis.fiber_g,
        ), grund

    # ----- helpers -----

    @staticmethod
    def _calc_age(birth_date: date) -> int:
        today = date.today()
        age = today.year - birth_date.year
        if (today.month, today.day) < (birth_date.month, birth_date.day):
            age -= 1
        return age
