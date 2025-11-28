"""
Trading Window Configuration and Broker Data Utilities

Handles:
- Trading window times and validation
- Market holiday detection
- Trading frequency controls
- Broker position utilities (entry price extraction, validation)
- Direct Alpaca API integration for reliable position data

IMPORTANT: This module bypasses Lumibot for position data when needed,
calling Alpaca's REST API directly to get accurate entry prices.
"""

from datetime import time, date
from typing import Any, Tuple, Dict, Optional
import os
import pytz
from config import Config

# =============================================================================
# TRADING WINDOW CONFIGURATION
# =============================================================================

TRADING_START_TIME = time(10, 0)  # 10:00 AM EST
TRADING_END_TIME = time(16, 0)  # 4:00 PM EST

# =============================================================================
# US MARKET HOLIDAYS (2025)
# =============================================================================

US_MARKET_HOLIDAYS_2025 = {
    date(2025, 1, 1),  # New Year's Day
    date(2025, 1, 20),  # Martin Luther King Jr. Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),  # Independence Day
    date(2025, 9, 1),  # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
}

# =============================================================================
# SYMBOLS TO SKIP (not tradeable stock positions)
# =============================================================================

SKIP_SYMBOLS = {'USD', 'USDT', 'USDC', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD'}

# =============================================================================
# DIRECT ALPACA API - POSITION CACHE
# =============================================================================

# Cache for position data from direct Alpaca API calls
_alpaca_position_cache: Dict[str, dict] = {}
_cache_initialized: bool = False


def _get_alpaca_api():
    """
    Get Alpaca REST API client.

    Returns:
        alpaca_trade_api.REST: Alpaca API client, or None if unavailable
    """
    if Config.BACKTESTING:
        return None

    try:
        import alpaca_trade_api as tradeapi

        api_key = os.getenv('ALPACA_API_KEY') or getattr(Config, 'ALPACA_API_KEY', None)
        api_secret = os.getenv('ALPACA_API_SECRET') or getattr(Config, 'ALPACA_API_SECRET', None)

        # Determine if paper trading
        paper_env = os.getenv('ALPACA_PAPER', 'True').lower() == 'true'
        paper_config = getattr(Config, 'ALPACA_PAPER', True)
        is_paper = paper_env if os.getenv('ALPACA_PAPER') else paper_config

        base_url = 'https://paper-api.alpaca.markets' if is_paper else 'https://api.alpaca.markets'

        return tradeapi.REST(api_key, api_secret, base_url)

    except ImportError:
        print("[ERROR] alpaca_trade_api not installed. Run: pip install alpaca-trade-api")
        return None
    except Exception as e:
        print(f"[ERROR] Failed to create Alpaca API client: {e}")
        return None


def refresh_position_cache() -> Dict[str, dict]:
    """
    Refresh position cache by calling Alpaca API directly.

    Call this at the start of each trading iteration for best performance.
    This bypasses Lumibot and gets accurate position data directly from Alpaca.

    Returns:
        dict: {symbol: {qty, avg_entry_price, cost_basis, current_price, ...}}
    """
    global _alpaca_position_cache, _cache_initialized

    if Config.BACKTESTING:
        _cache_initialized = True
        return {}

    api = _get_alpaca_api()
    if not api:
        print("[WARN] Could not refresh position cache - Alpaca API unavailable")
        _cache_initialized = True
        return _alpaca_position_cache

    try:
        positions = api.list_positions()

        _alpaca_position_cache = {}
        for pos in positions:
            symbol = pos.symbol

            # Skip non-stock symbols
            if symbol.upper() in SKIP_SYMBOLS:
                continue

            _alpaca_position_cache[symbol] = {
                'qty': int(float(pos.qty)),
                'avg_entry_price': float(pos.avg_entry_price),
                'cost_basis': float(pos.cost_basis),
                'current_price': float(pos.current_price),
                'market_value': float(pos.market_value),
                'unrealized_pl': float(pos.unrealized_pl),
                'unrealized_plpc': float(pos.unrealized_plpc) * 100,  # Convert to percentage
                'asset_class': str(getattr(pos, 'asset_class', 'us_equity')),
            }

        _cache_initialized = True

        if _alpaca_position_cache:
            print(f"[ALPACA] Refreshed position cache: {len(_alpaca_position_cache)} positions")
            for symbol, data in _alpaca_position_cache.items():
                print(f"   {symbol}: {data['qty']} shares @ ${data['avg_entry_price']:.2f}")

        return _alpaca_position_cache

    except Exception as e:
        print(f"[ERROR] Failed to refresh position cache from Alpaca: {e}")
        _cache_initialized = True
        return _alpaca_position_cache


def get_cached_position(ticker: str) -> Optional[dict]:
    """
    Get cached position data for a ticker.

    Args:
        ticker: Stock symbol

    Returns:
        dict: Position data or None if not found
    """
    global _alpaca_position_cache, _cache_initialized

    if Config.BACKTESTING:
        return None

    if not _cache_initialized:
        refresh_position_cache()

    return _alpaca_position_cache.get(ticker.upper())


def get_cached_entry_price(ticker: str) -> float:
    """
    Get cached entry price for a ticker.

    Args:
        ticker: Stock symbol

    Returns:
        float: Entry price or 0.0 if not found
    """
    position = get_cached_position(ticker)
    if position:
        return position.get('avg_entry_price', 0.0)
    return 0.0


def get_cached_quantity(ticker: str) -> int:
    """
    Get cached quantity for a ticker.

    Args:
        ticker: Stock symbol

    Returns:
        int: Quantity or 0 if not found
    """
    position = get_cached_position(ticker)
    if position:
        return position.get('qty', 0)
    return 0


def get_all_cached_positions() -> Dict[str, dict]:
    """
    Get all cached positions.

    Returns:
        dict: {symbol: position_data}
    """
    global _alpaca_position_cache, _cache_initialized

    if not _cache_initialized:
        refresh_position_cache()

    return _alpaca_position_cache.copy()


def clear_position_cache():
    """Clear the position cache. Call when positions change."""
    global _alpaca_position_cache, _cache_initialized
    _alpaca_position_cache = {}
    _cache_initialized = False


def get_position_direct(ticker: str) -> Optional[dict]:
    """
    Get position data directly from Alpaca API (not cached).

    Use this when you need real-time data, not cached data.

    Args:
        ticker: Stock symbol

    Returns:
        dict: Position data or None if not found/error
    """
    if Config.BACKTESTING:
        return None

    api = _get_alpaca_api()
    if not api:
        return None

    try:
        pos = api.get_position(ticker.upper())
        return {
            'qty': int(float(pos.qty)),
            'avg_entry_price': float(pos.avg_entry_price),
            'cost_basis': float(pos.cost_basis),
            'current_price': float(pos.current_price),
            'market_value': float(pos.market_value),
            'unrealized_pl': float(pos.unrealized_pl),
            'unrealized_plpc': float(pos.unrealized_plpc) * 100,
        }
    except Exception as e:
        # Position might not exist
        return None


# =============================================================================
# MARKET HOLIDAY FUNCTIONS
# =============================================================================

def is_market_holiday(check_date) -> bool:
    """
    Check if date is a US market holiday.

    Args:
        check_date: datetime.date object

    Returns:
        bool: True if holiday, False otherwise
    """
    if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return True
    return check_date in US_MARKET_HOLIDAYS_2025


# =============================================================================
# TRADING WINDOW FUNCTIONS
# =============================================================================

def is_within_trading_window(strategy) -> bool:
    """
    Check if current time is within trading window.

    Args:
        strategy: Lumibot Strategy instance

    Returns:
        bool: True if within trading window, False otherwise
    """
    if Config.BACKTESTING:
        return True

    try:
        est = pytz.timezone('US/Eastern')
        current_datetime_est = strategy.get_datetime().astimezone(est)
        current_time_est = current_datetime_est.time()
        current_date = current_datetime_est.date()

        if is_market_holiday(current_date):
            day_name = current_datetime_est.strftime('%A')
            print(f"[INFO] Market closed - {day_name}, {current_date} is a holiday/weekend")
            return False

        is_within = TRADING_START_TIME <= current_time_est <= TRADING_END_TIME

        if not is_within:
            if current_time_est < TRADING_START_TIME:
                print(f"[INFO] Before trading window (current: {current_time_est.strftime('%I:%M %p')} EST, "
                      f"window opens at {TRADING_START_TIME.strftime('%I:%M %p')} EST)")
            else:
                print(f"[INFO] After trading window (current: {current_time_est.strftime('%I:%M %p')} EST, "
                      f"window closed at {TRADING_END_TIME.strftime('%I:%M %p')} EST)")

        return is_within

    except Exception as e:
        print(f"[WARN] Could not check trading window: {e}")
        return False


def has_traded_today(strategy, last_trade_date) -> bool:
    """
    Check if strategy has already traded today.

    Args:
        strategy: Lumibot Strategy instance
        last_trade_date: Last date trading occurred (date object)

    Returns:
        bool: True if already traded today, False otherwise
    """
    if Config.BACKTESTING:
        return False

    current_date = strategy.get_datetime().date()

    if last_trade_date == current_date:
        print(f"[INFO] Already traded today ({current_date}) - skipping iteration")
        return True

    return False


def get_trading_window_info() -> dict:
    """
    Get trading window configuration info.

    Returns:
        dict: Trading window details
    """
    return {
        'start_time': TRADING_START_TIME,
        'end_time': TRADING_END_TIME,
        'start_time_str': TRADING_START_TIME.strftime('%I:%M %p'),
        'end_time_str': TRADING_END_TIME.strftime('%I:%M %p'),
        'timezone': 'US/Eastern'
    }


def print_trading_window_info():
    """Print trading window information."""
    info = get_trading_window_info()
    print(f"\n{'=' * 80}")
    print(f"⏰ TRADING WINDOW CONFIGURATION")
    print(f"{'=' * 80}")
    print(f"Start Time: {info['start_time_str']} {info['timezone']}")
    print(f"End Time:   {info['end_time_str']} {info['timezone']}")
    print(f"Duration:   {(TRADING_END_TIME.hour - TRADING_START_TIME.hour)} hours")
    print(f"Frequency:  Once per day")
    print(f"{'=' * 80}\n")


# =============================================================================
# POSITION VALIDATION
# =============================================================================

def is_valid_stock_position(position, ticker: str = "") -> bool:
    """
    Check if this is a valid stock position (not cash/forex/quote asset).

    Args:
        position: Broker position object
        ticker: Ticker symbol

    Returns:
        bool: True if valid stock position, False if should be skipped
    """
    symbol = ticker
    if not symbol:
        if hasattr(position, 'symbol'):
            symbol = position.symbol
        elif hasattr(position, 'asset') and hasattr(position.asset, 'symbol'):
            symbol = position.asset.symbol

    if not symbol:
        return False

    symbol = symbol.upper()

    # Skip known non-stock symbols
    if symbol in SKIP_SYMBOLS:
        return False

    # Check asset_type (Lumibot)
    if hasattr(position, 'asset') and position.asset:
        asset_type = getattr(position.asset, 'asset_type', None)
        if asset_type:
            asset_type_str = str(asset_type).lower()
            if 'forex' in asset_type_str or 'crypto' in asset_type_str:
                return False

    # Check asset_class (Alpaca)
    if hasattr(position, 'asset_class'):
        asset_class = str(position.asset_class).lower()
        if 'crypto' in asset_class or 'forex' in asset_class:
            return False

    return True


# =============================================================================
# BROKER POSITION UTILITIES
# =============================================================================

def get_broker_entry_price(position: Any, strategy: Any = None, ticker: str = "") -> float:
    """
    Extract entry price from broker position object.

    Priority order:
    1. Direct Alpaca cache (most reliable)
    2. Position object attributes (avg_entry_price, cost_basis)
    3. Lumibot attributes (avg_fill_price)
    4. Current price fallback

    Args:
        position: Broker position object
        strategy: Strategy instance (optional)
        ticker: Ticker symbol (optional, for logging)

    Returns:
        float: Entry price, or 0.0 if unable to determine
    """
    # Skip non-stock symbols
    if not is_valid_stock_position(position, ticker):
        return 0.0

    # Get ticker if not provided
    if not ticker:
        if hasattr(position, 'symbol'):
            ticker = position.symbol
        elif hasattr(position, 'asset') and hasattr(position.asset, 'symbol'):
            ticker = position.asset.symbol

    # === PRIORITY 1: Direct Alpaca cache (most reliable) ===
    if ticker and not Config.BACKTESTING:
        cached_price = get_cached_entry_price(ticker)
        if cached_price > 0:
            return cached_price

    # === PRIORITY 2: Position object attributes ===

    # Try avg_entry_price (Alpaca)
    if hasattr(position, 'avg_entry_price') and position.avg_entry_price:
        try:
            price = float(position.avg_entry_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # Try cost_basis / quantity
    if hasattr(position, 'cost_basis') and hasattr(position, 'quantity'):
        try:
            cost_basis = float(position.cost_basis)
            quantity = float(position.quantity)
            if quantity > 0 and cost_basis > 0:
                return cost_basis / quantity
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # Try cost_basis / qty
    if hasattr(position, 'cost_basis') and hasattr(position, 'qty'):
        try:
            cost_basis = float(position.cost_basis)
            qty = float(position.qty)
            if qty > 0 and cost_basis > 0:
                return cost_basis / qty
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # === PRIORITY 3: Lumibot attributes ===

    # Try avg_fill_price (Lumibot)
    if hasattr(position, 'avg_fill_price') and position.avg_fill_price:
        try:
            price = float(position.avg_fill_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # === PRIORITY 4: Direct API call (if cache miss) ===
    if ticker and not Config.BACKTESTING:
        direct_pos = get_position_direct(ticker)
        if direct_pos and direct_pos.get('avg_entry_price', 0) > 0:
            return direct_pos['avg_entry_price']

    # === PRIORITY 5: Current price fallback ===
    if hasattr(position, 'current_price') and position.current_price:
        try:
            price = float(position.current_price)
            if price > 0:
                if ticker:
                    print(f"[WARN] {ticker} - Using current_price as fallback: ${price:.2f}")
                return price
        except (ValueError, TypeError):
            pass

    # Try strategy.get_last_price
    if strategy and ticker:
        try:
            price = strategy.get_last_price(ticker)
            if price and price > 0:
                print(f"[WARN] {ticker} - Using live price as fallback: ${price:.2f}")
                return float(price)
        except:
            pass

    if ticker:
        print(f"[ERROR] {ticker} - Could not determine entry price")

    return 0.0


def get_position_quantity(position: Any, ticker: str = "") -> int:
    """
    Extract quantity from broker position object.

    Priority order:
    1. Direct Alpaca cache
    2. Position object attributes (quantity, qty)

    Args:
        position: Broker position object
        ticker: Ticker symbol (for logging)

    Returns:
        int: Position quantity, or 0 if unable to determine
    """
    # Skip non-stock symbols
    if not is_valid_stock_position(position, ticker):
        return 0

    # Get ticker if not provided
    if not ticker:
        if hasattr(position, 'symbol'):
            ticker = position.symbol
        elif hasattr(position, 'asset') and hasattr(position.asset, 'symbol'):
            ticker = position.asset.symbol

    # === PRIORITY 1: Direct Alpaca cache ===
    if ticker and not Config.BACKTESTING:
        cached_qty = get_cached_quantity(ticker)
        if cached_qty > 0:
            return cached_qty

    # === PRIORITY 2: Position object attributes ===

    # Try 'quantity' (Lumibot)
    if hasattr(position, 'quantity'):
        try:
            qty = int(float(position.quantity))
            if qty != 0:
                return abs(qty)
        except (ValueError, TypeError):
            pass

    # Try 'qty' (Alpaca)
    if hasattr(position, 'qty'):
        try:
            qty = int(float(position.qty))
            if qty != 0:
                return abs(qty)
        except (ValueError, TypeError):
            pass

    # === PRIORITY 3: Direct API call ===
    if ticker and not Config.BACKTESTING:
        direct_pos = get_position_direct(ticker)
        if direct_pos and direct_pos.get('qty', 0) > 0:
            return direct_pos['qty']

    if ticker:
        print(f"[ERROR] {ticker} - Could not extract quantity")

    return 0


def validate_entry_price(entry_price: float, ticker: str = "", min_price: float = 0.01) -> bool:
    """
    Validate that entry price is reasonable.

    Args:
        entry_price: Entry price to validate
        ticker: Ticker symbol (for logging)
        min_price: Minimum acceptable price

    Returns:
        bool: True if valid, False otherwise
    """
    if ticker and ticker.upper() in SKIP_SYMBOLS:
        return False

    if entry_price <= 0:
        if ticker:
            print(f"[ERROR] {ticker} - Invalid entry price: ${entry_price:.2f}")
        return False

    if entry_price < min_price:
        if ticker:
            print(f"[WARN] {ticker} - Entry price ${entry_price:.2f} below minimum ${min_price:.2f}")
        return False

    return True


# =============================================================================
# P&L UTILITIES
# =============================================================================

def calculate_position_pnl(entry_price: float, current_price: float, quantity: int) -> Tuple[float, float]:
    """
    Calculate position P&L.

    Args:
        entry_price: Entry price per share
        current_price: Current price per share
        quantity: Number of shares

    Returns:
        tuple: (pnl_dollars, pnl_pct)
    """
    if entry_price <= 0 or quantity <= 0:
        return 0.0, 0.0

    pnl_per_share = current_price - entry_price
    pnl_dollars = pnl_per_share * quantity
    pnl_pct = (pnl_per_share / entry_price * 100)

    return pnl_dollars, pnl_pct


def format_price(price: float, decimals: int = 2) -> str:
    """Format price for display."""
    return f"${price:,.{decimals}f}"


def format_pnl(pnl_dollars: float, pnl_pct: float) -> str:
    """Format P&L for display with emoji."""
    emoji = "✅" if pnl_dollars > 0 else "❌"
    return f"{emoji} ${pnl_dollars:+,.2f} ({pnl_pct:+.1f}%)"


# =============================================================================
# ACCOUNT UTILITIES
# =============================================================================

def get_account_info() -> Optional[dict]:
    """
    Get account information directly from Alpaca.

    Returns:
        dict: Account info or None if unavailable
    """
    if Config.BACKTESTING:
        return None

    api = _get_alpaca_api()
    if not api:
        return None

    try:
        account = api.get_account()
        return {
            'equity': float(account.equity),
            'cash': float(account.cash),
            'buying_power': float(account.buying_power),
            'portfolio_value': float(account.portfolio_value),
            'pattern_day_trader': account.pattern_day_trader,
            'trading_blocked': account.trading_blocked,
            'account_blocked': account.account_blocked,
        }
    except Exception as e:
        print(f"[ERROR] Failed to get account info: {e}")
        return None