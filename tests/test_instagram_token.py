from pathlib import Path

import httpx

from shorts_bot.instagram_token import exchange_long_lived_page_token, set_dotenv_value


def test_exchanges_user_token_and_selects_matching_page_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v26.0/oauth/access_token":
            assert request.url.params["client_id"] == "app-id"
            assert request.url.params["client_secret"] == "app-secret"
            assert request.url.params["fb_exchange_token"] == "short-user-token"
            return httpx.Response(200, json={"access_token": "long-user-token"})
        if request.url.path == "/v26.0/me/permissions":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"permission": permission, "status": "granted"}
                        for permission in (
                            "pages_show_list",
                            "pages_read_engagement",
                            "pages_manage_posts",
                            "instagram_basic",
                            "instagram_content_publish",
                        )
                    ]
                },
            )
        if request.url.path == "/v26.0/me/accounts":
            assert request.headers["authorization"] == "Bearer long-user-token"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "page-123",
                            "name": "Splitzz Page",
                            "access_token": "long-page-token",
                            "instagram_business_account": {
                                "id": "1789",
                                "username": "splitzz.isodope",
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    token, page_name, page_id = exchange_long_lived_page_token(
        "app-id",
        "app-secret",
        "short-user-token",
        "splitzz.isodope",
        require_facebook=True,
        transport=httpx.MockTransport(handler),
    )

    assert token == "long-page-token"
    assert page_name == "Splitzz Page"
    assert page_id == "page-123"
    assert len(requests) == 3


def test_saves_page_token_without_duplicate_dotenv_entries(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "INSTAGRAM_ACCESS_TOKEN=old\nOTHER=value\nINSTAGRAM_ACCESS_TOKEN=duplicate\n",
        encoding="utf-8",
    )

    set_dotenv_value(env_path, "INSTAGRAM_ACCESS_TOKEN", "long-page-token")

    content = env_path.read_text(encoding="utf-8")
    assert content.count("INSTAGRAM_ACCESS_TOKEN=") == 1
    assert "INSTAGRAM_ACCESS_TOKEN=long-page-token" in content
    assert "OTHER=value" in content
