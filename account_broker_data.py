"""
Trading Window Configuration and Broker Data Utilities

Handles:
- Trading window times and validation
- Market holiday detection
- Trading frequency controls
- Broker position utilities (entry price extraction, validation)
- Direct Alpaca API integration for reliable position data
- Stock split detection and verification (forward and reverse)

IMPORTANT: This module bypasses Lumibot for position data when needed,
calling Alpaca's REST API directly to get accurate entry prices.
"""

from datetime import time, date, datetime, timedelta
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
# STOCK SPLIT TRACKER
# =============================================================================

class StockSplitTracker:
    """
    Tracks stock splits detected during trading sessions for reporting in:
    - Backtest final summary
    - Live trading logs
    - Daily email notifications

    Usage:
        from account_broker_data import split_tracker

        # Record a split
        split_tracker.record_split(
            ticker='NOW',
            split_type='forward',
            ratio=5.0,
            old_entry=720.00,
            new_entry=144.00,
            confidence='high',
            date=current_date
        )

        # Get all splits for reporting
        splits = split_tracker.get_splits()

        # Clear at start of new session/backtest
        split_tracker.clear()
    """

    def __init__(self):
        self.splits: list = []

    def record_split(
            self,
            ticker: str,
            split_type: str,
            ratio: float,
            old_entry: float,
            new_entry: float,
            confidence: str = 'medium',
            date: datetime = None,
            old_stop: float = None,
            new_stop: float = None,
            old_R: float = None,
            new_R: float = None
    ):
        """
        Record a detected stock split.

        Args:
            ticker: Stock symbol
            split_type: 'forward' or 'reverse'
            ratio: Split ratio (e.g., 5.0 for 5:1 forward split)
            old_entry: Entry price before adjustment
            new_entry: Entry price after adjustment
            confidence: 'high', 'medium', or 'low'
            date: Date split was detected
            old_stop: Stop price before adjustment (optional)
            new_stop: Stop price after adjustment (optional)
            old_R: R value before adjustment (optional)
            new_R: R value after adjustment (optional)
        """
        split_record = {
            'ticker': ticker,
            'split_type': split_type,
            'ratio': ratio,
            'old_entry': old_entry,
            'new_entry': new_entry,
            'confidence': confidence,
            'date': date or datetime.now(),
            'old_stop': old_stop,
            'new_stop': new_stop,
            'old_R': old_R,
            'new_R': new_R,
            'display_ratio': format_split_ratio(ratio)
        }

        self.splits.append(split_record)

        # Log immediately for live trading
        self._log_split(split_record)

    def _log_split(self, split: dict):
        """Log split detection to console"""
        confidence_emoji = {
            'high': '✅',
            'medium': '⚠️',
            'low': '❓'
        }.get(split['confidence'], '❓')

        print(f"\n{'=' * 60}")
        print(f"🔄 STOCK SPLIT DETECTED")
        print(f"{'=' * 60}")
        print(f"   Ticker: {split['ticker']}")
        print(f"   Type: {split['split_type'].upper()} SPLIT ({split['display_ratio']})")
        print(f"   Confidence: {confidence_emoji} {split['confidence'].upper()}")
        print(f"   Entry Price: ${split['old_entry']:.2f} → ${split['new_entry']:.2f}")

        if split.get('old_stop') and split.get('new_stop'):
            print(f"   Stop Price: ${split['old_stop']:.2f} → ${split['new_stop']:.2f}")

        if split.get('old_R') and split.get('new_R'):
            print(f"   R Value: ${split['old_R']:.2f} → ${split['new_R']:.2f}")

        if split['date']:
            print(f"   Date: {split['date'].strftime('%Y-%m-%d %H:%M')}")
        print(f"{'=' * 60}\n")

    def get_splits(self) -> list:
        """Get all recorded splits"""
        return self.splits.copy()

    def get_splits_for_date(self, date: datetime) -> list:
        """Get splits detected on a specific date"""
        target_date = date.date() if hasattr(date, 'date') else date
        return [
            s for s in self.splits
            if s['date'] and s['date'].date() == target_date
        ]

    def get_split_count(self) -> int:
        """Get total number of splits detected"""
        return len(self.splits)

    def get_splits_by_type(self) -> dict:
        """Get splits grouped by type"""
        forward = [s for s in self.splits if s['split_type'] == 'forward']
        reverse = [s for s in self.splits if s['split_type'] == 'reverse']
        return {'forward': forward, 'reverse': reverse}

    def has_splits(self) -> bool:
        """Check if any splits were detected"""
        return len(self.splits) > 0

    def clear(self):
        """Clear all recorded splits (call at start of new session)"""
        self.splits = []

    def get_summary_text(self) -> str:
        """Get text summary for logging"""
        if not self.splits:
            return "No stock splits detected."

        lines = [
            f"Stock Splits Detected: {len(self.splits)}",
            "-" * 40
        ]

        for split in self.splits:
            conf_emoji = '✅' if split['confidence'] == 'high' else '⚠️'
            lines.append(
                f"  {conf_emoji} {split['ticker']}: {split['split_type']} {split['display_ratio']} "
                f"(${split['old_entry']:.2f} → ${split['new_entry']:.2f})"
            )

        return "\n".join(lines)

    def generate_html_section(self) -> str:
        """Generate HTML for email/report"""
        if not self.splits:
            return ""

        html = """
        <div class="split-section" style="margin: 20px 0; padding: 15px; background-color: #fff3cd; border-left: 5px solid #ffc107; border-radius: 4px;">
            <h3 style="margin-top: 0; color: #856404;">🔄 Stock Splits Detected</h3>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                <tr style="background-color: #ffeaa7;">
                    <th style="padding: 8px; text-align: left; border-bottom: 2px solid #856404;">Ticker</th>
                    <th style="padding: 8px; text-align: left; border-bottom: 2px solid #856404;">Type</th>
                    <th style="padding: 8px; text-align: left; border-bottom: 2px solid #856404;">Ratio</th>
                    <th style="padding: 8px; text-align: right; border-bottom: 2px solid #856404;">Old Entry</th>
                    <th style="padding: 8px; text-align: right; border-bottom: 2px solid #856404;">New Entry</th>
                    <th style="padding: 8px; text-align: center; border-bottom: 2px solid #856404;">Confidence</th>
                </tr>
        """

        for split in self.splits:
            conf_emoji = '✅' if split['confidence'] == 'high' else ('⚠️' if split['confidence'] == 'medium' else '❓')
            type_emoji = '📈' if split['split_type'] == 'forward' else '📉'

            html += f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>{split['ticker']}</strong></td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;">{type_emoji} {split['split_type'].capitalize()}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #ddd;">{split['display_ratio']}</td>
                    <td style="padding: 8px; text-align: right; border-bottom: 1px solid #ddd;">${split['old_entry']:,.2f}</td>
                    <td style="padding: 8px; text-align: right; border-bottom: 1px solid #ddd;">${split['new_entry']:,.2f}</td>
                    <td style="padding: 8px; text-align: center; border-bottom: 1px solid #ddd;">{conf_emoji} {split['confidence'].capitalize()}</td>
                </tr>
            """

        html += """
            </table>
            <p style="margin-top: 10px; font-size: 0.9em; color: #856404;">
                <em>Position metadata (stops, R values) have been automatically adjusted for these splits.</em>
            </p>
        </div>
        """

        return html

    def display_summary(self):
        """Display stock split summary for final report (backtest)"""
        if not self.has_splits():
            return

        splits = self.get_splits()
        splits_by_type = self.get_splits_by_type()

        print(f"\n{'STOCK SPLITS DETECTED':^100}")
        print(f"{'-' * 100}")
        print(f"{'Total Splits':<35} {len(splits):>25}")
        print(f"{'Forward Splits':<35} {len(splits_by_type['forward']):>25}")
        print(f"{'Reverse Splits':<35} {len(splits_by_type['reverse']):>25}")

        print(f"\n{'Ticker':<12} {'Type':<10} {'Ratio':<10} {'Old Entry':>15} {'New Entry':>15} {'Confidence':<12}")
        print(f"{'-' * 100}")

        for split in splits:
            conf_emoji = '✅' if split['confidence'] == 'high' else ('⚠️' if split['confidence'] == 'medium' else '❓')
            print(
                f"{split['ticker']:<12} "
                f"{split['split_type']:<10} "
                f"{split['display_ratio']:<10} "
                f"${split['old_entry']:>14,.2f} "
                f"${split['new_entry']:>14,.2f} "
                f"{conf_emoji} {split['confidence']:<10}"
            )

        print(f"\n{'Note: Position metadata (stops, R values) automatically adjusted':^100}")


# Global singleton instance
split_tracker = StockSplitTracker()


# =============================================================================
# STOCK SPLIT DETECTION AND VERIFICATION
# =============================================================================

def detect_split_via_alpaca(ticker: str, current_date: datetime = None, days_back: int = 5) -> dict:
    """
    Detect stock splits by comparing raw vs split-adjusted prices from Alpaca.

    This works by fetching the same historical bars with two different adjustments:
    - 'split' adjustment: prices adjusted for splits
    - 'raw': original unadjusted prices
    If these differ, a split occurred.

    Args:
        ticker: Stock symbol
        current_date: Reference date (for backtesting). None = use current time.
        days_back: Days of history to check

    Returns:
        dict: {
            'split_detected': bool,
            'ratio': float or None,
            'raw_price': float,
            'adjusted_price': float,
            'split_type': 'forward' or 'reverse' or None,
            'error': str or None
        }
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_API_SECRET
        )

        # Use provided date or current time
        if current_date:
            # Handle timezone-aware datetimes
            if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
                end_date = current_date.replace(tzinfo=None)
            else:
                end_date = current_date
        else:
            end_date = datetime.now()

        start_date = end_date - timedelta(days=days_back)

        # Fetch with split adjustment
        adjusted_request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=end_date,
            adjustment='split'
        )

        # Fetch raw (unadjusted)
        raw_request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=end_date,
            adjustment='raw'
        )

        adjusted_bars = client.get_stock_bars(adjusted_request)
        raw_bars = client.get_stock_bars(raw_request)

        if ticker not in adjusted_bars.data or ticker not in raw_bars.data:
            return {
                'split_detected': False,
                'ratio': None,
                'error': 'No data returned'
            }

        if not adjusted_bars.data[ticker] or not raw_bars.data[ticker]:
            return {
                'split_detected': False,
                'ratio': None,
                'error': 'Empty bar data'
            }

        # Get most recent bar from each
        adjusted_close = float(adjusted_bars.data[ticker][-1].close)
        raw_close = float(raw_bars.data[ticker][-1].close)

        # If they differ significantly, a split occurred
        if adjusted_close > 0 and raw_close > 0:
            ratio = raw_close / adjusted_close

            # Threshold: more than 5% difference indicates a split
            if abs(ratio - 1.0) > 0.05:
                split_type = 'forward' if ratio > 1.0 else 'reverse'
                return {
                    'split_detected': True,
                    'ratio': ratio,
                    'raw_price': raw_close,
                    'adjusted_price': adjusted_close,
                    'split_type': split_type,
                    'error': None
                }

        return {
            'split_detected': False,
            'ratio': 1.0,
            'raw_price': raw_close,
            'adjusted_price': adjusted_close,
            'split_type': None,
            'error': None
        }

    except Exception as e:
        print(f"[SPLIT CHECK] Alpaca API error for {ticker}: {e}")
        return {
            'split_detected': False,
            'ratio': None,
            'error': str(e)
        }


def detect_split_via_dataframe(ticker: str, raw_df, days_back: int = 10) -> dict:
    """
    Detect splits using pre-loaded DataFrame (for backtesting).

    Looks for sudden large price gaps that indicate a split.
    This is less reliable than API comparison but works offline.

    Args:
        ticker: Stock symbol
        raw_df: DataFrame with OHLC data (should be split-adjusted)
        days_back: Days to scan for gaps

    Returns:
        dict: Split detection result
    """
    try:
        if raw_df is None or len(raw_df) < days_back + 1:
            return {
                'split_detected': False,
                'ratio': None,
                'error': 'Insufficient data'
            }

        # Look at recent closes
        recent_closes = raw_df['close'].tail(days_back + 1).values

        # Check for large overnight gaps (>40% move suggests split)
        for i in range(1, len(recent_closes)):
            prev_close = recent_closes[i - 1]
            curr_close = recent_closes[i]

            if prev_close > 0 and curr_close > 0:
                ratio = prev_close / curr_close

                # Forward split: price dropped significantly (ratio > 1.4)
                # Reverse split: price jumped significantly (ratio < 0.7)
                if ratio > 1.4:
                    return {
                        'split_detected': True,
                        'ratio': ratio,
                        'split_type': 'forward',
                        'method': 'price_gap',
                        'error': None
                    }
                elif ratio < 0.7:
                    return {
                        'split_detected': True,
                        'ratio': ratio,
                        'split_type': 'reverse',
                        'method': 'price_gap',
                        'error': None
                    }

        return {
            'split_detected': False,
            'ratio': 1.0,
            'split_type': None,
            'error': None
        }

    except Exception as e:
        print(f"[SPLIT CHECK] DataFrame analysis error for {ticker}: {e}")
        return {
            'split_detected': False,
            'ratio': None,
            'error': str(e)
        }


def verify_split_ratio(
        ticker: str,
        detected_ratio: float,
        current_date: datetime = None,
        raw_df=None,
        is_backtesting: bool = False
) -> dict:
    """
    Verify detected split ratio using available data sources.

    In live trading: Uses Alpaca API (raw vs adjusted comparison)
    In backtesting: Uses DataFrame analysis (less reliable, more permissive)

    Args:
        ticker: Stock symbol
        detected_ratio: Ratio we calculated (stored_price / broker_price)
        current_date: Reference date
        raw_df: DataFrame for backtesting verification
        is_backtesting: True if running in backtest mode

    Returns:
        dict: {
            'verified': bool - was verification attempted successfully
            'split_confirmed': bool - does evidence support a split
            'should_adjust': bool - should we apply the adjustment
            'ratio_to_use': float - the ratio to use for adjustment
            'confidence': str - 'high', 'medium', 'low'
            'reason': str - explanation
        }
    """

    if is_backtesting:
        # Backtesting: Use DataFrame analysis as backup, but be more permissive
        # since we can't reliably call the API in backtest mode

        df_result = detect_split_via_dataframe(ticker, raw_df)

        if df_result.get('split_detected'):
            df_ratio = df_result['ratio']
            # Check if ratios are in same ballpark (within 20%)
            if df_ratio and abs(detected_ratio - df_ratio) / max(detected_ratio, df_ratio) < 0.20:
                return {
                    'verified': True,
                    'split_confirmed': True,
                    'should_adjust': True,
                    'ratio_to_use': detected_ratio,  # Use our detected ratio
                    'confidence': 'medium',
                    'reason': f'DataFrame gap analysis confirms split (df_ratio={df_ratio:.2f})'
                }

        # In backtesting, if the ratio is extreme enough, trust it
        # This handles the NOW case where stored metadata doesn't match split-adjusted data
        is_forward = detected_ratio > 1.5
        is_reverse = detected_ratio < 0.67

        if is_forward or is_reverse:
            return {
                'verified': True,
                'split_confirmed': True,
                'should_adjust': True,
                'ratio_to_use': detected_ratio,
                'confidence': 'medium',
                'reason': f'Backtest mode: ratio {detected_ratio:.2f} strongly suggests split'
            }

        return {
            'verified': True,
            'split_confirmed': False,
            'should_adjust': False,
            'ratio_to_use': None,
            'confidence': 'low',
            'reason': 'No split evidence in backtest data'
        }

    else:
        # Live trading: Use Alpaca API verification
        alpaca_result = detect_split_via_alpaca(ticker, current_date)

        if alpaca_result.get('error'):
            # API failed - fall back to ratio-only with lower confidence
            is_forward = detected_ratio > 1.5
            is_reverse = detected_ratio < 0.67

            if is_forward or is_reverse:
                return {
                    'verified': False,
                    'split_confirmed': None,
                    'should_adjust': True,  # Proceed cautiously
                    'ratio_to_use': detected_ratio,
                    'confidence': 'low',
                    'reason': f'API unavailable, proceeding with detected ratio {detected_ratio:.2f}'
                }

            return {
                'verified': False,
                'split_confirmed': False,
                'should_adjust': False,
                'ratio_to_use': None,
                'confidence': 'low',
                'reason': f'API error: {alpaca_result["error"]}'
            }

        if not alpaca_result['split_detected']:
            # Alpaca says no split - don't adjust
            return {
                'verified': True,
                'split_confirmed': False,
                'should_adjust': False,
                'ratio_to_use': None,
                'confidence': 'high',
                'reason': 'Alpaca raw/adjusted prices match - no split detected'
            }

        # Alpaca confirms split - verify ratio matches
        alpaca_ratio = alpaca_result['ratio']
        tolerance = 0.15  # 15% tolerance
        ratio_matches = abs(detected_ratio - alpaca_ratio) / alpaca_ratio < tolerance

        if ratio_matches:
            return {
                'verified': True,
                'split_confirmed': True,
                'should_adjust': True,
                'ratio_to_use': alpaca_ratio,  # Use Alpaca's more accurate ratio
                'confidence': 'high',
                'reason': f'Alpaca confirms {alpaca_result["split_type"]} split (ratio={alpaca_ratio:.2f})'
            }
        else:
            # Split confirmed but ratios differ - use Alpaca's ratio
            return {
                'verified': True,
                'split_confirmed': True,
                'should_adjust': True,
                'ratio_to_use': alpaca_ratio,  # Trust Alpaca over our calculation
                'confidence': 'medium',
                'reason': f'Split confirmed, using Alpaca ratio {alpaca_ratio:.2f} (detected was {detected_ratio:.2f})'
            }


def format_split_ratio(ratio: float) -> str:
    """
    Format split ratio for display.

    Args:
        ratio: The split ratio (old_price / new_price)

    Returns:
        str: Human-readable format like "5:1" or "1:10"
    """
    if ratio >= 1.0:
        # Forward split
        return f"{ratio:.0f}:1"
    else:
        # Reverse split
        return f"1:{1 / ratio:.0f}"


def adjust_position_metadata_for_split(meta: dict, ratio: float) -> dict:
    """
    Adjust all price-based fields in position metadata for a stock split.

    Args:
        meta: Position metadata dictionary
        ratio: Split ratio (old_price / new_price)

    Returns:
        dict: Updated metadata (also modifies in place)
    """
    if ratio <= 0:
        return meta

    # Adjust all price-based fields
    if meta.get('initial_stop') and meta['initial_stop'] > 0:
        meta['initial_stop'] = meta['initial_stop'] / ratio

    if meta.get('current_stop') and meta['current_stop'] > 0:
        meta['current_stop'] = meta['current_stop'] / ratio

    if meta.get('R') and meta['R'] > 0:
        meta['R'] = meta['R'] / ratio

    if meta.get('highest_close') and meta['highest_close'] > 0:
        meta['highest_close'] = meta['highest_close'] / ratio

    if meta.get('entry_atr') and meta['entry_atr'] > 0:
        meta['entry_atr'] = meta['entry_atr'] / ratio

    return meta


# =============================================================================
# MARKET HOLIDAY FUNCTIONS
# =============================================================================

def is_market_holiday(check_date) -> bool:
    """
    Check if date is a US market holiday.

    Args:
        check_date: date or datetime object

    Returns:
        bool: True if holiday
    """
    if hasattr(check_date, 'date'):
        check_date = check_date.date()

    return check_date in US_MARKET_HOLIDAYS_2025


def get_trading_window_info() -> dict:
    """
    Get trading window configuration.

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


def get_cash_balance(strategy):
    """
    Get cash balance - from Alpaca for live trading, tracked internally for backtesting.

    In backtesting, Lumibot's get_cash() can be stale within an iteration,
    so we track pending orders ourselves.
    """
    if Config.BACKTESTING:
        # Use Lumibot's cash for backtesting (handled by pending_exit_orders adjustment)
        return strategy.get_cash()

    # Live trading: Get directly from Alpaca
    try:
        from alpaca.trading.client import TradingClient

        client = TradingClient(
            api_key=os.getenv('ALPACA_API_KEY'),
            secret_key=os.getenv('ALPACA_API_SECRET'),
            paper=os.getenv('ALPACA_PAPER', 'true').lower() == 'true'
        )

        account = client.get_account()
        return float(account.cash)

    except Exception as e:
        print(f"[BROKER] Failed to get Alpaca cash, falling back to Lumibot: {e}")
        return strategy.get_cash()


def get_position_entry_date(ticker: str) -> Optional[datetime]:
    """
    Get the original entry date for a position from Alpaca order history.

    Looks for the earliest filled BUY order for this ticker.

    Args:
        ticker: Stock symbol

    Returns:
        datetime: Entry date or None if not found
    """
    if Config.BACKTESTING:
        return None

    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import OrderSide, OrderStatus, QueryOrderStatus

        client = TradingClient(
            api_key=os.getenv('ALPACA_API_KEY'),
            secret_key=os.getenv('ALPACA_API_SECRET'),
            paper=os.getenv('ALPACA_PAPER', 'true').lower() == 'true'
        )

        # Get filled orders for this ticker
        request = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            symbols=[ticker.upper()],
            limit=100
        )

        orders = client.get_orders(filter=request)

        # Find earliest filled BUY order
        buy_orders = [
            o for o in orders
            if o.side == OrderSide.BUY and o.status == OrderStatus.FILLED
        ]

        if buy_orders:
            # Sort by filled_at ascending to get earliest
            buy_orders.sort(key=lambda o: o.filled_at or o.submitted_at)
            earliest = buy_orders[0]
            return earliest.filled_at or earliest.submitted_at

        return None

    except Exception as e:
        print(f"[BROKER] Error getting entry date for {ticker}: {e}")
        return None




# =============================================================================
# TRADING FREQUENCY CONTROL
# =============================================================================

def has_traded_today(strategy, last_trade_date) -> bool:
    """
    Check if we've already traded today (for backtesting once-per-day).

    Args:
        strategy: Strategy instance
        last_trade_date: Date of last trade

    Returns:
        bool: True if already traded today
    """
    current_date = strategy.get_datetime().date()
    return last_trade_date == current_date