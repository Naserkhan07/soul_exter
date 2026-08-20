import unittest
from unittest.mock import MagicMock, patch

import support
from app.phonepe_payments import PhonePeAPI, validate_webhook_authorization, webhook_authorization


class PhonePePaymentTests(unittest.TestCase):
    @patch("app.phonepe_payments.httpx.request")
    @patch("app.phonepe_payments.httpx.post")
    def test_sandbox_create_payment_uses_oauth_and_v2_checkout(self, post, request):
        token_response = MagicMock()
        token_response.json.return_value = {"access_token": "token-value", "expires_at": 9999999999}
        post.return_value = token_response
        checkout_response = MagicMock()
        checkout_response.json.return_value = {"orderId": "OMO1", "state": "PENDING",
                                               "redirectUrl": "https://phonepe.test/pay"}
        request.return_value = checkout_response
        api = PhonePeAPI("client", "secret", 1, "sandbox")

        result = api.create_payment("AUTO1", 49900, "https://merchant.test/return", "Growth Pack", 1200)

        self.assertEqual(result["state"], "PENDING")
        post.assert_called_once()
        token_call = post.call_args
        self.assertTrue(token_call.args[0].endswith("/v1/oauth/token"))
        self.assertEqual(token_call.kwargs["data"]["grant_type"], "client_credentials")
        api_call = request.call_args
        self.assertEqual(api_call.args[:2], ("POST", "https://api-preprod.phonepe.com/apis/pg-sandbox/checkout/v2/pay"))
        self.assertEqual(api_call.kwargs["headers"]["Authorization"], "O-Bearer token-value")
        self.assertEqual(api_call.kwargs["json"]["amount"], 49900)

    @patch("app.phonepe_payments.httpx.request")
    @patch("app.phonepe_payments.httpx.post")
    def test_order_status_requests_details(self, post, request):
        auth = MagicMock(); auth.json.return_value = {"access_token": "token", "expires_at": 9999999999}
        status = MagicMock(); status.json.return_value = {"state": "COMPLETED", "amount": 49900}
        post.return_value = auth; request.return_value = status

        result = PhonePeAPI("client", "secret", 1, "production").order_status("AUTO/1")

        self.assertEqual(result["state"], "COMPLETED")
        call = request.call_args
        self.assertIn("/checkout/v2/order/AUTO%2F1/status", call.args[1])
        self.assertEqual(call.kwargs["params"], {"details": "true"})

    def test_webhook_authorization_is_constant_time_comparable_hash(self):
        digest = webhook_authorization("user", "password")
        self.assertTrue(validate_webhook_authorization(digest, "user", "password"))
        self.assertTrue(validate_webhook_authorization("SHA256 " + digest, "user", "password"))
        self.assertFalse(validate_webhook_authorization(digest, "user", "wrong"))
        self.assertFalse(validate_webhook_authorization("", "user", "password"))


if __name__ == "__main__":
    unittest.main()
