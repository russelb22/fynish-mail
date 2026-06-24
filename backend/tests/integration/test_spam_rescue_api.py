from __future__ import annotations


def test_spam_rescue_api_returns_mock_candidates(api_client, seeded_db):
    response = api_client.get("/api/spam-rescue")

    assert response.status_code == 200
    payload = response.json()
    candidates = [
        message
        for account in payload["accounts"]
        for message in account["messages"]
    ]
    candidate_ids = {message["gmail_message_id"] for message in candidates}

    assert payload["count"] == len(candidates)
    assert "ps-9001" in candidate_ids
    assert "ps-9002" not in candidate_ids
    assert all(message["source_label"] == "spam" for message in candidates)
    assert all(message["review_surface"] == "spam_rescue" for message in candidates)


def test_feature_flags_include_spam_rescue(api_client, isolated_db):
    response = api_client.get("/api/features")

    assert response.status_code == 200
    assert response.json()["features"]["spam_rescue"] is True
