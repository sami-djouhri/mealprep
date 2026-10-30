"""Tests für recipe_hidden: hide/unhide + Filter in Listing und Vorschlags-Kandidaten.

Tenant-Isolation wird live via docker exec verifiziert (Events hängen an
SessionLocal, die Test-Session ist bewusst ungescoped, wie bei Migration 0010).
"""

from app.models import Recipe, RecipeHidden
from app.services.recipes import RecipesService


def _mk_recipe(db, name="Testgericht"):
    r = Recipe(name=name, portions_default=2, cook_time_min=20, owner_sub=None)
    db.add(r)
    db.flush()
    return r


def test_hide_filters_from_list(db):
    r1 = _mk_recipe(db, "Bleibt")
    r2 = _mk_recipe(db, "Wird ausgeblendet")
    svc = RecipesService(db)

    assert svc.hide(r2.id) is True
    ids = {r.id for r in svc.list_all()}
    assert r1.id in ids and r2.id not in ids

    # include_hidden liefert beide
    ids_all = {r.id for r in svc.list_all(include_hidden=True)}
    assert {r1.id, r2.id} <= ids_all


def test_hide_is_idempotent(db):
    r = _mk_recipe(db)
    svc = RecipesService(db)
    assert svc.hide(r.id) is True
    assert svc.hide(r.id) is True
    assert db.query(RecipeHidden).count() == 1


def test_unhide_restores(db):
    r = _mk_recipe(db)
    svc = RecipesService(db)
    svc.hide(r.id)
    assert svc.unhide(r.id) is True
    assert r.id in {x.id for x in svc.list_all()}
    # idempotent
    assert svc.unhide(r.id) is True


def test_hide_unknown_recipe_returns_false(db):
    svc = RecipesService(db)
    assert svc.hide(99999) is False
    assert svc.unhide(99999) is False


def test_filter_respects_hidden(db):
    r = _mk_recipe(db, "Suppengrün")
    svc = RecipesService(db)
    svc.hide(r.id)
    assert svc.filter(q="Suppen") == []
    assert {x.id for x in svc.filter(q="Suppen", include_hidden=True)} == {r.id}


def test_delete_cleans_up_hidden_entry(db):
    r = _mk_recipe(db)
    svc = RecipesService(db)
    svc.hide(r.id)
    assert svc.delete(r.id) is True
    assert db.query(RecipeHidden).count() == 0
