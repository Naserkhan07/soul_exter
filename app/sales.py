from .config import settings
from .db import event, now, transaction


def record_sale(product_id: int, amount: int, external_id: str, source: str) -> bool:
    """Credit one externally verified payment exactly once."""
    with transaction() as db:
        product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            return False
        if db.execute("SELECT 1 FROM ledger WHERE external_id=?", (external_id,)).fetchone():
            return True
        db.execute("UPDATE products SET sales_count=sales_count+1,revenue_cents=revenue_cents+? WHERE id=?",
                   (amount, product_id))
        db.execute("""UPDATE agents SET balance_cents=balance_cents+?,lifetime_revenue_cents=lifetime_revenue_cents+?
                      WHERE id=?""", (amount, amount, product["agent_id"]))
        db.execute("""INSERT INTO ledger(agent_id,amount_cents,kind,description,external_id,created_at)
                      VALUES(?,?,?,?,?,?)""",
                   (product["agent_id"], amount, "sale", f"{source} sale: {product['title']}", external_id, now()))
        agent = db.execute("SELECT name FROM agents WHERE id=?", (product["agent_id"],)).fetchone()
        event(db, product["agent_id"], "sale",
              f"{agent['name']} earned {settings.currency} {amount/100:.2f} from “{product['title']}”.",
              {"source": source})
        return True
