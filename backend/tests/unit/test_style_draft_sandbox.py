from __future__ import annotations

from app.services.style_draft_sandbox import render_prompt_packet


def test_render_prompt_packet_combines_profile_and_synthetic_email():
    packet = render_prompt_packet(
        account_email="owner@example.com",
        style_profile="# Writing Style Profile\n\nBe practical and warm.",
        scenario={
            "id": "example",
            "from": "Ari <ari@example.com>",
            "subject": "Prototype feedback",
            "body": "Hi Russel,\n\nDo you want detailed notes?\n\nAri",
            "draft_goal": "Thank them and ask for concise notes.",
        },
    )

    assert "# Draft Sandbox Packet: example" in packet
    assert "Be practical and warm." in packet
    assert "From: Ari <ari@example.com>" in packet
    assert "Thank them and ask for concise notes." in packet
    assert "Return only the drafted email body." in packet
