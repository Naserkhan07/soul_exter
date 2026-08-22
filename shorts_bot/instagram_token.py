from __future__ import annotations

import argparse
import getpass
from pathlib import Path
from typing import Any

import httpx

from .errors import ConfigurationError


class InstagramTokenError(ConfigurationError):
    """Meta could not issue a long-lived Instagram publishing token."""


def exchange_long_lived_page_token(
    app_id: str,
    app_secret: str,
    short_user_token: str,
    instagram_username: str,
    api_version: str = "v26.0",
    require_facebook: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> tuple[str, str, str]:
    """Exchange a short User token, then retrieve the matching long-lived Page token."""
    base = f"https://graph.facebook.com/{api_version}"
    timeout = httpx.Timeout(60, read=120)
    with httpx.Client(timeout=timeout, transport=transport) as client:
        exchange = client.get(
            f"{base}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_user_token,
            },
        )
        exchange_payload = _meta_json(exchange, "exchange the short-lived User token")
        long_user_token = str(exchange_payload.get("access_token") or "")
        if not long_user_token:
            raise InstagramTokenError("Meta returned no long-lived User access token.")

        permissions = client.get(
            f"{base}/me/permissions",
            headers={"Authorization": f"Bearer {long_user_token}"},
        )
        permissions_payload = _meta_json(permissions, "check granted Meta permissions")
        granted = {
            str(item.get("permission"))
            for item in permissions_payload.get("data", [])
            if isinstance(item, dict) and item.get("status") == "granted"
        }
        required = {
            "pages_show_list",
            "pages_read_engagement",
            "instagram_basic",
            "instagram_content_publish",
        }
        if require_facebook:
            required.add("pages_manage_posts")
        missing = sorted(required - granted)
        if missing:
            raise InstagramTokenError(
                "The User token is missing required Instagram/Facebook publishing permissions: "
                + ", ".join(missing)
            )

        accounts = client.get(
            f"{base}/me/accounts",
            headers={"Authorization": f"Bearer {long_user_token}"},
            params={"fields": "id,name,access_token,tasks,instagram_business_account{id,username}"},
        )
        accounts_payload = _meta_json(accounts, "list managed Facebook Pages")

    target = instagram_username.strip().lstrip("@").casefold()
    pages = accounts_payload.get("data", [])
    if not isinstance(pages, list):
        pages = []
    available: list[str] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        instagram = page.get("instagram_business_account", {})
        if not isinstance(instagram, dict):
            continue
        username = str(instagram.get("username") or "")
        if username:
            available.append(username)
        if username.casefold() != target:
            continue
        page_token = str(page.get("access_token") or "")
        if not page_token:
            raise InstagramTokenError(
                f"Meta found @{instagram_username} but returned no Page access token."
            )
        page_id = str(page.get("id") or "")
        if not page_id:
            raise InstagramTokenError("Meta returned no Facebook Page ID.")
        return page_token, str(page.get("name") or "Unnamed Page"), page_id

    detail = ", ".join(f"@{name}" for name in available) or "no connected Instagram accounts"
    raise InstagramTokenError(
        f"No Facebook Page connected to @{instagram_username} was returned; found {detail}."
    )


def set_dotenv_value(path: Path, name: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{name}="
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith(prefix):
            if not replaced:
                output.append(f"{name}={value}")
                replaced = True
            continue
        output.append(line)
    if not replaced:
        if output and output[-1]:
            output.append("")
        output.append(f"{name}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _meta_json(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise InstagramTokenError(
            f"Meta returned invalid data while trying to {operation}."
        ) from exc
    if response.is_success and isinstance(payload, dict):
        return payload
    detail = f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error", {})
        if isinstance(error, dict):
            detail = str(error.get("error_user_msg") or error.get("message") or detail)
    raise InstagramTokenError(f"Could not {operation}: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create and save a long-lived Page token for Instagram Reel publishing."
    )
    parser.add_argument("--username", default="splitzz.isodope")
    parser.add_argument(
        "--facebook",
        action="store_true",
        help="Require Facebook Reel permissions and enable Facebook publishing",
    )
    parser.add_argument("--api-version", default="v26.0")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()

    print("Generate a fresh USER token in Meta Graph API Explorer before continuing.")
    app_id = input("Meta App ID: ").strip()
    app_secret = getpass.getpass("Meta App Secret (hidden): ").strip()
    user_token = getpass.getpass("Short-lived Facebook USER token (hidden): ").strip()
    if not app_id or not app_secret or not user_token:
        parser.error("App ID, App Secret, and short-lived User token are required.")

    try:
        page_token, page_name, page_id = exchange_long_lived_page_token(
            app_id,
            app_secret,
            user_token,
            args.username,
            args.api_version,
            require_facebook=args.facebook,
        )
        set_dotenv_value(args.env_file, "INSTAGRAM_ACCESS_TOKEN", page_token)
        set_dotenv_value(args.env_file, "INSTAGRAM_GRAPH_API_VERSION", args.api_version)
        if args.facebook:
            set_dotenv_value(args.env_file, "FACEBOOK_ACCESS_TOKEN", page_token)
            set_dotenv_value(args.env_file, "FACEBOOK_PAGE_ID", page_id)
            set_dotenv_value(args.env_file, "FACEBOOK_GRAPH_API_VERSION", args.api_version)
            set_dotenv_value(args.env_file, "UPLOAD_FACEBOOK", "true")
    except InstagramTokenError as exc:
        parser.error(str(exc))
        return

    facebook_note = f" and configured Facebook Page {page_id}" if args.facebook else ""
    print(
        f"Saved a long-lived Page token for @{args.username} ({page_name}){facebook_note} "
        f"in {args.env_file}."
    )
    print("The App Secret and temporary User token were not saved.")


if __name__ == "__main__":
    main()
