"""PhonePe Payment Gateway Standard Checkout v2 integration."""

import asyncio
import hashlib
import hmac
import threading
import time
from urllib.parse import quote
import httpx
from .config import settings
from .db import now, row, rows, transaction
from .sales import record_sale
from .workstreams import ensure_workstream, mark_completed, mark_failed, mark_started


class PhonePeAPIError(RuntimeError):
    pass


class PhonePeAPI:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 client_version: int | None = None, environment: str | None = None, timeout: float = 20):
        self.client_id = client_id or settings.phonepe_client_id
        self.client_secret = client_secret or settings.phonepe_client_secret
        self.client_version = client_version or settings.phonepe_client_version
        self.environment = (environment or settings.phonepe_environment).lower()
        self.timeout = timeout
        if self.environment not in {"sandbox", "production"}:
            raise ValueError("PhonePe environment must be sandbox or production")
        if not self.client_id or not self.client_secret or not self.client_version:
            raise ValueError("PhonePe client credentials are required")
        if self.environment == "sandbox":
            self.auth_base = self.api_base = "https://api-preprod.phonepe.com/apis/pg-sandbox"
        else:
            self.auth_base = "https://api.phonepe.com/apis/identity-manager"
            self.api_base = "https://api.phonepe.com/apis/pg"
        self._token = ""
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def _access_token(self) -> str:
        with self._token_lock:
            if self._token and self._token_expires_at > time.time() + 60:
                return self._token
            try:
                response = httpx.post(
                    f"{self.auth_base}/v1/oauth/token",
                    data={"client_id": self.client_id, "client_version": str(self.client_version),
                          "client_secret": self.client_secret, "grant_type": "client_credentials"},
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                token = str(payload["access_token"])
                expires = float(payload.get("expires_at", 0))
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                raise PhonePeAPIError("PhonePe authorization failed") from exc
            if expires < time.time():
                expires = time.time() + max(300, expires)
            self._token, self._token_expires_at = token, expires
            return token

    def _request(self, method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
        try:
            response = httpx.request(
                method, f"{self.api_base}{path}", json=payload, params=params,
                headers={"Authorization": f"O-Bearer {self._access_token()}",
                         "Content-Type": "application/json", "Accept": "application/json",
                         "User-Agent": "Automaton/0.1"}, timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PhonePeAPIError("PhonePe API request failed") from exc
        if not isinstance(data, dict):
            raise PhonePeAPIError("PhonePe returned an invalid response")
        return data

    def create_payment(self, merchant_order_id: str, amount_paise: int, redirect_url: str,
                       message: str, expire_after: int) -> dict:
        return self._request("POST", "/checkout/v2/pay", {
            "merchantOrderId": merchant_order_id,
            "amount": amount_paise,
            "expireAfter": expire_after,
            "paymentFlow": {"type": "PG_CHECKOUT", "message": message[:120],
                            "merchantUrls": {"redirectUrl": redirect_url}},
        })

    def order_status(self, merchant_order_id: str) -> dict:
        return self._request("GET", f"/checkout/v2/order/{quote(merchant_order_id, safe='')}/status",
                             params={"details": "true"})


def webhook_authorization(username: str, password: str) -> str:
    return hashlib.sha256(f"{username}:{password}".encode()).hexdigest()


def validate_webhook_authorization(received: str, username: str, password: str) -> bool:
    expected = webhook_authorization(username, password)
    normalized = (received or "").strip()
    if normalized.lower().startswith("sha256 "):
        normalized = normalized.split(None, 1)[1]
    return bool(username and password and hmac.compare_digest(normalized.lower(), expected.lower()))


def _transaction_id(status_payload: dict) -> str:
    for payment in status_payload.get("paymentDetails") or []:
        if payment.get("state") == "COMPLETED" and payment.get("transactionId"):
            return str(payment["transactionId"])
    return str(status_payload.get("orderId") or "")


def complete_phonepe_order(merchant_order_id: str, status_payload: dict) -> bool:
    order = row("""SELECT pho.*,po.product_id,po.amount_cents,po.id payment_order_id
                   FROM phonepe_orders pho JOIN payment_orders po ON po.id=pho.payment_order_id
                   WHERE pho.merchant_order_id=?""", (merchant_order_id,))
    if not order:
        return False
    if status_payload.get("state") != "COMPLETED" or int(status_payload.get("amount", 0)) != order["amount_cents"]:
        return False
    transaction_id = _transaction_id(status_payload)
    if not transaction_id:
        return False
    record_sale(order["product_id"], order["amount_cents"], transaction_id, "PhonePe")
    stamp = now()
    with transaction() as db:
        db.execute("""UPDATE phonepe_orders SET state='COMPLETED',phonepe_order_id=?,transaction_id=?,
                      last_checked_at=?,completed_at=? WHERE payment_order_id=?""",
                   (str(status_payload.get("orderId") or ""), transaction_id, stamp, stamp, order["payment_order_id"]))
        db.execute("""UPDATE payment_orders SET provider_payment_id=?,status='paid',paid_at=? WHERE id=?""",
                   (transaction_id, stamp, order["payment_order_id"]))
    return True


def refresh_phonepe_order(payment_order_id: int) -> dict:
    order = row("""SELECT pho.*,po.status payment_status,po.product_id,po.amount_cents,po.fulfillment_token
                   FROM phonepe_orders pho JOIN payment_orders po ON po.id=pho.payment_order_id
                   WHERE pho.payment_order_id=?""", (payment_order_id,))
    if not order:
        raise PhonePeAPIError("PhonePe order not found")
    if order["payment_status"] == "paid":
        return {**order, "paid": True}
    status = PhonePeAPI().order_status(order["merchant_order_id"])
    state = str(status.get("state") or "PENDING")
    paid = complete_phonepe_order(order["merchant_order_id"], status)
    if not paid:
        with transaction() as db:
            db.execute("UPDATE phonepe_orders SET state=?,phonepe_order_id=?,last_checked_at=? WHERE payment_order_id=?",
                       (state, str(status.get("orderId") or ""), now(), payment_order_id))
            if state == "FAILED":
                db.execute("UPDATE payment_orders SET status='failed' WHERE id=?", (payment_order_id,))
    return {**order, "state": "COMPLETED" if paid else state, "paid": paid,
            "phonepe_order_id": status.get("orderId")}


async def phonepe_payment_scheduler(stop: asyncio.Event) -> None:
    interval = max(30, settings.phonepe_poll_seconds)
    ensure_workstream("phonepe_payments", interval, {"status": "monitoring_orders"})
    while not stop.is_set():
        pending = rows("""SELECT payment_order_id FROM phonepe_orders
                          WHERE state IN ('PENDING','CREATED') ORDER BY id LIMIT 50""")
        mark_started("phonepe_payments", interval)
        checked = completed = errors = 0
        try:
            for item in pending:
                try:
                    result = await asyncio.to_thread(refresh_phonepe_order, item["payment_order_id"])
                    checked += 1
                    completed += int(bool(result.get("paid")))
                except Exception:
                    errors += 1
            mark_completed("phonepe_payments", interval,
                           {"checked": checked, "completed": completed, "errors": errors,
                            "status": "no_pending_orders" if not pending else "checked_orders"})
        except Exception as exc:
            mark_failed("phonepe_payments", interval, exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
