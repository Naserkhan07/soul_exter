import unittest
from unittest.mock import MagicMock, patch


class DatabaseConnectionTests(unittest.TestCase):
    @patch("app.db.connect")
    def test_rows_always_closes_read_connection(self, connect):
        from app.db import rows
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [{"value": 1}]
        connect.return_value = db

        self.assertEqual(rows("SELECT 1"), [{"value": 1}])

        db.close.assert_called_once_with()

    @patch("app.db.connect")
    def test_row_always_closes_read_connection(self, connect):
        from app.db import row
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"value": 1}
        connect.return_value = db

        self.assertEqual(row("SELECT 1"), {"value": 1})

        db.close.assert_called_once_with()

    @patch("app.db.connect")
    def test_read_connection_closes_when_query_fails(self, connect):
        from app.db import rows
        db = MagicMock()
        db.execute.side_effect = RuntimeError("query failed")
        connect.return_value = db

        with self.assertRaises(RuntimeError):
            rows("BROKEN")

        db.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
