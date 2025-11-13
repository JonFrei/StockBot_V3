"""
In-Memory Stock Rotation System with Winner Lock Protection + Ticker Quality Scoring

ENHANCED WITH:
- Priority 3: Penalty system for consistently losing tickers
- Priority 5: Per-ticker historical win rate tracking for scoring

Dynamically selects best stocks from core_stocks list without modifying JSON config.
Rotates based on momentum, signal quality, market conditions, AND historical performance.

NEW: Winner Lock - Don't rotate out stocks that are up >15% with momentum OR trending

Usage:
    rotator = StockRotator(max_active=12, profit_tracker=None)
    active_tickers = rotator.get_active_tickers(strategy, all_candidates, current_date, all_stock_data)
"""

from datetime import datetime, timedelta
import stock_data
import signals
from position_monitoring import calculate_market_condition_score

# PRIORITY 3: Ticker Blacklist/Penalty System
TICKER_PENALTIES = {
    # Based on backtest results - tickers with poor win rates or consistent losses
    'SHOP': -25,  # 16.7% win rate, -$3,883 (avoid)
    'V': -30,  # 0% win rate, -$3,523 (avoid)
    'AMZN': -30,  # 0% win rate, -$1,074 (avoid)
    'TSLA': -25,  # 20% win rate, -$3,320 (avoid)
    'COIN': -20,  # 28.6% win rate, -$1,786 (reduce exposure)
    'PYPL': -15,  # 50% win rate but consistent small losses
    'META': -10,  # 50% win rate, slight losses
}


class StockRotator:
    """
    Manages dynamic stock rotation in memory with winner lock protection
    ENHANCED: Now includes historical win rate tracking (Priority 5)

    Attributes:
        max_active: Maximum number of stocks to trade simultaneously
        rotation_frequency: How often to rotate ('daily', 'weekly', 'monthly')
        active_tickers: List of currently active tickers
        last_rotation_date: Date of last rotation
        ticker_scores: Historical scores for each ticker
        locked_winners: Tickers locked due to strong performance
        profit_tracker: Reference to profit tracker for win rate data (NEW)
        ticker_performance: Historical performance tracking (NEW)
    """

    def __init__(self, max_active=12, rotation_frequency='weekly', profit_tracker=None):
        self.max_active = max_active
        self.rotation_frequency = rotation_frequency
        self.active_tickers = []
        self.last_rotation_date = None
        self.ticker_scores = {}  # Historical tracking
        self.rotation_count = 0
        self.locked_winners = []

        # PRIORITY 5: Win rate tracking
        self.profit_tracker = profit_tracker
        self.ticker_performance = {}  # {ticker: {'wins': int, 'losses': int, 'win_rate': float}}

    def should_rotate(self, current_date):
        """
        Check if it's time to rotate based on frequency

        Returns: bool
        """
        if self.last_rotation_date is None:
            return True

        days_since_rotation = (current_date - self.last_rotation_date).days

        if self.rotation_frequency == 'daily':
            return days_since_rotation >= 1
        elif self.rotation_frequency == 'weekly':
            return days_since_rotation >= 7
        elif self.rotation_frequency == 'biweekly':
            return days_since_rotation >= 14
        elif self.rotation_frequency == 'monthly':
            return days_since_rotation >= 30

    def update_ticker_performance_from_tracker(self):
        """
        PRIORITY 5: Update ticker performance from profit tracker

        Extracts win/loss data from closed trades to inform rotation scoring
        """
        if not self.profit_tracker:
            return

        # Reset performance tracking
        self.ticker_performance = {}

        # Get closed trades from profit tracker
        closed_trades = self.profit_tracker.closed_trades

        for trade in closed_trades:
            ticker = trade['ticker']
            is_winner = trade['pnl_dollars'] > 0

            if ticker not in self.ticker_performance:
                self.ticker_performance[ticker] = {
                    'wins': 0,
                    'losses': 0,
                    'win_rate': 0.0,
                    'total_trades': 0
                }

            if is_winner:
                self.ticker_performance[ticker]['wins'] += 1
            else:
                self.ticker_performance[ticker]['losses'] += 1

            self.ticker_performance[ticker]['total_trades'] += 1

            # Calculate win rate
            total = self.ticker_performance[ticker]['total_trades']
            wins = self.ticker_performance[ticker]['wins']
            self.ticker_performance[ticker]['win_rate'] = (wins / total * 100) if total > 0 else 0

    def get_historical_performance_score(self, ticker):
        """
        PRIORITY 5: Calculate score bonus/penalty based on historical win rate

        Returns: float (-20 to +20 points)
            +20: Excellent (>80% win rate)
            +10: Good (70-80%)
            +5: Above average (60-70%)
            0: Average (50-60%)
            -10: Below average (40-50%)
            -20: Poor (<40%)
        """
        if ticker not in self.ticker_performance:
            return 0  # No history = neutral

        perf = self.ticker_performance[ticker]

        # Need at least 3 trades for reliable data
        if perf['total_trades'] < 3:
            return 0

        win_rate = perf['win_rate']

        if win_rate >= 80:
            return 20.0
        elif win_rate >= 70:
            return 10.0
        elif win_rate >= 60:
            return 5.0
        elif win_rate >= 50:
            return 0.0
        elif win_rate >= 40:
            return -10.0
        else:
            return -20.0

    def calculate_stock_score(self, ticker, data, strategy, spy_data=None):
        """
        Calculate rotation score for a stock (0-100 scale)

        ENHANCED: Now includes Priority 3 (penalties) and Priority 5 (historical win rate)

        Scoring Components:
        1. Trend Strength (30 points) - Distance above 200 SMA
        2. Momentum (25 points) - ADX strength
        3. Volume Activity (20 points) - Recent volume
        4. Signal Quality (25 points) - Current buy signal strength
        5. BONUS: Recent performance (up to +10 or -10)
        6. NEW: Ticker penalties (Priority 3): -30 to 0 points
        7. NEW: Historical win rate (Priority 5): -20 to +20 points

        Args:
            ticker: Stock symbol
            data: Stock data dict
            strategy: Strategy instance
            spy_data: SPY data for regime filter (optional)

        Returns: float (can be negative due to penalties)
        """
        if not data or 'indicators' not in data:
            return -100.0  # Invalid data = very low score

        indicators = data['indicators']
        score = 0.0

        # 1. TREND STRENGTH (30 points)
        close = indicators.get('close', 0)
        sma200 = indicators.get('sma200', 0)

        if close > sma200 and sma200 > 0:
            distance_pct = ((close - sma200) / sma200 * 100)
            trend_score = min(30.0, distance_pct * 1.5)
            score += trend_score
        else:
            score -= 10.0

        # 2. MOMENTUM (25 points)
        adx = indicators.get('adx', 0)
        if adx > 40:
            score += 25.0
        elif adx > 30:
            score += 20.0
        elif adx > 20:
            score += 10.0
        elif adx > 15:
            score += 5.0

        # 3. VOLUME ACTIVITY (20 points)
        volume_ratio = indicators.get('volume_ratio', 0)
        if volume_ratio > 2.0:
            score += 20.0
        elif volume_ratio > 1.5:
            score += 15.0
        elif volume_ratio > 1.2:
            score += 10.0
        elif volume_ratio > 1.0:
            score += 5.0

        # 4. SIGNAL QUALITY (25 points)
        buy_signal_list = ['swing_trade_1', 'swing_trade_2']
        buy_signal = signals.buy_signals(indicators, buy_signal_list, spy_data=spy_data)

        if buy_signal and buy_signal.get('side') == 'buy':
            market_condition = calculate_market_condition_score(indicators)

            if market_condition['condition'] == 'strong':
                score += 25.0
            elif market_condition['condition'] == 'neutral':
                score += 15.0
            else:
                score += 5.0

        # 5. BONUS: Recent performance (up to +10 or -10)
        try:
            raw_data = data.get('raw', None)
            if raw_data is not None and len(raw_data) >= 20:
                price_20d_ago = raw_data['close'].iloc[-20]
                current_price = raw_data['close'].iloc[-1]
                return_pct = ((current_price - price_20d_ago) / price_20d_ago * 100)

                if return_pct > 10:
                    score += 10.0
                elif return_pct > 5:
                    score += 5.0
                elif return_pct < -10:
                    score -= 10.0
                elif return_pct < -5:
                    score -= 5.0
        except:
            pass

        # PRIORITY 3: Apply ticker penalties
        if ticker in TICKER_PENALTIES:
            penalty = TICKER_PENALTIES[ticker]
            score += penalty  # Add negative value

        # PRIORITY 5: Apply historical win rate bonus/penalty
        historical_score = self.get_historical_performance_score(ticker)
        score += historical_score

        # Store in history
        if ticker not in self.ticker_scores:
            self.ticker_scores[ticker] = []
        self.ticker_scores[ticker].append({
            'date': datetime.now(),
            'score': score
        })

        return score

    def check_winner_locks(self, strategy, all_stock_data):
        """
        FIXED: Check existing positions for winners to lock

        LOOSENED Lock criteria (easier to lock):
        - Position is up >15% (was 20%)
        - Strong momentum (ADX > 20) OR trending (price > EMA20)

        Returns: list of tickers to lock
        """
        locked = []

        try:
            positions = strategy.get_positions()

            for position in positions:
                ticker = position.symbol

                # Only check tickers in our candidate pool
                if ticker not in all_stock_data:
                    continue

                # Get position P&L
                try:
                    current_price = strategy.get_last_price(ticker)
                    entry_price = float(position.avg_fill_price)
                    pnl_pct = ((current_price - entry_price) / entry_price * 100)
                except:
                    continue

                # LOOSENED: Check if it's a winner (was >20%, now >15%)
                if pnl_pct < 12.0:
                    continue

                # Check momentum
                data = all_stock_data[ticker]['indicators']
                adx = data.get('adx', 0)
                close = data.get('close', 0)
                ema20 = data.get('ema20', 0)

                # LOOSENED: Lock if has momentum OR trending (was AND)
                has_momentum = adx > 18
                is_trending = close > ema20

                if has_momentum or is_trending:
                    locked.append({
                        'ticker': ticker,
                        'pnl_pct': pnl_pct,
                        'adx': adx,
                        'above_ema20': close > ema20
                    })
        except Exception as e:
            print(f"   ⚠️ Error checking winner locks: {e}")

        return locked

    def rotate_stocks(self, strategy, all_candidates, current_date, all_stock_data):
        """
        Perform stock rotation with WINNER LOCK protection
        ENHANCED: Now uses Priority 3 (penalties) and Priority 5 (win rate) in scoring

        NEW: Don't rotate out winning positions that are still trending

        Args:
            strategy: Strategy instance (for position/price access)
            all_candidates: List of all possible tickers from core_stocks
            current_date: Current date
            all_stock_data: Pre-fetched data for all candidates

        Returns:
            list: New active tickers
        """
        if not all_candidates:
            return []

        print(f"\n{'=' * 80}")
        print(f"🔄 STOCK ROTATION - {current_date.strftime('%Y-%m-%d')}")
        print(f"{'=' * 80}")

        # Extract SPY data for regime filter
        spy_data = all_stock_data.get('SPY', {}).get('indicators', None) if 'SPY' in all_stock_data else None

        # PRIORITY 5: Update performance data from profit tracker
        self.update_ticker_performance_from_tracker()

        # STEP 1: Check for winner locks
        locked_winners_data = self.check_winner_locks(strategy, all_stock_data)
        locked_tickers = [w['ticker'] for w in locked_winners_data]

        if locked_winners_data:
            print(f"\n🔒 WINNER LOCKS - Protecting {len(locked_winners_data)} high-performers:")
            for winner in locked_winners_data:
                momentum_label = f"ADX {winner['adx']:.0f}" if winner['adx'] > 20 else "trending"
                print(f"   🔒 {winner['ticker']}: +{winner['pnl_pct']:.1f}% ({momentum_label}) - LET IT RUN!")

        try:
            positions = strategy.get_positions()
            for position in positions:
                ticker = position.symbol
                if ticker not in all_stock_data:
                    continue
                try:
                    current_price = strategy.get_last_price(ticker)
                    entry_price = float(position.avg_fill_price)
                    pnl_pct = ((current_price - entry_price) / entry_price * 100)

                    # Absolute 20% lock (overrides everything)
                    if pnl_pct > 20.0 and ticker not in locked_tickers:
                        locked_tickers.append(ticker)
                        print(f"   🔒 {ticker}: +{pnl_pct:.1f}% (>20% absolute lock)")
                except:
                    continue
        except:
            pass

        # Calculate available slots for rotation
        available_slots = self.max_active - len(locked_tickers)
        print(f"\nEvaluating {len(all_candidates)} candidates for {available_slots} rotation slots...")
        print(f"(+ {len(locked_tickers)} locked winners)")

        # STEP 2: Score all candidates (NOW WITH PENALTIES AND WIN RATE)
        scores = {}

        for ticker in all_candidates:
            try:
                if ticker not in all_stock_data:
                    scores[ticker] = -100.0
                    continue

                # Calculate score (includes penalties, win rate, and SPY regime filter)
                score = self.calculate_stock_score(ticker, all_stock_data[ticker], strategy, spy_data=spy_data)
                scores[ticker] = score

            except Exception as e:
                print(f"   ⚠️ Error scoring {ticker}: {e}")
                scores[ticker] = -100.0

        # STEP 3: Sort by score and build new active list
        sorted_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Locked winners are guaranteed in the active list
        new_active = locked_tickers[:]

        # Fill remaining slots with highest-scored non-locked stocks
        for ticker, score in sorted_stocks:
            if ticker not in new_active and len(new_active) < self.max_active:
                if score > -50:  # Only add if score isn't terrible
                    new_active.append(ticker)

        # STEP 4: Display rankings WITH PENALTIES AND WIN RATES
        print(f"\n📊 ROTATION RANKINGS (with penalties & win rates):")
        print(f"{'─' * 100}")
        print(f"{'Rank':<6} {'Ticker':<8} {'Score':<10} {'WinRate':<12} {'Penalty':<12} {'Status':<15} {'Change'}")
        print(f"{'─' * 100}")

        for idx, (ticker, score) in enumerate(sorted_stocks[:20], 1):
            # Get win rate
            win_rate_str = "N/A"
            if ticker in self.ticker_performance:
                perf = self.ticker_performance[ticker]
                if perf['total_trades'] >= 3:
                    win_rate_str = f"{perf['win_rate']:.0f}% ({perf['wins']}W/{perf['losses']}L)"

            # Get penalty
            penalty_str = ""
            if ticker in TICKER_PENALTIES:
                penalty_str = f"{TICKER_PENALTIES[ticker]:+d}"

            # Determine status
            was_active = ticker in self.active_tickers
            is_active = ticker in new_active
            is_locked = ticker in locked_tickers

            if is_locked:
                status = "🔒 LOCKED"
                change = "🏆"
            elif is_active and was_active:
                status = "✅ ACTIVE"
                change = "—"
            elif is_active and not was_active:
                status = "🆕 PROMOTED"
                change = "↑"
            elif not is_active and was_active:
                status = "📤 ROTATED OUT"
                change = "↓"
            else:
                status = "⚪ BENCH"
                change = "—"

            print(f"{idx:<6} {ticker:<8} {score:>6.1f}     {win_rate_str:<12} {penalty_str:<12} {status:<15} {change}")

        print(f"{'─' * 100}\n")

        # STEP 5: Show changes summary
        added = [t for t in new_active if t not in self.active_tickers and t not in locked_tickers]
        removed = [t for t in self.active_tickers if t not in new_active and t not in locked_tickers]

        if locked_tickers:
            print(f"🔒 LOCKED WINNERS: {', '.join(locked_tickers)}")
        if added:
            print(f"🆕 PROMOTED: {', '.join(added)}")
        if removed:
            print(f"📤 ROTATED OUT: {', '.join(removed)}")

        print(f"\n✅ ACTIVE POOL ({len(new_active)}): {', '.join(new_active)}")
        print(f"{'=' * 80}\n")

        # Update state
        self.active_tickers = new_active
        self.locked_winners = locked_tickers
        self.last_rotation_date = current_date
        self.rotation_count += 1

        return new_active

    def get_active_tickers(self, strategy, all_candidates, current_date, all_stock_data):
        """
        Get current active tickers, rotating if needed

        Args:
            strategy: Strategy instance
            all_candidates: List of all tickers from core_stocks
            current_date: Current date
            all_stock_data: Pre-fetched data for all candidates

        Returns:
            list: Active tickers for trading
        """
        # First time or time to rotate?
        if self.should_rotate(current_date):
            return self.rotate_stocks(strategy, all_candidates, current_date, all_stock_data)

        # Not time to rotate - return current active list
        return self.active_tickers

    def force_rotation(self, strategy, all_candidates, current_date, all_stock_data):
        """
        Force a rotation regardless of schedule

        Useful for manual rotation or after major market events
        """
        return self.rotate_stocks(strategy, all_candidates, current_date, all_stock_data)

    def get_ticker_history(self, ticker):
        """
        Get historical scores for a ticker

        Returns: list of {date, score} dicts
        """
        return self.ticker_scores.get(ticker, [])

    def get_rotation_summary(self):
        """
        Get summary statistics about rotation

        Returns: dict with stats
        """
        return {
            'rotation_count': self.rotation_count,
            'last_rotation': self.last_rotation_date,
            'active_count': len(self.active_tickers),
            'active_tickers': self.active_tickers,
            'locked_winners': len(self.locked_winners),
            'total_tracked': len(self.ticker_scores)
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def create_default_rotator(max_active=12, frequency='weekly', profit_tracker=None):
    """
    Create a default rotator instance

    Args:
        max_active: Number of stocks to keep active
        frequency: 'daily', 'weekly', or 'monthly'
        profit_tracker: Reference to profit tracker for win rate data

    Returns:
        StockRotator instance
    """
    return StockRotator(max_active=max_active, rotation_frequency=frequency, profit_tracker=profit_tracker)


def print_rotation_report(rotator):
    """
    Print detailed rotation report
    """
    summary = rotator.get_rotation_summary()

    print(f"\n{'=' * 80}")
    print(f"📊 ROTATION SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total Rotations: {summary['rotation_count']}")
    print(f"Last Rotation: {summary['last_rotation']}")
    print(f"Active Stocks: {summary['active_count']}/{rotator.max_active}")
    print(f"Locked Winners: {summary['locked_winners']}")
    print(f"Currently Trading: {', '.join(summary['active_tickers'])}")
    print(f"Total Stocks Tracked: {summary['total_tracked']}")
    print(f"{'=' * 80}\n")