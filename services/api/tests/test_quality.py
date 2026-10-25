from app.services.quality import clean_code, clean_value


def test_clean_value_accepts_plausible_observations():
    assert clean_value("temperature_c", 21.5) == 21.5
    assert clean_value("humidity_pct", "40") == 40.0
    assert clean_value("precipitation_mm", 0) == 0.0

def test_clean_value_rejects_missing_and_implausible_data():
    assert clean_value("temperature_c", None) is None
    assert clean_value("temperature_c", "not-a-number") is None
    assert clean_value("temperature_c", 120) is None
    assert clean_value("humidity_pct", -1) is None
    assert clean_value("pressure_hpa", float("nan")) is None
    assert clean_code(51.0) == 51
    assert clean_code(250) is None
