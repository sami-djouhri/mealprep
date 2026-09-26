"""Tagesbezogener Bedarf: Trainingstag gegen Ruhetag.

★★ Die Hauptgefahr ist nicht die Formel, sondern die duenne Grundlage. Ein
frisch eingerichtetes System darf den Kalorienbedarf eines Menschen, der
weiter trainiert, nicht nach unten schieben, nur weil noch nichts erfasst
ist. Deshalb pruefen die meisten Tests hier, dass **nichts** passiert.
"""

from __future__ import annotations

from datetime import date

from app.models import UserProfile
from app.services.profile import ProfileService
from tests.conftest import MockFitnessAdapter

BELASTBAR = {
    "stufe": "moderate",
    "faktor": 1.55,
    "trainings_pro_woche": 3.0,
    "trainings_im_fenster": 12,
    "fenster_tage": 28,
    "belastbar": True,
    "begruendung": "12 Trainings in 28 Tagen",
}

TRAINING_ERFASST = {"training": True, "quelle": "erfasst", "erreichbar": True}
RUHETAG = {"training": False, "quelle": "keine", "erreichbar": True}


def _profil(db):
    p = UserProfile(
        height_cm=180, weight_kg=80, sex="male",
        birth_date=date(1990, 1, 1), activity_level="moderate",
    )
    db.add(p)
    db.flush()
    return p


def test_ohne_belastbare_grundlage_bleibt_alles_wie_es_war(db):
    """Der Fall von heute: 0 von 4 Trainings erfasst, ``belastbar`` False."""
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    fitness = MockFitnessAdapter(niveau={
        "trainings_pro_woche": 0.0,
        "belastbar": False,
        "begruendung": "Erst 0 von 4 Trainings erfasst.",
    })

    ziele, grund = svc.tagesziele(date.today(), p, fitness)

    assert ziele.kcal == basis.kcal
    assert grund["verschoben"] is False
    assert "0 von 4" in grund["grund"], "der Grund muss in der Antwort stehen"


def test_fitness_nicht_erreichbar_aendert_nichts(db):
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    fitness = MockFitnessAdapter(erreichbar=False)

    ziele, grund = svc.tagesziele(date.today(), p, fitness)

    assert ziele.kcal == basis.kcal
    assert grund["verschoben"] is False
    assert "antwortet nicht" in grund["grund"]


def test_trainingstag_bekommt_mehr_kohlenhydrate(db):
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    fitness = MockFitnessAdapter(niveau=BELASTBAR, trainingstag=TRAINING_ERFASST)

    ziele, grund = svc.tagesziele(date.today(), p, fitness)

    assert grund["verschoben"] is True
    assert grund["trainingstag"] is True
    assert ziele.kcal > basis.kcal
    assert ziele.carbs_g > basis.carbs_g
    assert ziele.protein_g == basis.protein_g, "Protein haengt am Koerpergewicht"
    assert ziele.fat_g == basis.fat_g


def test_ruhetag_bekommt_weniger(db):
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    fitness = MockFitnessAdapter(niveau=BELASTBAR, trainingstag=RUHETAG)

    ziele, grund = svc.tagesziele(date.today(), p, fitness)

    assert grund["verschoben"] is True
    assert grund["trainingstag"] is False
    assert ziele.kcal < basis.kcal
    assert ziele.carbs_g < basis.carbs_g


def test_die_woche_bleibt_in_summe_gleich(db):
    """★★ Der Kern des Entwurfs: verschoben, nicht draufgerechnet.

    Der Aktivitaetsfaktor im TDEE bildet das Training schon ab. Ein
    Aufschlag am Trainingstag wuerde dasselbe Training zweimal zaehlen.
    """
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    t = BELASTBAR["trainings_pro_woche"]

    training = MockFitnessAdapter(niveau=BELASTBAR, trainingstag=TRAINING_ERFASST)
    ruhe = MockFitnessAdapter(niveau=BELASTBAR, trainingstag=RUHETAG)
    kcal_training = svc.tagesziele(date.today(), p, training)[0].kcal
    kcal_ruhe = svc.tagesziele(date.today(), p, ruhe)[0].kcal

    woche = t * kcal_training + (7 - t) * kcal_ruhe
    assert abs(woche - 7 * basis.kcal) < 1.0


def test_null_trainings_je_woche_hat_keine_gegenseite(db):
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    niveau = dict(BELASTBAR, trainings_pro_woche=0.0)
    fitness = MockFitnessAdapter(niveau=niveau, trainingstag=RUHETAG)

    ziele, grund = svc.tagesziele(date.today(), p, fitness)

    assert ziele.kcal == basis.kcal
    assert grund["verschoben"] is False
    assert "Gegenseite" in grund["grund"]


def test_sieben_trainings_je_woche_hat_keinen_ruhetag(db):
    """Bei t=7 teilt die Formel durch null. Das wird nicht gedeckelt."""
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    niveau = dict(BELASTBAR, trainings_pro_woche=7.0)
    fitness = MockFitnessAdapter(niveau=niveau, trainingstag=TRAINING_ERFASST)

    ziele, grund = svc.tagesziele(date.today(), p, fitness)

    assert ziele.kcal == basis.kcal
    assert grund["verschoben"] is False


def test_ruhetag_faellt_nie_unter_den_grundumsatz(db):
    p = _profil(db)
    svc = ProfileService(db)
    bmr = svc.calc_bmr(p)
    niveau = dict(BELASTBAR, trainings_pro_woche=6.0)
    fitness = MockFitnessAdapter(niveau=niveau, trainingstag=RUHETAG)

    # Ein absichtlich unsinnig grosser Anteil.
    from app.config import settings
    alt = settings.TRAININGSTAG_ANTEIL
    settings.TRAININGSTAG_ANTEIL = 0.9
    try:
        ziele, _grund = svc.tagesziele(date.today(), p, fitness)
    finally:
        settings.TRAININGSTAG_ANTEIL = alt

    assert ziele.kcal >= bmr


def test_abgeschaltet_heisst_abgeschaltet(db):
    p = _profil(db)
    svc = ProfileService(db)
    basis = svc.derive_daily_targets(p)
    fitness = MockFitnessAdapter(niveau=BELASTBAR, trainingstag=TRAINING_ERFASST)

    from app.config import settings
    alt = settings.TRAININGSTAG_ANTEIL
    settings.TRAININGSTAG_ANTEIL = 0.0
    try:
        ziele, grund = svc.tagesziele(date.today(), p, fitness)
    finally:
        settings.TRAININGSTAG_ANTEIL = alt

    assert ziele.kcal == basis.kcal
    assert grund["verschoben"] is False
    assert "abgeschaltet" in grund["grund"]


def test_geplanter_tag_wird_als_solcher_ausgewiesen(db):
    """Geplant ist nicht erfasst. Der Unterschied reist mit.

    Ein Tagesziel, das einen geplanten und dann ausgefallenen Trainingstag
    als Training rechnet, liegt zu hoch. Entschieden wird das nicht hier,
    aber sichtbar bleibt es.
    """
    p = _profil(db)
    svc = ProfileService(db)
    fitness = MockFitnessAdapter(
        niveau=BELASTBAR,
        trainingstag={"training": True, "quelle": "geplant", "erreichbar": True},
    )

    _ziele, grund = svc.tagesziele(date.today(), p, fitness)

    assert grund["quelle"] == "geplant"
