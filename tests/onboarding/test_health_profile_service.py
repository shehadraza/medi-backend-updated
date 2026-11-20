
import pytest

from app.modules.health.service import (
    _get_profile_aad,
    _serialize_profile,
    _deserialize_profile,
)


def test_profile_serialization_preserves_bangla():
    data = {
        "sleep_hours": 7,
        "water_intake": 2,
        "notes": "আমি প্রতিদিন সকালে হাঁটি।",
    }

    serialized = _serialize_profile(data)

    assert "আমি প্রতিদিন সকালে হাঁটি।" in serialized
    assert _deserialize_profile(serialized) == data


def test_profile_serialization_rejects_non_dict():
    with pytest.raises(ValueError):
        _serialize_profile(["invalid", "profile"])


def test_profile_serialization_rejects_nan():
    with pytest.raises(ValueError):
        _serialize_profile({"sleep_hours": float("nan")})


def test_profile_deserialization_rejects_invalid_json():
    with pytest.raises(RuntimeError):
        _deserialize_profile("{invalid-json}")


def test_profile_deserialization_rejects_non_object():
    with pytest.raises(RuntimeError):
        _deserialize_profile('["not", "an", "object"]')


def test_profile_aad_is_user_specific():
    user_aad = _get_profile_aad("user-123")
    other_aad = _get_profile_aad("user-456")

    assert user_aad != other_aad
    assert user_aad == b"medi:health-profile:v1:user-123"


def test_profile_aad_rejects_empty_user_id():
    with pytest.raises(ValueError):
        _get_profile_aad("")
