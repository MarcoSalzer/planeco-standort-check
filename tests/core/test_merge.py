from app.core.merge import merge_fields


def test_neuer_wert_gewinnt_bei_widerspruch():
    result = merge_fields(old={"phone": "+4940111111"}, new={"phone": "+4940222222"})
    assert result.values["phone"] == "+4940222222"
    assert result.changed_fields["phone"] == {"alt": "+4940111111", "neu": "+4940222222"}
    assert result.merged_fields == {}


def test_leerer_neuer_wert_uebernimmt_alten():
    result = merge_fields(old={"message": "Bitte anrufen"}, new={"message": ""})
    assert result.values["message"] == "Bitte anrufen"
    assert result.merged_fields["message"] == "Bitte anrufen"
    assert result.changed_fields == {}


def test_leerer_neuer_wert_uebernimmt_alten_bei_none():
    result = merge_fields(old={"message": "Bitte anrufen"}, new={"message": None})
    assert result.values["message"] == "Bitte anrufen"
    assert result.merged_fields["message"] == "Bitte anrufen"


def test_beide_leer_bleibt_leer():
    result = merge_fields(old={"message": None}, new={"message": ""})
    assert result.values["message"] == ""
    assert result.changed_fields == {}
    assert result.merged_fields == {}


def test_identischer_wert_ist_keine_aenderung():
    result = merge_fields(old={"city": "Hamburg"}, new={"city": "Hamburg"})
    assert result.values["city"] == "Hamburg"
    assert result.changed_fields == {}
    assert result.merged_fields == {}


def test_is_owner_false_ist_ein_gefuellter_wert_kein_leerfeld():
    result = merge_fields(old={"is_owner": True}, new={"is_owner": False})
    assert result.values["is_owner"] is False
    assert result.changed_fields["is_owner"] == {"alt": True, "neu": False}
    assert result.merged_fields == {}


def test_is_owner_none_uebernimmt_alten_bool_wert():
    result = merge_fields(old={"is_owner": True}, new={"is_owner": None})
    assert result.values["is_owner"] is True
    assert result.merged_fields["is_owner"] is True


def test_mehrere_felder_unabhaengig_voneinander():
    old = {"name": "Tom Ahrens", "message": "Altes Anliegen", "postal_code": None}
    new = {"name": "", "message": "Neues Anliegen", "postal_code": "20095"}
    result = merge_fields(old=old, new=new)
    assert result.values == {
        "name": "Tom Ahrens",
        "message": "Neues Anliegen",
        "postal_code": "20095",
    }
    assert result.merged_fields == {"name": "Tom Ahrens"}
    assert result.changed_fields == {
        "message": {"alt": "Altes Anliegen", "neu": "Neues Anliegen"},
        "postal_code": {"alt": None, "neu": "20095"},
    }


def test_vorher_leeres_feld_wird_jetzt_befuellt_erscheint_im_diff():
    """Fund, s. docs/FUNDE.md: ein Feld, das vorher leer war (None) und jetzt
    zum ersten Mal befüllt wird, muss im Änderungsprotokoll auftauchen -
    weder als "geändert" (verlangte fälschlich einen bereits gefüllten alten
    Wert) noch als "übernommen" (verlangt einen leeren neuen Wert) erfasste
    das vorher, die Information verschwand spurlos aus changed_fields UND
    merged_fields."""
    result = merge_fields(old={"message": None}, new={"message": "Neue Anmerkung"})
    assert result.values["message"] == "Neue Anmerkung"
    assert result.changed_fields == {"message": {"alt": None, "neu": "Neue Anmerkung"}}
    assert result.merged_fields == {}


def test_vorher_leeres_feld_als_whitespace_wird_jetzt_befuellt_erscheint_im_diff():
    result = merge_fields(old={"message": "   "}, new={"message": "Neue Anmerkung"})
    assert result.values["message"] == "Neue Anmerkung"
    assert result.changed_fields == {"message": {"alt": "   ", "neu": "Neue Anmerkung"}}
    assert result.merged_fields == {}
