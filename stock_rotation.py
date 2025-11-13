"""
In-Memory Stock Rotation System with Winner Lock Protection

Dynamically selects best stocks from core_stocks list without modifying JSON config.
Rotates based on momentum, signal quality, and market conditions.

NEW: Winner Lock - Don't rotate out stocks that are up >15% with momentum OR trending

Usage:
    rotator = StockRotator(max_active=12)
    active_tickers = rotator.get_active_tickers(strategy, all_candidates, current_date, all_stock_data)
"""

from datetime import datetime, timedelta
import stock_data
import signals
from position_monitoring import calculate_market_condition_score


class StockRotator:
    """
    Manages dynamic stock rotation in memory with winner lock protection

    Attributes:
        max_active: Maximum number of stocks to trade simultaneously
        rotation_frequency: How often to rotate ('daily', 'weekly', 'monthly')
        active_tickers: List of currently active tickers
        last_rotation_date: Date of last rotation
        ticker_scores: Historical scores for each ticker
        locked_winners: Tickers locked due to strong performance
    """

    def __init__(self, max_active=12, rotation_frequency='weekly'):
        self.max_active = max_active
        self.rotation_frequency = rotation_frequency
        self.active_tickers = []
        self.last_rotation_date = None
        self.ticker_scores = {}  # Historical tracking
        self.rotation_count = 0
        self.locked_winners = []  # NEW: Track locked winners

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
        elif self.rotation_frequency == 'biweekly':  # ADD THIS
            return days_since_rotation >= 14
        elif self.rotation_frequency == 'monthly':
            return days_since_rotation >= 30

    def calculate_stock_score(self, ticker, data, strategy):
        """
        Calculate rotation score for a stock (0-100 scale)

        Scoring Components:
        1. Trend Strength (30 points) - Distance above 200 SMA
        2. Momentum (25 points) - ADX strength
        3. Volume Activity (20 points) - Recent volume
        4. Signal Quality (25 points) - Current buy signal strength

        Returns: float (0-100)
        """
        if not data or 'indicators' not in data:
            return 0.0

        indicators = data['indicators']
        score = 0.0

        # 1. TREND STRENGTH (30 points)
        close = indicators.get('close', 0)
        sma200 = indicators.get('sma200', 0)

        if close > sma200 and sma200 > 0:
            distance_pct = ((close - sma200) / sma200 * 100)
            # Give more points for stronger trends (up to 30)
            trend_score = min(30.0, distance_pct * 1.5)
            score += trend_score
        else:
            # Penalize stocks below 200 SMA
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
        # Below 15 ADX = no momentum points

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
        # Below 1.0 = no volume points

        # 4. SIGNAL QUALITY (25 points)
        # Check if stock has a current buy signal
        buy_signal_list = ['swing_trade_1', 'swing_trade_2']
        buy_signal = signals.buy_signals(indicators, buy_signal_list)

        if buy_signal and buy_signal.get('side') == 'buy':
            # Has a buy signal - award points based on market condition
            market_condition = calculate_market_condition_score(indicators)

            if market_condition['condition'] == 'strong':
                score += 25.0  # Perfect
            elif market_condition['condition'] == 'neutral':
                score += 15.0
            else:  # weak
                score += 5.0

        # 5. BONUS: Recent performance (up to +10 or -10)
        # Check if we have historical data
        try:
            raw_data = data.get('raw', None)
            if raw_data is not None and len(raw_data) >= 20:
                price_20d_ago = raw_data['close'].iloc[-20]
                current_price = raw_data['close'].iloc[-1]
                return_pct = ((current_price - price_20d_ago) / price_20d_ago * 100)

                # Positive momentum bonus
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

        # Ensure score is non-negative
        return max(0.0, score)

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
                if pnl_pct < 12.0:  # CHANGED from 15.0
                    continue

                # Check momentum
                data = all_stock_data[ticker]['indicators']
                adx = data.get('adx', 0)
                close = data.get('close', 0)
                ema20 = data.get('ema20', 0)
                ema50 = data.get('ema50', 0)

                # LOOSENED: Lock if has momentum OR trending (was AND)
                # Either strong ADX (>20) or price structure is good
                has_momentum = adx > 18  # Was 25 -> 20 ->
                is_trending = close > ema20  # Was close > ema20 > ema50

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

        # STEP 2: Score all candidates
        scores = {}

        for ticker in all_candidates:
            try:
                # Use pre-fetched data
                if ticker not in all_stock_data:
                    scores[ticker] = 0.0
                    continue

                # Calculate score
                score = self.calculate_stock_score(ticker, all_stock_data[ticker], strategy)
                scores[ticker] = score

                # Store in history
                if ticker not in self.ticker_scores:
                    self.ticker_scores[ticker] = []
                self.ticker_scores[ticker].append({
                    'date': current_date,
                    'score': score
                })

            except Exception as e:
                print(f"   ⚠️ Error scoring {ticker}: {e}")
                scores[ticker] = 0.0

        # STEP 3: Sort by score and build new active list
        sorted_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Locked winners are guaranteed in the active list
        new_active = locked_tickers[:]

        # Fill remaining slots with highest-scored non-locked stocks
        for ticker, score in sorted_stocks:
            if ticker not in new_active and len(new_active) < self.max_active:
                if score > 0:  # Only add if has positive score
                    new_active.append(ticker)

        # STEP 4: Display rankings
        print(f"\n📊 ROTATION RANKINGS:")
        print(f"{'─' * 80}")
        print(f"{'Rank':<6} {'Ticker':<8} {'Score':<10} {'Status':<15} {'Change'}")
        print(f"{'─' * 80}")

        for idx, (ticker, score) in enumerate(sorted_stocks[:20], 1):  # Show top 20
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

            print(f"{idx:<6} {ticker:<8} {score:>6.1f}     {status:<15} {change}")

        print(f"{'─' * 80}\n")

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

def create_default_rotator(max_active=12, frequency='weekly'):
    """
    Create a default rotator instance

    Args:
        max_active: Number of stocks to keep active
        frequency: 'daily', 'weekly', or 'monthly'

    Returns:
        StockRotator instance
    """
    return StockRotator(max_active=max_active, rotation_frequency=frequency)


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
