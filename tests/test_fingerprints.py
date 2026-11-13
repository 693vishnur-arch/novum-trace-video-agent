from backend.app.services.fingerprints import similar, historical_hashes


def test_hamming_duplicate_detection():
    assert similar("0000000000000000", "0000000000000001")
    assert not similar("0000000000000000", "ffffffffffffffff")
    assert not similar(None, "0000000000000000")


def test_historical_registry_reads_existing_credits():
    data = [{"stock_credits": [{"fingerprint": "abcdefabcdefabcd"}]},
            {"stock_credits": [{"video_id": "123"}]}]
    assert historical_hashes(data) == {"abcdefabcdefabcd"}
