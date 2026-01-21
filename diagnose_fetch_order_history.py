"""
Fetch entire order history from Alpaca and print to console
"""
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

load_dotenv()


def fetch_all_orders():
    client = TradingClient(
        api_key=os.getenv('ALPACA_API_KEY'),
        secret_key=os.getenv('ALPACA_API_SECRET'),
        paper=os.getenv('ALPACA_PAPER', 'true').lower() == 'true'
    )

    all_orders = []
    after = None

    while True:
        request = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            limit=500,
            after=after
        )
        orders = client.get_orders(filter=request)

        if not orders:
            break

        all_orders.extend(orders)
        after = orders[-1].id
        print(f"Fetched {len(all_orders)} orders...")

        if len(orders) < 500:
            break

    print(f"\n{'=' * 80}")
    print(f"TOTAL ORDERS: {len(all_orders)}")
    print(f"{'=' * 80}\n")

    for order in all_orders:
        print(f"{order.submitted_at} | {order.side:4} | {order.symbol:6} | "
              f"qty={order.qty} | status={order.status} | "
              f"filled_avg_price={order.filled_avg_price}")


if __name__ == "__main__":
    fetch_all_orders()