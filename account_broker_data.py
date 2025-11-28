# =============================================================================
# REPLACEMENT CODE FOR account_broker_data.py
# =============================================================================
# Replace the following functions in your account_broker_data.py file:
# 1. get_broker_entry_price() - Updated to handle Lumibot positions better
# 2. get_position_quantity() - Updated to handle both qty and quantity
# 3. is_valid_stock_position() - NEW function to filter out USD and non-stocks
# =============================================================================
from typing import Any, Tuple


# List of symbols to skip (not tradeable stock positions)
SKIP_SYMBOLS = {'USD', 'USDT', 'USDC', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD'}


def is_valid_stock_position(position, ticker: str = "") -> bool:
    """
    Check if this is a valid stock position (not cash/forex/quote asset).

    Lumibot may include USD as a "position" representing cash/quote asset.
    This function filters those out.

    Args:
        position: Broker position object
        ticker: Ticker symbol

    Returns:
        bool: True if valid stock position, False if should be skipped
    """
    # Get symbol from position or use provided ticker
    symbol = ticker
    if not symbol:
        if hasattr(position, 'symbol'):
            symbol = position.symbol
        elif hasattr(position, 'asset') and hasattr(position.asset, 'symbol'):
            symbol = position.asset.symbol

    if not symbol:
        return False

    symbol = symbol.upper()

    # Skip known non-stock symbols (cash, forex, stablecoins)
    if symbol in SKIP_SYMBOLS:
        return False

    # Check asset_type if available (Lumibot positions have this)
    if hasattr(position, 'asset') and position.asset:
        asset_type = getattr(position.asset, 'asset_type', None)
        if asset_type:
            asset_type_str = str(asset_type).lower()
            # Only allow stocks/equities
            if 'forex' in asset_type_str or 'crypto' in asset_type_str:
                return False

    # Check asset_class if available (Alpaca positions have this)
    if hasattr(position, 'asset_class'):
        asset_class = str(position.asset_class).lower()
        if 'us_equity' not in asset_class and 'stock' not in asset_class:
            # Could be crypto, forex, etc.
            if 'crypto' in asset_class or 'forex' in asset_class:
                return False

    return True


def get_broker_entry_price(position: Any, strategy: Any = None, ticker: str = "") -> float:
    """
    Extract entry price from broker position object.

    Handles both:
    - Direct Alpaca API positions (avg_entry_price, cost_basis)
    - Lumibot wrapped positions (avg_fill_price)

    Tries multiple attributes in order of preference:
    1. avg_entry_price (Alpaca direct)
    2. cost_basis / quantity (Alpaca calculation)
    3. cost_basis / qty (Alpaca alternate)
    4. avg_fill_price (Lumibot)

    Returns 0.0 if no valid entry price found - position will be flagged for manual review.

    Args:
        position: Broker position object
        strategy: Strategy instance (optional, can be used for price lookup fallback)
        ticker: Ticker symbol (optional, for logging)

    Returns:
        float: Entry price, or 0.0 if unable to determine
    """
    # First check if this is a valid stock position
    if not is_valid_stock_position(position, ticker):
        # Silently skip non-stock positions (USD, etc.)
        return 0.0

    # Try avg_entry_price first (Alpaca direct API)
    if hasattr(position, 'avg_entry_price') and position.avg_entry_price:
        try:
            price = float(position.avg_entry_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # Try cost_basis / quantity (alpaca-trade-api format with 'quantity')
    if hasattr(position, 'cost_basis') and hasattr(position, 'quantity'):
        try:
            cost_basis = float(position.cost_basis)
            quantity = float(position.quantity)
            if quantity > 0 and cost_basis > 0:
                price = cost_basis / quantity
                if price > 0:
                    return price
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # Try cost_basis / qty (alpaca-trade-api format with 'qty')
    if hasattr(position, 'cost_basis') and hasattr(position, 'qty'):
        try:
            cost_basis = float(position.cost_basis)
            qty = float(position.qty)
            if qty > 0 and cost_basis > 0:
                price = cost_basis / qty
                if price > 0:
                    return price
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # Try avg_fill_price (Lumibot Position object)
    if hasattr(position, 'avg_fill_price') and position.avg_fill_price:
        try:
            price = float(position.avg_fill_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # Try current_price as last resort (better than 0)
    if hasattr(position, 'current_price') and position.current_price:
        try:
            price = float(position.current_price)
            if price > 0:
                if ticker:
                    print(f"[WARN] {ticker} - Using current_price as fallback entry price: ${price:.2f}")
                return price
        except (ValueError, TypeError):
            pass

    # Try to get price from strategy if available
    if strategy and ticker:
        try:
            price = strategy.get_last_price(ticker)
            if price and price > 0:
                print(f"[WARN] {ticker} - Using live price as fallback entry price: ${price:.2f}")
                return float(price)
        except:
            pass

    # No valid entry price found - return 0.0 for manual review
    if ticker:
        print(f"[ERROR] {ticker} - Could not determine entry price, flagging for manual review")

    return 0.0


def get_position_quantity(position: Any, ticker: str = "") -> int:
    """
    Extract quantity from broker position object.

    Handles both:
    - Alpaca positions (qty)
    - Lumibot positions (quantity)

    Args:
        position: Broker position object
        ticker: Ticker symbol (for logging)

    Returns:
        int: Position quantity, or 0 if unable to determine
    """
    # First check if this is a valid stock position
    if not is_valid_stock_position(position, ticker):
        # Silently skip non-stock positions (USD, etc.)
        return 0

    # Try 'quantity' first (Lumibot format)
    if hasattr(position, 'quantity'):
        try:
            qty = int(float(position.quantity))
            if qty > 0:
                return qty
            elif qty < 0:
                # Handle short positions (convert to positive)
                return abs(qty)
        except (ValueError, TypeError):
            pass

    # Try 'qty' (Alpaca format)
    if hasattr(position, 'qty'):
        try:
            qty = int(float(position.qty))
            if qty > 0:
                return qty
            elif qty < 0:
                return abs(qty)
        except (ValueError, TypeError):
            pass

    if ticker:
        print(f"[ERROR] {ticker} - Could not extract quantity from position")

    return 0


def validate_entry_price(entry_price: float, ticker: str = "", min_price: float = 0.01) -> bool:
    """
    Validate that entry price is reasonable.

    Args:
        entry_price: Entry price to validate
        ticker: Ticker symbol (for logging)
        min_price: Minimum acceptable price (default $0.01)

    Returns:
        bool: True if valid, False otherwise
    """
    # Skip validation for non-stock symbols (they return 0.0 intentionally)
    if ticker and ticker.upper() in SKIP_SYMBOLS:
        return False

    if entry_price <= 0:
        if ticker:
            print(f"[ERROR] {ticker} - Invalid entry price: ${entry_price:.2f} (must be > 0)")
        return False

    if entry_price < min_price:
        if ticker:
            print(f"[WARN] {ticker} - Entry price ${entry_price:.2f} below minimum ${min_price:.2f}")
        return False

    return True