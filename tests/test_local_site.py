from pathlib import Path
from urllib.request import urlopen

from shorts_bot.local_site import start_local_storefront


def test_serves_splitzzz_website_and_security_headers(tmp_path: Path) -> None:
    website_dir = tmp_path / "website"
    website_dir.mkdir()
    (website_dir / "index.html").write_text("<h1>Splitzzz</h1>", encoding="utf-8")
    opened: list[str] = []

    website = start_local_storefront(
        website_dir,
        port=0,
        auto_open=True,
        browser_opener=opened.append,
    )
    try:
        with urlopen(website.url, timeout=5) as response:  # noqa: S310
            content = response.read().decode("utf-8")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
        assert "Splitzzz" in content
        assert opened == [website.url]
    finally:
        website.stop()

    assert not website.thread.is_alive()
