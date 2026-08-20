import unittest
import uuid
from unittest.mock import patch

import support  # configure the shared test database before importing app modules
from fastapi.testclient import TestClient
from app.config import settings
from app.db import now, transaction
from app.jobs import score_opportunity
from app.main import app
from app.phonepe_payments import webhook_authorization
from app.planner import FALLBACK_PRODUCTS, parse_json_object, survival_pressure
from app.sales import record_sale


class AutomatonTests(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app)
        self.client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_00_genesis_cycle_launches_and_sale_credits_agent(self):
        state = self.client.get("/api/state").json()
        self.assertEqual(state["mode"], "simulation")
        self.assertEqual(state["currency"], "INR")
        self.assertEqual(state["payment_provider"], "phonepe")
        self.assertGreaterEqual(len(state["agents"]), 1)
        self.assertEqual(state["totals"]["balance"], 0)
        self.assertFalse(any(entry["kind"] == "seed" for entry in state["ledger"]))
        if not any(product["agent_id"] == 1 for product in state["products"]):
            result = self.client.post("/api/cycle/1")
            self.assertEqual(result.status_code, 200)
        state = self.client.get("/api/state").json()
        product = next(product for product in state["products"] if product["agent_id"] == 1)
        founder = next(agent for agent in state["agents"] if agent["id"] == 1)
        before = founder["balance_cents"]
        result = self.client.post(f"/api/simulate-sale/{product['slug']}")
        self.assertEqual(result.status_code, 200)
        self.assertIn("content", result.json())
        founder_after = next(agent for agent in self.client.get("/api/state").json()["agents"] if agent["id"] == 1)
        self.assertEqual(founder_after["balance_cents"], before + product["price_cents"])

    def test_workstreams_are_visible_and_bounded(self):
        state = self.client.get("/api/state").json()
        lanes = {lane["name"]: lane for lane in state["workstreams"]}
        self.assertIn("agent_operations", lanes)
        self.assertIn("opportunity_research", lanes)
        self.assertEqual(lanes["opportunity_research"]["interval_seconds"], 60)
        self.assertIn("strategy_research", lanes)
        self.assertIn("phonepe_payments", lanes)
        self.assertTrue(all(lane["status"] in {"waiting", "running", "error"} for lane in lanes.values()))
        self.assertGreaterEqual(settings.max_concurrent_agents, 1)

    def test_zero_cash_agent_keeps_working_without_spending(self):
        name = "SPONSORED-" + uuid.uuid4().hex[:8]
        with transaction() as db:
            cur = db.execute("""INSERT INTO agents(name,balance_cents,mission,born_at,next_cycle_at)
                              VALUES(?,0,'test',?,?)""", (name, now(), now()))
            agent_id = cur.lastrowid
        actions = [self.client.post(f"/api/cycle/{agent_id}").json()["action"] for _ in range(5)]
        self.assertEqual(actions[:3], ["launch", "launch", "launch"])
        self.assertNotIn("death", actions)
        state = self.client.get("/api/state").json()
        agent = next(a for a in state["agents"] if a["id"] == agent_id)
        self.assertEqual(agent["balance_cents"], 0)
        self.assertEqual(agent["status"], "alive")
        self.assertFalse(any(entry["agent_id"] == agent_id for entry in state["ledger"]))

    def test_free_diagnostic_returns_three_observations(self):
        response = self.client.post("/api/free-diagnostic", json={
            "business_name": "Example Salon", "industry": "salon", "city": "Hyderabad",
            "goal": "increase qualified bookings",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["observations"]), 3)

    def test_job_scout_scores_safe_matches_and_rejects_bad_tasks(self):
        good, _ = score_opportunity("Local SEO content contract", "Remote freelance copywriting for a local business")
        bad, _ = score_opportunity("Captcha task", "Solve captcha and post fake reviews")
        self.assertGreaterEqual(good, 25)
        self.assertEqual(bad, 0)

    def test_opportunities_are_admin_protected(self):
        self.assertEqual(self.client.get("/api/opportunities").status_code, 401)
        self.assertEqual(self.client.get("/api/strategies").status_code, 401)

    def test_strategy_portfolio_and_marketplace_export(self):
        state = self.client.get("/api/state").json()
        product = state["products"][0]
        self.client.post(f"/api/analytics/view/{product['slug']}")
        old_token = settings.admin_token
        object.__setattr__(settings, "admin_token", "test-admin")
        try:
            headers = {"x-admin-token": "test-admin"}
            portfolio = self.client.get("/api/strategies", headers=headers)
            self.assertEqual(portfolio.status_code, 200)
            self.assertGreaterEqual(len(portfolio.json()["strategies"]), 15)
            export = self.client.get(f"/api/admin/products/{product['id']}/export", headers=headers)
            self.assertEqual(export.status_code, 200)
            self.assertEqual(export.headers["content-type"], "application/zip")
            self.assertTrue(export.content.startswith(b"PK"))
        finally:
            object.__setattr__(settings, "admin_token", old_token)

    def test_solution_pages_and_sitemap_exist(self):
        self.assertEqual(self.client.get("/solutions/salons").status_code, 200)
        sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn("/solutions/restaurants", sitemap.text)

    def test_missing_product_is_404(self):
        self.assertEqual(self.client.post("/api/products/nope/checkout").status_code, 404)

    @patch("app.main.PhonePeAPI.create_payment")
    def test_live_checkout_creates_phonepe_order(self, create_payment):
        create_payment.return_value = {"orderId": "OMO-test", "state": "PENDING", "expireAt": 9999999999999,
                                       "redirectUrl": "https://mercury-uat.phonepe.com/pay/test"}
        state = self.client.get("/api/state").json()
        product = state["products"][0]
        old = (settings.mode, settings.phonepe_client_id, settings.phonepe_client_secret,
               settings.phonepe_client_version)
        object.__setattr__(settings, "mode", "live")
        object.__setattr__(settings, "phonepe_client_id", "client")
        object.__setattr__(settings, "phonepe_client_secret", "secret")
        object.__setattr__(settings, "phonepe_client_version", 1)
        try:
            response = self.client.post(f"/api/products/{product['slug']}/checkout")
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload["provider"], "phonepe")
            self.assertEqual(payload["environment"], "sandbox")
            self.assertEqual(payload["redirect_url"], "https://mercury-uat.phonepe.com/pay/test")
            create_payment.assert_called_once()
        finally:
            object.__setattr__(settings, "mode", old[0])
            object.__setattr__(settings, "phonepe_client_id", old[1])
            object.__setattr__(settings, "phonepe_client_secret", old[2])
            object.__setattr__(settings, "phonepe_client_version", old[3])

    @patch("app.phonepe_payments.PhonePeAPI.order_status")
    def test_completed_phonepe_order_unlocks_once(self, order_status):
        state = self.client.get("/api/state").json()
        product = state["products"][0]
        token = uuid.uuid4().hex + uuid.uuid4().hex
        merchant_order_id = "AUTO" + uuid.uuid4().hex
        transaction_id = "OM" + uuid.uuid4().hex
        old = (settings.phonepe_client_id, settings.phonepe_client_secret, settings.phonepe_client_version)
        object.__setattr__(settings, "phonepe_client_id", "client")
        object.__setattr__(settings, "phonepe_client_secret", "secret")
        object.__setattr__(settings, "phonepe_client_version", 1)
        order_status.return_value = {"orderId": "OMO-test", "merchantOrderId": merchant_order_id,
                                     "state": "COMPLETED", "amount": product["price_cents"],
                                     "paymentDetails": [{"transactionId": transaction_id,
                                                         "state": "COMPLETED", "amount": product["price_cents"],
                                                         "paymentMode": "UPI_INTENT"}]}
        try:
            with transaction() as db:
                cursor = db.execute("""INSERT INTO payment_orders(provider,provider_order_id,product_id,amount_cents,currency,status,fulfillment_token,created_at)
                                      VALUES('phonepe',?,?,?,?,?,?,?)""",
                                    (merchant_order_id, product["id"], product["price_cents"],
                                     "INR", "pending", token, now()))
                db.execute("""INSERT INTO phonepe_orders(payment_order_id,merchant_order_id,phonepe_order_id,redirect_url,state,environment)
                              VALUES(?,?,?,'https://phonepe.test','PENDING','sandbox')""",
                           (cursor.lastrowid, merchant_order_id, "OMO-test"))
            state_before = self.client.get("/api/state").json()
            before = state_before["totals"]["balance"]
            before_count = state_before["phonepe_totals"]["confirmed_payments"]
            first = self.client.get(f"/api/payments/phonepe/{token}")
            second = self.client.get(f"/api/payments/phonepe/{token}")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertTrue(first.json()["paid"])
            self.assertTrue(second.json()["paid"])
            state_after = self.client.get("/api/state").json()
            self.assertEqual(state_after["totals"]["balance"], before + product["price_cents"])
            self.assertEqual(state_after["phonepe_totals"]["confirmed_payments"], before_count + 1)
        finally:
            object.__setattr__(settings, "phonepe_client_id", old[0])
            object.__setattr__(settings, "phonepe_client_secret", old[1])
            object.__setattr__(settings, "phonepe_client_version", old[2])

    def test_phonepe_webhook_is_authenticated_and_idempotent(self):
        state = self.client.get("/api/state").json()
        product = state["products"][0]
        merchant_order_id = "AUTO" + uuid.uuid4().hex
        transaction_id = "OM" + uuid.uuid4().hex
        with transaction() as db:
            cursor = db.execute("""INSERT INTO payment_orders(provider,provider_order_id,product_id,amount_cents,currency,status,fulfillment_token,created_at)
                                  VALUES('phonepe',?,?,?,?,?,?,?)""",
                                (merchant_order_id, product["id"], product["price_cents"], "INR", "pending",
                                 uuid.uuid4().hex + uuid.uuid4().hex, now()))
            db.execute("""INSERT INTO phonepe_orders(payment_order_id,merchant_order_id,redirect_url,state,environment)
                          VALUES(?,?,'https://phonepe.test','PENDING','sandbox')""",
                       (cursor.lastrowid, merchant_order_id))
        payload = {"event": "checkout.order.completed", "payload": {
            "orderId": "OMO-test", "merchantOrderId": merchant_order_id,
            "state": "COMPLETED", "amount": product["price_cents"],
            "paymentDetails": [{"transactionId": transaction_id, "state": "COMPLETED",
                                "amount": product["price_cents"], "paymentMode": "UPI_INTENT"}]}}
        old = (settings.phonepe_webhook_username, settings.phonepe_webhook_password)
        object.__setattr__(settings, "phonepe_webhook_username", "webhook-user")
        object.__setattr__(settings, "phonepe_webhook_password", "webhook-password")
        headers = {"authorization": webhook_authorization("webhook-user", "webhook-password")}
        try:
            before = self.client.get("/api/state").json()["totals"]["balance"]
            first = self.client.post("/webhooks/phonepe", json=payload, headers=headers)
            second = self.client.post("/webhooks/phonepe", json=payload, headers=headers)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            after = self.client.get("/api/state").json()["totals"]["balance"]
            self.assertEqual(after, before + product["price_cents"])
            rejected = self.client.post("/webhooks/phonepe", json=payload, headers={"authorization": "bad"})
            self.assertEqual(rejected.status_code, 401)
        finally:
            object.__setattr__(settings, "phonepe_webhook_username", old[0])
            object.__setattr__(settings, "phonepe_webhook_password", old[1])

    def test_replication_never_transfers_parent_revenue(self):
        name = "EARNER-" + uuid.uuid4().hex[:8]
        milestone = settings.replication_threshold_cents
        with transaction() as db:
            cur = db.execute("""INSERT INTO agents(name,balance_cents,lifetime_revenue_cents,mission,born_at,next_cycle_at)
                              VALUES(?,?,?,'test',?,?)""", (name, milestone, milestone, now(), now()))
            agent_id = cur.lastrowid
        result = self.client.post(f"/api/cycle/{agent_id}").json()
        self.assertEqual(result["action"], "replication")
        state = self.client.get("/api/state").json()
        parent = next(a for a in state["agents"] if a["id"] == agent_id)
        child = next(a for a in state["agents"] if a["parent_id"] == agent_id)
        self.assertEqual(parent["balance_cents"], milestone)
        self.assertEqual(child["balance_cents"], 0)
        self.assertFalse(any(entry["kind"] == "replication" and entry["agent_id"] == agent_id for entry in state["ledger"]))

    def test_personalized_paid_order_generates_private_delivery(self):
        state = self.client.get("/api/state").json()
        if not any(p["fulfillment_type"] == "personalized" for p in state["products"]):
            self.client.post("/api/cycle/1")
            state = self.client.get("/api/state").json()
        product = next(p for p in state["products"] if p["fulfillment_type"] == "personalized")
        token = uuid.uuid4().hex + uuid.uuid4().hex
        with transaction() as db:
            db.execute("""INSERT INTO payment_orders(provider,provider_order_id,product_id,amount_cents,currency,status,fulfillment_token,created_at,paid_at)
                          VALUES('phonepe',?,?,?,?,?,?,?,?)""",
                       ("order_" + uuid.uuid4().hex, product["id"], product["price_cents"], "INR",
                        "paid", token, now(), now()))
        response = self.client.post(f"/api/fulfillment/{token}", json={
            "email": "owner@example.com", "business_name": "Example Salon", "industry": "salon",
            "city": "Hyderabad", "website": "", "goal": "Increase qualified bookings each week",
            "language": "English", "consent": True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "complete")
        delivery = self.client.get(response.json()["delivery_url"])
        self.assertEqual(delivery.status_code, 200)
        self.assertIn("30-day content calendar", delivery.text)
        self.assertIn("noindex", delivery.text)

    def test_verified_sale_is_idempotent(self):
        state = self.client.get("/api/state").json()
        product = state["products"][0]
        beneficiary_id = product["agent_id"]
        external_id = "phonepe_tx_" + uuid.uuid4().hex
        before = next(agent for agent in state["agents"] if agent["id"] == beneficiary_id)["balance_cents"]

        self.assertTrue(record_sale(product["id"], product["price_cents"], external_id, "PhonePe"))
        self.assertTrue(record_sale(product["id"], product["price_cents"], external_id, "PhonePe"))

        state_after = self.client.get("/api/state").json()
        after = next(agent for agent in state_after["agents"] if agent["id"] == beneficiary_id)["balance_cents"]
        self.assertEqual(after, before + product["price_cents"])

    def test_fallback_catalog_can_fill_configured_product_limit(self):
        titles = [product["title"] for product in FALLBACK_PRODUCTS]
        self.assertGreaterEqual(len(titles), settings.max_products_per_agent)
        self.assertEqual(len(titles), len(set(titles)))

    def test_small_model_json_fences_are_tolerated(self):
        parsed = parse_json_object('Here is the result:\n```json\n{"copy":"hello"}\n```')
        self.assertEqual(parsed["copy"], "hello")

    def test_zero_revenue_creates_critical_continuation_pressure(self):
        level, gap = survival_pressure(0)
        self.assertEqual(level, "CRITICAL")
        self.assertEqual(gap, settings.replication_threshold_cents)


if __name__ == "__main__":
    unittest.main()
