import pytest
from pydantic import ValidationError

from app.core.masking import mask_for_log, mask_value
from app.core.schemas import change_schema, create_schema


def test_client_id_in_the_body_is_ignored():
    body = create_schema("locations").model_validate({"code": "L1", "name": "One", "state_rid": 1, "client_id": 999, "junk": 1}).model_dump()
    assert "client_id" not in body and "junk" not in body


def test_pan_is_upper_cased_and_checked():
    le = create_schema("legal-entities")
    assert le.model_validate({"code": "E1", "registered_name": "X", "pan": "aaacx1234a"}).model_dump()["pan"] == "AAACX1234A"
    with pytest.raises(ValidationError):
        le.model_validate({"code": "E1", "registered_name": "X", "pan": "NOTAPAN"})


def test_change_schema_is_all_optional():
    assert change_schema("departments").model_validate({}).model_dump(exclude_unset=True) == {}


def test_masking():
    assert mask_value("123456789012") == "XXXXXXXX9012"
    out = mask_for_log({"pan": "AAACX1234A", "pan_hash": "h", "name": "n"}, {"pan"})
    assert out["pan"].endswith("234A") and out["pan"].startswith("X") and "pan_hash" not in out
