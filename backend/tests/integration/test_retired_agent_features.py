import pytest


def test_older_web_clients_can_load_without_agent_features(api_client, monkeypatch):
    monkeypatch.setattr("app.core.config.SPAM_RESCUE_ENABLED", True)
    response = api_client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["features"] == {
        "auto_response_drafts": False,
        "auto_response_send": False,
        "writing_style_cards": False,
        "spam_rescue": True,
    }
    response = api_client.get("/api/settings/ai-digest-attention-notes")
    assert response.status_code == 200
    assert response.json() == {"notes": []}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/settings/ai-digest-attention-notes"),
        ("PATCH", "/api/settings/ai-digest-attention-notes/1"),
        ("DELETE", "/api/settings/ai-digest-attention-notes/1"),
        ("GET", "/api/settings/writing-style-cards"),
        ("POST", "/api/settings/writing-style-cards"),
        ("POST", "/api/messages/1/auto-response-draft"),
        ("POST", "/api/messages/1/auto-response-send-preview"),
        ("POST", "/api/messages/1/auto-response-send"),
    ],
)
def test_retired_agent_routes_are_unavailable(api_client, method, path):
    assert api_client.request(method, path).status_code in (404, 405)
