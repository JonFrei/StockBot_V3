"""
In-Memory Stock Rotation System with Integrated Blacklist

INTEGRATED FEATURES:
- Stock rotation with winner lock protection
- Ticker quality scoring with historical win rate tracking
- INTEGRATED: Proactive ticker blacklisting (was separate file)

Dynamically selects best stocks from core_stocks list without modifying JSON config.
Rotates based on momentum, signal quality, market conditions, AND historical performance.

Usage:
    rotator = StockRotator(max_active=12, profit_tracker=None)
    active_tickers = rotator.rotate_stocks(strategy, all_candidates, current_date, all_stock_data)
"""

from datetime import datetime, timedelta
import stock_data
import signals
from position_monitoring import calculate_market_condition_score


# =============================================================================
# INTEGRATED TICKER BLACKLIST SYSTEM
# =============================================================================

class TickerBlacklist:
    """
    Proactive ticker quality monitoring system

    Integrates with profit_tracker to analyze historical performance
    and penalize/blacklist poor performers
    """

    def __init__(self, profit_tracker):
        """
        Initialize blacklist system

        Args:
            profit_tracker: Reference to ProfitTracker instance
        """
        self.profit_tracker = profit_tracker
        self.consecutive_losses = {}  # {ticker: count}
        self.temporary_blacklist = {}  # {ticker: expiry_date}
        self.permanent_blacklist = set()

    def update_from_trade(self, ticker, is_winner, current_date):
        """
        Update tracker when a trade closes

        Args:
            ticker: Stock symbol
            is_winner: True if profitable, False if loss
            current_date: Trade close date
        """
        if is_winner:
            # Reset consecutive losses on win
            self.consecutive_losses[ticker] = 0
        else:
            # Increment consecutive losses
            current_count = self.consecutive_losses.get(ticker, 0)
            self.consecutive_losses[ticker] = current_count + 1

            # Check for blacklist triggers
            if self.consecutive_losses[ticker] >= 3:
                self._apply_temporary_blacklist(
                    ticker,
                    current_date,
                    days=21,
                    reason='3 consecutive losses'
                )

            # Check aggregate P&L damage even if losses were not consecutive
            self._check_recent_loss_pnl(ticker, current_date)

        # Check for permanent blacklist
        self._check_permanent_blacklist(ticker)

    def _apply_temporary_blacklist(self, ticker, current_date, days=21, reason='3 consecutive losses'):
        """
        Apply 2-4 week temporary blacklist

        Args:
            ticker: Stock symbol
            current_date: Current date
            days: Duration of blacklist
            reason: Description shown in logs
        """
        if ticker not in self.permanent_blacklist:
            expiry = current_date + timedelta(days=days)
            previous_expiry = self.temporary_blacklist.get(ticker)

            # Only extend/announce if the new expiry is later
            if previous_expiry is None or expiry > previous_expiry:
                self.temporary_blacklist[ticker] = expiry
                print(f"\n⛔ TEMPORARY BLACKLIST: {ticker} ({reason}) - Until {expiry.strftime('%Y-%m-%d')}")

    def _check_recent_loss_pnl(self, ticker, current_date, trades_to_check=3, loss_threshold=-1000.0):
        """
        Apply a shorter temporary blacklist if cumulative P&L over the recent window
        is deeply negative, even without consecutive losses. Helps cut off names
        like NFLX sooner.
        """
        if not self.profit_tracker:
            return

        ticker_trades = [t for t in self.profit_tracker.closed_trades if t['ticker'] == ticker]
        if len(ticker_trades) < trades_to_check:
            return

        recent_trades = ticker_trades[-trades_to_check:]
        total_recent_pnl = sum(t['pnl_dollars'] for t in recent_trades)

        if total_recent_pnl <= loss_threshold:
            self._apply_temporary_blacklist(
                ticker,
                current_date,
                days=14,
                reason=f'{total_recent_pnl:+,.0f} over last {trades_to_check} trades'
            )

    def _check_permanent_blacklist(self, ticker):
        """
        Check if ticker should be permanently blacklisted

        Criteria: Win rate < 30% over 5+ trades
        """
        trades = [t for t in self.profit_tracker.closed_trades if t['ticker'] == ticker]

        if len(trades) < 5:
            return  # Not enough data

        wins = sum(1 for t in trades if t['pnl_dollars'] > 0)
        win_rate = wins / len(trades) * 100

        if win_rate < 30.0:
            self.permanent_blacklist.add(ticker)
            # Remove from temporary if present
            if ticker in self.temporary_blacklist:
                del self.temporary_blacklist[ticker]
            print(f"\n🚫 PERMANENT BLACKLIST: {ticker} ({win_rate:.1f}% win rate over {len(trades)} trades)")

    def clean_expired_blacklists(self, current_date):
        """
        Remove expired temporary blacklists

        Args:
            current_date: Current date
        """
        expired = [ticker for ticker, expiry in self.temporary_blacklist.items()
                   if current_date >= expiry]

        for ticker in expired:
            del self.temporary_blacklist[ticker]
            # Reset consecutive losses
            self.consecutive_losses[ticker] = 0
            print(f"\n✅ BLACKLIST EXPIRED: {ticker} - Back in rotation pool")

    def get_ticker_penalty(self, ticker):
        """
        Calculate penalty score for stock rotation

        Returns: float (-100 to 0)
            -100: Blacklisted
            -50: Very poor performance
            -30: Poor performance
            -20: 2 consecutive losses
            -15: Win rate < 50%
            0: No penalty
        """
        # Permanent blacklist = full penalty
        if ticker in self.permanent_blacklist:
            return -100.0

        # Temporary blacklist = full penalty
        if ticker in self.temporary_blacklist:
            return -100.0

        # Get historical performance
        trades = [t for t in self.profit_tracker.closed_trades if t['ticker'] == ticker]

        if len(trades) < 3:
            return 0.0  # Not enough data for penalty

        wins = sum(1 for t in trades if t['pnl_dollars'] > 0)
        win_rate = wins / len(trades) * 100
        consecutive = self.consecutive_losses.get(ticker, 0)

        penalty = 0.0

        # Win rate penalties
        if win_rate < 30.0:
            penalty -= 50.0
        elif win_rate < 40.0:
            penalty -= 30.0
        elif win_rate < 50.0:
            penalty -= 15.0

        # Consecutive loss penalties
        if consecutive >= 2:
            penalty -= 20.0

        return penalty

    def is_blacklisted(self, ticker):
        """
        Check if ticker is currently blacklisted

        Returns: bool
        """
        return ticker in self.permanent_blacklist or ticker in self.temporary_blacklist

    def get_statistics(self):
        """
        Get blacklist statistics

        Returns: dict with stats
        """
        return {
            'permanent_blacklist': list(self.permanent_blacklist),
            'temporary_blacklist': len(self.temporary_blacklist),
            'temp_blacklist_tickers': list(self.temporary_blacklist.keys()),
            'tickers_with_consecutive_losses': {
                ticker: count for ticker, count in self.consecutive_losses.items()
                if count > 0
            }
        }


# =============================================================================
# STOCK ROTATION SYSTEM
# =============================================================================

class StockRotator:
    """
    Manages dynamic stock rotation in memory with winner lock protection
    INTEGRATED: Now includes TickerBlacklist functionality
        NEW: Tiered sizing so top-ranked tickers receive higher allocation

    Attributes:
        max_active: Maximum number of stocks to trade simultaneously
        rotation_frequency: How often to rotate ('daily', 'weekly', 'monthly')
        active_tickers: List of currently active tickers
        last_rotation_date: Date of last rotation
        ticker_scores: Historical scores for each ticker
        locked_winners: Tickers locked due to strong performance
        profit_tracker: Reference to profit tracker for win rate data
        ticker_performance: Historical performance tracking
        blacklist: Integrated TickerBlacklist instance
    """

    def __init__(self, max_active=12, rotation_frequency='weekly', profit_tracker=None):
        self.max_active = max_active
        self.rotation_frequency = rotation_frequency
        self.active_tickers = []
        self.last_rotation_date = None
        self.ticker_scores = {}  # Historical tracking
        self.rotation_count = 0
        self.locked_winners = []
        self.initial_order = {}
        self.ticker_tiers = {}
        self.ticker_rankings = {}
        self.tier_size_overrides = {}
        self.premium_rank_boosts = [1.20, 1.17, 1.14, 1.11, 1.08, 1.05, 1.02]
        self.reduced_tier_multiplier = 0.7

        # Win rate tracking
        self.profit_tracker = profit_tracker
        self.ticker_performance = {}  # {ticker: {'wins': int, 'losses': int, 'win_rate': float}}

        # INTEGRATED: Blacklist system
        self.blacklist = TickerBlacklist(profit_tracker) if profit_tracker else None

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
        Update ticker performance from profit tracker

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
        Calculate score bonus/penalty based on historical win rate

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

        INTEGRATED: Now includes blacklist penalties

        Scoring Components:
        1. Trend Strength (30 points) - Distance above 200 SMA
        2. Momentum (25 points) - ADX strength
        3. Volume Activity (20 points) - Recent volume
        4. Signal Quality (25 points) - Current buy signal strength
        5. BONUS: Recent performance (up to +10 or -10)
        6. Historical win rate: -20 to +20 points
        7. INTEGRATED: Blacklist penalties: -100 to 0 points

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

        # 6. Historical win rate bonus/penalty
        historical_score = self.get_historical_performance_score(ticker)
        score += historical_score

        # 7. INTEGRATED: Apply blacklist penalties
        if self.blacklist:
            blacklist_penalty = self.blacklist.get_ticker_penalty(ticker)
            score += blacklist_penalty

        # Store in history
        if ticker not in self.ticker_scores:
            self.ticker_scores[ticker] = []
        self.ticker_scores[ticker].append({
            'date': datetime.now(),
            'score': score
        })

        return score

    def _seed_initial_order(self, candidates):
        """
        Store the original ordering of the ticker universe so we can
        default to it before sufficient trade history exists.
        """
        for ticker in candidates:
            if ticker not in self.initial_order:
                self.initial_order[ticker] = len(self.initial_order)

    def _rank_tickers_for_competition(self, candidates):
        """
        Rank tickers by trade volume (count) and win rate so the most
        battle-tested names control the boosted slots.
        """
        ranking = []

        for ticker in candidates:
            perf = self.ticker_performance.get(ticker, {})
            total_trades = perf.get('total_trades', 0)
            win_rate = perf.get('win_rate', 0.0) if total_trades > 0 else 0.0
            seed_idx = self.initial_order.get(ticker, len(self.initial_order))
            is_blacklisted = bool(self.blacklist and self.blacklist.is_blacklisted(ticker))

            ranking.append({
                'ticker': ticker,
                'trades': total_trades,
                'win_rate': win_rate,
                'seed_idx': seed_idx,
                'is_blacklisted': is_blacklisted
            })

        ranking.sort(key=lambda item: (
            item['is_blacklisted'],
            -item['trades'],
            -item['win_rate'],
            item['seed_idx']
        ))
        return ranking

    def _assign_tiers(self, ranking, locked_tickers):
        """
        Convert ranking output into tier labels and sizing multipliers.
        Locked winners always receive boosted sizing.
        """
        tiers = {}
        size_map = {}

        non_blacklisted = [entry for entry in ranking if not entry['is_blacklisted']]

        prioritized = []
        seen = set()

        # Locked winners first (preserve their order)
        for ticker in locked_tickers:
            entry = next((item for item in non_blacklisted if item['ticker'] == ticker), None)
            if entry and entry['ticker'] not in seen:
                prioritized.append(entry)
                seen.add(entry['ticker'])

        # Remaining contenders keep their ranking order
        for entry in non_blacklisted:
            if entry['ticker'] not in seen:
                prioritized.append(entry)
                seen.add(entry['ticker'])

        premium_cap = min(len(self.premium_rank_boosts), len(prioritized))

        for idx in range(premium_cap):
            entry = prioritized[idx]
            tiers[entry['ticker']] = 'premium'
            size_map[entry['ticker']] = self.premium_rank_boosts[idx]

        for entry in prioritized[premium_cap:]:
            ticker = entry['ticker']
            if entry['trades'] == 0 or entry['win_rate'] > 0:
                tiers[ticker] = 'base'
                size_map[ticker] = 1.0
            else:
                tiers[ticker] = 'reduced'
                size_map[ticker] = self.reduced_tier_multiplier

        # Blacklisted tickers get explicitly tagged so we can skip them
        for entry in ranking:
            if entry['is_blacklisted']:
                tiers[entry['ticker']] = 'blacklisted'
                size_map[entry['ticker']] = 0.0

        # Build ordered watchlist grouped by tier priority
        ordered_watchlist = []
        for tier_name in ['premium', 'base', 'reduced']:
            for entry in prioritized:
                ticker = entry['ticker']
                if tiers.get(ticker) == tier_name and ticker not in ordered_watchlist:
                    ordered_watchlist.append(ticker)

        return tiers, size_map, ordered_watchlist

    def check_winner_locks(self, strategy, all_stock_data):
        """
        Check existing positions for winners to lock

        Lock criteria:
        - Position is up >12%
        - Strong momentum (ADX > 18) OR trending (price > EMA20)

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

                # Check if it's a winner
                if pnl_pct < 12.0:
                    continue

                # Check momentum
                data = all_stock_data[ticker]['indicators']
                adx = data.get('adx', 0)
                close = data.get('close', 0)
                ema20 = data.get('ema20', 0)

                # Lock if has momentum OR trending
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
        INTEGRATED: Uses built-in blacklist system

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

        self._seed_initial_order(all_candidates)

        print(f"\n{'=' * 80}")
        print(f"🔄 STOCK ROTATION - {current_date.strftime('%Y-%m-%d')}")
        print(f"{'=' * 80}")

        # Extract SPY data for regime filter
        spy_data = all_stock_data.get('SPY', {}).get('indicators', None) if 'SPY' in all_stock_data else None

        # Update performance data from profit tracker
        self.update_ticker_performance_from_tracker()
        previous_tiers = dict(self.ticker_tiers)

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

        premium_slots = min(len(self.premium_rank_boosts), len(all_candidates))
        print(f"\nEvaluating {len(all_candidates)} candidates | {premium_slots} boosted slots | "
              f"{len(locked_tickers)} locked winners")

        # STEP 2: Score all candidates
        scores = {}

        for ticker in all_candidates:
            try:
                if ticker not in all_stock_data:
                    scores[ticker] = -100.0
                    continue

                # Calculate score (includes blacklist penalties)
                score = self.calculate_stock_score(ticker, all_stock_data[ticker], strategy, spy_data=spy_data)
                scores[ticker] = score

            except Exception as e:
                print(f"   ⚠️ Error scoring {ticker}: {e}")
                scores[ticker] = -100.0

        # INTEGRATED: Filter blacklisted tickers
        if self.blacklist:
            for ticker in list(scores.keys()):
                if self.blacklist.is_blacklisted(ticker):
                    scores[ticker] = -200.0  # Force to bottom

        # STEP 3: Sort by score and build new active list
        sorted_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Build tier map + watchlist order
        competition_rankings = self._rank_tickers_for_competition(all_candidates)
        tiers, size_overrides, ordered_watchlist = self._assign_tiers(competition_rankings, locked_tickers)
        self.ticker_tiers = tiers
        self.tier_size_overrides = size_overrides
        self.ticker_rankings = {
            entry['ticker']: idx + 1
            for idx, entry in enumerate(competition_rankings)
            if not entry['is_blacklisted']
        }

        new_active = ordered_watchlist[:]
        for ticker in locked_tickers:
            if ticker not in new_active and tiers.get(ticker) != 'blacklisted':
                new_active.insert(0, ticker)

        # STEP 4: Display rankings
        print(f"\n📊 ROTATION RANKINGS (score + tier sizing):")
        print(f"{'─' * 120}")
        print(f"{'Rank':<6} {'Ticker':<8} {'Score':<8} {'Trades':<8} {'WinRate':<14} {'Tier':<14} {'SizeX':<8} {'Status'}")
        print(f"{'─' * 120}")

        for idx, (ticker, score) in enumerate(sorted_stocks[:30], 1):
            perf = self.ticker_performance.get(ticker, {})
            trades = perf.get('total_trades', 0)
            if trades > 0:
                win_rate_str = f"{perf.get('win_rate', 0):.0f}% ({perf.get('wins', 0)}W/{perf.get('losses', 0)}L)"
            else:
                win_rate_str = "N/A"

            tier_label = self.ticker_tiers.get(ticker, 'base').upper()
            size_mult = self.tier_size_overrides.get(ticker, 1.0)
            status = ""
            if ticker in locked_tickers:
                status = "🔒 LOCKED"
            elif tier_label == 'BLACKLISTED':
                status = "⛔ BLACKLIST"
            elif ticker in new_active:
                status = "✅ ACTIVE"
            else:
                status = "⚪ BENCH"

            print(f"{idx:<6} {ticker:<8} {score:>6.1f}   {trades:<8} {win_rate_str:<14} "
                  f"{tier_label:<14} x{size_mult:>4.2f}   {status}")

        print(f"{'─' * 120}\n")

        current_premium = [t for t, tier in self.ticker_tiers.items() if tier == 'premium']
        previous_premium = [t for t, tier in previous_tiers.items() if tier == 'premium']
        promoted = [t for t in current_premium if t not in previous_premium]
        demoted = [t for t in previous_premium if self.ticker_tiers.get(t) != 'premium']

        if locked_tickers:
            print(f"🔒 LOCKED WINNERS: {', '.join(locked_tickers)}")
        if promoted:
            print(f"⬆️ BOOSTED INTO TOP 7: {', '.join(promoted)}")
        if demoted:
            print(f"⬇️ LOST BOOSTED SLOT: {', '.join(demoted)}")

        base_list = [t for t, tier in self.ticker_tiers.items() if tier == 'base']
        reduced_list = [t for t, tier in self.ticker_tiers.items() if tier == 'reduced']

        def preview_list(items):
            if not items:
                return "None"
            preview = items[:10]
            suffix = " ..." if len(items) > 10 else ""
            return ", ".join(preview) + suffix

        print(f"\n🏆 PREMIUM ({len(current_premium)}): {preview_list(current_premium)}")
        print(f"⚖️  BASE ({len(base_list)}): {preview_list(base_list)}")
        print(f"🔻 REDUCED ({len(reduced_list)}): {preview_list(reduced_list)}")

        print(f"\n✅ TIERED WATCHLIST ({len(new_active)} tradable tickers): {', '.join(new_active)}")
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

    def get_ticker_tier(self, ticker):
        """
        Return the current tier label for a ticker (premium/base/reduced).
        """
        return self.ticker_tiers.get(ticker, 'base')

    def get_size_multiplier(self, ticker):
        """
        Return the tier-based sizing multiplier for the ticker.

        Premium names get >1.0, reduced names <1.0, everyone else 1.0.
        """
        return self.tier_size_overrides.get(ticker, 1.0)

    def get_tier_summary(self):
        """
        Provide a quick breakdown of tickers in each tier (excluding blacklist).
        """
        summary = {
            'premium': [],
            'base': [],
            'reduced': []
        }

        for ticker, tier in self.ticker_tiers.items():
            if tier in summary:
                summary[tier].append(ticker)

        return summary

    def get_rotation_summary(self):
        """
        Get summary statistics about rotation

        Returns: dict with stats
        """
        tier_summary = self.get_tier_summary()
        return {
            'rotation_count': self.rotation_count,
            'last_rotation': self.last_rotation_date,
            'active_count': len(self.active_tickers),
            'active_tickers': self.active_tickers,
            'locked_winners': len(self.locked_winners),
            'total_tracked': len(self.ticker_scores),
            'tier_summary': tier_summary,
            'premium_slots': len(self.premium_rank_boosts)
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def print_rotation_report(rotator):
    """
    Print detailed rotation report including blacklist stats
    """
    summary = rotator.get_rotation_summary()

    print(f"\n{'=' * 80}")
    print(f"📊 ROTATION SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total Rotations: {summary['rotation_count']}")
    print(f"Last Rotation: {summary['last_rotation']}")
    print(f"Active Stocks (tradable): {summary['active_count']}")
    print(f"Boosted Slots (Top Tier): {summary['premium_slots']}")
    print(f"Locked Winners: {summary['locked_winners']}")
    print(f"Currently Trading (tier order): {', '.join(summary['active_tickers'])}")
    print(f"Total Stocks Tracked: {summary['total_tracked']}")

    tier_summary = summary['tier_summary']

    def describe_tier(label):
        members = tier_summary.get(label, [])
        if not members:
            return "None"
        preview = members[:12]
        suffix = " ..." if len(members) > 12 else ""
        return f"{', '.join(preview)}{suffix}"

    print(f"\n🏆 Premium Tier ({len(tier_summary.get('premium', []))}): {describe_tier('premium')}")
    print(f"⚖️  Base Tier ({len(tier_summary.get('base', []))}): {describe_tier('base')}")
    print(f"🔻 Reduced Tier ({len(tier_summary.get('reduced', []))}): {describe_tier('reduced')}")
    print(f"{'=' * 80}\n")

    # INTEGRATED: Display blacklist stats
    if rotator.blacklist:
        blacklist_stats = rotator.blacklist.get_statistics()
        print(f"{'=' * 80}")
        print(f"⛔ TICKER BLACKLIST SUMMARY")
        print(f"{'=' * 80}")
        if blacklist_stats['permanent_blacklist']:
            print(f"Permanent Blacklist: {', '.join(blacklist_stats['permanent_blacklist'])}")
        else:
            print(f"Permanent Blacklist: None")

        if blacklist_stats['temp_blacklist_tickers']:
            print(f"Temporary Blacklist: {', '.join(blacklist_stats['temp_blacklist_tickers'])}")
        else:
            print(f"Temporary Blacklist: None")

        if blacklist_stats['tickers_with_consecutive_losses']:
            print(f"\nTickers with Consecutive Losses:")
            for ticker, count in blacklist_stats['tickers_with_consecutive_losses'].items():
                print(f"   {ticker}: {count} loss(es)")
        print(f"{'=' * 80}\n")