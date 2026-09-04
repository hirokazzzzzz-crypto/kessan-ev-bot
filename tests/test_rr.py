import pytest

from pretrade.rr import calculate_rr, RR_WARNING_THRESHOLD


def test_calculate_rr_basic():
    rr = calculate_rr(entry_price=1000, target_price=1200, stop_price=950)
    assert rr.reward == pytest.approx(200)
    assert rr.risk == pytest.approx(50)
    assert rr.ratio == pytest.approx(4.0)
    assert rr.warning is False


def test_calculate_rr_below_threshold_warns():
    rr = calculate_rr(entry_price=1000, target_price=1050, stop_price=950)
    assert rr.ratio == pytest.approx(1.0)
    assert rr.ratio < RR_WARNING_THRESHOLD
    assert rr.warning is True


def test_calculate_rr_exactly_threshold_no_warning():
    rr = calculate_rr(entry_price=1000, target_price=1200, stop_price=900)
    assert rr.ratio == pytest.approx(2.0)
    assert rr.warning is False


def test_calculate_rr_invalid_stop_price():
    with pytest.raises(ValueError):
        calculate_rr(entry_price=1000, target_price=1200, stop_price=1000)


def test_calculate_rr_invalid_target_price():
    with pytest.raises(ValueError):
        calculate_rr(entry_price=1000, target_price=1000, stop_price=950)
