"""Tests for ProfileService: BMR, TDEE, macro targets."""

from datetime import date

from app.models import UserProfile
from app.services.profile import ACTIVITY_MULTIPLIERS, ProfileService


def test_bmr_katch_mcardle(db):
    """Katch-McArdle BMR when body_fat_pct is provided."""
    profile = UserProfile(
        id=1, height_cm=180, weight_kg=80, sex="male",
        activity_level="moderate", body_fat_pct=15.0,
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    bmr = svc.calc_bmr(profile)

    # LBM = 80 * (1 - 0.15) = 68
    # BMR = 370 + 21.6 * 68 = 370 + 1468.8 = 1838.8
    expected = 370 + 21.6 * (80 * 0.85)
    assert abs(bmr - expected) < 0.1, f"Expected {expected}, got {bmr}"


def test_bmr_mifflin_male(db):
    """Mifflin-St Jeor for male without body_fat_pct."""
    profile = UserProfile(
        id=1, height_cm=180, weight_kg=80, sex="male",
        activity_level="moderate",
        birth_date=date(1996, 6, 15),  # ~29 years old
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    bmr = svc.calc_bmr(profile)

    age = svc._calc_age(date(1996, 6, 15))
    expected = 10 * 80 + 6.25 * 180 - 5 * age + 5
    assert abs(bmr - expected) < 0.1, f"Expected {expected}, got {bmr}"


def test_bmr_mifflin_female(db):
    """Mifflin-St Jeor for female without body_fat_pct."""
    profile = UserProfile(
        id=1, height_cm=165, weight_kg=60, sex="female",
        activity_level="light",
        birth_date=date(1992, 3, 10),
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    bmr = svc.calc_bmr(profile)

    age = svc._calc_age(date(1992, 3, 10))
    expected = 10 * 60 + 6.25 * 165 - 5 * age - 161
    assert abs(bmr - expected) < 0.1, f"Expected {expected}, got {bmr}"


def test_tdee_uses_activity_multiplier(db):
    """TDEE = BMR * activity multiplier."""
    profile = UserProfile(
        id=1, height_cm=180, weight_kg=80, sex="male",
        activity_level="active", body_fat_pct=15.0,
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    bmr = svc.calc_bmr(profile)
    tdee = svc.calc_tdee(profile)

    expected_mult = ACTIVITY_MULTIPLIERS["active"]  # 1.725
    assert abs(tdee - bmr * expected_mult) < 0.1


def test_macro_targets_weight_loss(db):
    """Targets for weight-loss goal: TDEE-500 kcal, 2.2g/kg protein, 0.9g/kg fat."""
    profile = UserProfile(
        id=1, height_cm=180, weight_kg=80, sex="male",
        activity_level="moderate", target_weight_kg=72.0,
        body_fat_pct=18.0,
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    targets = svc.derive_daily_targets(profile)

    tdee = svc.calc_tdee(profile)
    expected_kcal = tdee - 500

    assert abs(targets.kcal - round(expected_kcal, 1)) < 0.2
    assert targets.protein_g == round(80 * 2.2, 1)
    assert targets.fat_g == round(80 * 0.9, 1)

    # Carbs fill remaining
    protein_kcal = targets.protein_g * 4
    fat_kcal = targets.fat_g * 9
    expected_carbs = max(0, targets.kcal - protein_kcal - fat_kcal) / 4
    assert abs(targets.carbs_g - round(expected_carbs, 1)) < 0.2


def test_macro_targets_bulking(db):
    """Targets for weight-gain goal: TDEE+300 kcal, 2.0g/kg protein, 0.8g/kg fat."""
    profile = UserProfile(
        id=1, height_cm=175, weight_kg=65, sex="male",
        activity_level="active", target_weight_kg=72.0,
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    targets = svc.derive_daily_targets(profile)

    tdee = svc.calc_tdee(profile)
    expected_kcal = tdee + 300

    assert abs(targets.kcal - round(expected_kcal, 1)) < 0.2
    assert targets.protein_g == round(65 * 2.0, 1)
    assert targets.fat_g == round(65 * 0.8, 1)


def test_macro_targets_kcal_override(db):
    """kcal_target_override takes precedence over TDEE calculation."""
    profile = UserProfile(
        id=1, height_cm=180, weight_kg=80, sex="male",
        activity_level="moderate", target_weight_kg=75.0,
        kcal_target_override=2000,
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    targets = svc.derive_daily_targets(profile)

    assert targets.kcal == 2000.0


def test_body_metric_syncs_profile(db):
    """add_body_metric updates the profile's weight, body_fat_pct, and waist_cm."""
    profile = UserProfile(id=1, height_cm=180, weight_kg=80, sex="male", activity_level="moderate")
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    bm = svc.add_body_metric(weight_kg=78.5, body_fat_pct=14.0, waist_cm=84.0)

    db.refresh(profile)
    assert profile.weight_kg == 78.5
    assert profile.body_fat_pct == 14.0
    assert profile.waist_cm == 84.0
    assert bm.weight_kg == 78.5
    assert bm.body_fat_pct == 14.0
    assert bm.waist_cm == 84.0


def test_get_or_create_singleton(db):
    """get_or_create should always return id=1 profile."""
    svc = ProfileService(db)
    p1 = svc.get_or_create()
    assert p1.id == 1

    # Second call returns same
    p2 = svc.get_or_create()
    assert p2.id == 1
    assert p1 is p2
