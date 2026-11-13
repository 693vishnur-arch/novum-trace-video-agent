from backend.app.services import commons


def test_conservative_license_gate():
    assert commons.eligible({"LicenseShortName": {"value": "CC0"}})
    assert commons.eligible({"LicenseShortName": {"value": "Public domain"}})
    assert not commons.eligible({"LicenseShortName": {"value": "CC BY-SA 4.0"}})
    assert not commons.eligible({})


def test_reject_untrusted_image_url(tmp_path):
    try:
        commons.download_image({"download_url": "https://evil.example/test"}, tmp_path / "x.png")
        assert False, "expected validation failure"
    except ValueError:
        pass
