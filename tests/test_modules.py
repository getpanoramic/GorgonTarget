import pytest
from gorgontarget.translator import MedusaTranslator
from gorgontarget.models import SonarrSeries

def test_parse_size_to_bytes():
    assert MedusaTranslator.parse_size_to_bytes("500 GB") == 500 * 10**9
    assert MedusaTranslator.parse_size_to_bytes("1 TB") == 10**12
    assert MedusaTranslator.parse_size_to_bytes("invalid") == 0

def test_translator_extract_clean_integer_id():
    assert MedusaTranslator.extract_clean_integer_id({"id": 123}) == 123
    assert MedusaTranslator.extract_clean_integer_id({"id": {"medusa": 456}}) == 456

def test_translator_to_sonarr_series():
    medusa_show = {
        "id": 1,
        "title": "Test Show",
        "ids": {"tvdb": 100, "tmdb": 200},
        "path": "/tv/TestShow",
        "status": "continuing",
        "year": 2026
    }
    series = MedusaTranslator.to_sonarr_series(medusa_show)
    assert isinstance(series, SonarrSeries)
    assert series.title == "Test Show"
    assert series.tvdbId == 100
    assert series.year == 2026
