from __future__ import annotations


def test_spam_rescue_keywords_endpoint_seeds_defaults(api_client):
    response = api_client.get("/api/settings/spam-rescue-protected-keywords")

    assert response.status_code == 200
    keywords = response.json()["keywords"]
    keyword_values = {item["keyword"] for item in keywords}
    assert "invoice" in keyword_values
    assert "account recovery" in keyword_values
    assert all(item["enabled"] is True for item in keywords)


def test_spam_rescue_keywords_can_create_update_toggle_and_delete(api_client):
    create_response = api_client.post(
        "/api/settings/spam-rescue-protected-keywords",
        json={"keyword": "Zoning Permit"},
    )
    assert create_response.status_code == 200
    created = create_response.json()["keyword"]
    assert created["keyword"] == "zoning permit"
    assert created["enabled"] is True

    update_response = api_client.patch(
        f"/api/settings/spam-rescue-protected-keywords/{created['id']}",
        json={"keyword": "Permit Hearing", "enabled": False},
    )
    assert update_response.status_code == 200
    updated = update_response.json()["keyword"]
    assert updated["keyword"] == "permit hearing"
    assert updated["enabled"] is False

    delete_response = api_client.delete(
        f"/api/settings/spam-rescue-protected-keywords/{created['id']}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    keywords = api_client.get("/api/settings/spam-rescue-protected-keywords").json()["keywords"]
    assert "permit hearing" not in {item["keyword"] for item in keywords}


def test_spam_rescue_keywords_reject_duplicates(api_client):
    first_response = api_client.post(
        "/api/settings/spam-rescue-protected-keywords",
        json={"keyword": "Zoning Permit"},
    )
    assert first_response.status_code == 200

    duplicate_response = api_client.post(
        "/api/settings/spam-rescue-protected-keywords",
        json={"keyword": " zoning   permit "},
    )
    assert duplicate_response.status_code == 400
    assert duplicate_response.json()["code"] == "spam_rescue_keyword_validation_failed"
