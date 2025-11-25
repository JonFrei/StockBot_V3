"""
Profit Tracking System - DUAL MODE (PostgreSQL for live, in-memory for backtesting)

UPDATED: Final summary includes safeguard system statistics
"""

from datetime import datetime
from database import get_database
from config import Config


class ProfitTracker:
    """
    Database-backed profit tracker with dual-mode support
    - Live: Records to PostgreSQL, queries for summaries
    - Backtest: Records to in-memory database
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def record_trade(self, ticker, quantity_sold, entry_price, exit_price,
                     exit_date, entry_signal, exit_signal, entry_score=0):
        """Record completed trade to database (PostgreSQL or in-memory)"""

        # Calculate P&L
        pnl_per_share = exit_price - entry_price
        total_pnl = pnl_per_share * quantity_sold
        pnl_pct = (pnl_per_share / entry_price * 100) if entry_price > 0 else 0

        conn = self.db.get_connection()
        try:
            # DUAL MODE: PostgreSQL or in-memory
            if Config.BACKTESTING:
                # In-memory insert
                self.db.insert_trade(
                    ticker=ticker,
                    quantity=quantity_sold,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_dollars=total_pnl,
                    pnl_pct=pnl_pct,
                    entry_signal=entry_signal,
                    entry_score=entry_score,
                    exit_signal=exit_signal.get('reason', 'unknown'),
                    exit_date=exit_date
                )
            else:
                # PostgreSQL insert
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO closed_trades 
                    (ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date,
                     was_watchlisted, confirmation_date, days_to_confirmation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    ticker,
                    quantity_sold,
                    entry_price,
                    exit_price,
                    total_pnl,
                    pnl_pct,
                    entry_signal,
                    entry_score,
                    exit_signal.get('reason', 'unknown'),
                    exit_date,
                    False,
                    None,
                    0
                ))

                conn.commit()
                cursor.close()

            # Display immediate feedback
            emoji = "✅" if total_pnl > 0 else "❌"

            print(
                f"\n{emoji} TRADE CLOSED: {ticker} | ${total_pnl:+,.2f} ({pnl_pct:+.1f}%) | "
                f"{quantity_sold} shares @ ${entry_price:.2f} → ${exit_price:.2f}")

        except Exception as e:
            if not Config.BACKTESTING:
                conn.rollback()
            print(f"[ERROR] Failed to record trade: {e}")
            raise
        finally:
            self.db.return_connection(conn)

    def get_closed_trades(self, limit=None):
        """Get closed trades from database (PostgreSQL or in-memory)"""

        if Config.BACKTESTING:
            # In-memory retrieval
            return self.db.get_closed_trades(limit)

        # PostgreSQL retrieval
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            if limit:
                cursor.execute("""
                    SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                           entry_signal, entry_score, exit_signal, exit_date
                    FROM closed_trades
                    ORDER BY exit_date DESC
                    LIMIT %s
                """, (limit,))
            else:
                cursor.execute("""
                    SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                           entry_signal, entry_score, exit_signal, exit_date
                    FROM closed_trades
                    ORDER BY exit_date DESC
                """)

            trades = []
            for row in cursor.fetchall():
                trades.append({
                    'ticker': row[0],
                    'quantity': row[1],
                    'entry_price': float(row[2]),
                    'exit_price': float(row[3]),
                    'pnl_dollars': float(row[4]),
                    'pnl_pct': float(row[5]),
                    'entry_signal': row[6],
                    'entry_score': row[7],
                    'exit_signal': row[8],
                    'exit_date': row[9]
                })

            return trades

        finally:
            cursor.close()
            self.db.return_connection(conn)

    def display_final_summary(self, stock_rotator=None, regime_detector=None):
        """
        Display comprehensive P&L summary with rotation and safeguard stats

        UPDATED: Includes safeguard system statistics
        """

        closed_trades = self.get_closed_trades()

        if not closed_trades:
            print("\n📊 No closed trades to report")
            return

        # Calculate summary stats
        winners = [t for t in closed_trades if t['pnl_dollars'] > 0]
        losers = [t for t in closed_trades if t['pnl_dollars'] < 0]

        total_realized = sum(t['pnl_dollars'] for t in closed_trades)
        win_rate = (len(winners) / len(closed_trades) * 100) if closed_trades else 0

        avg_win = sum(t['pnl_dollars'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl_dollars'] for t in losers) / len(losers) if losers else 0

        # Display header
        mode = "Memory (Backtest)" if Config.BACKTESTING else "Database"
        print(f"\n{'=' * 100}")
        print(f"📊 FINAL PERFORMANCE SUMMARY (Source: {mode})")
        print(f"{'=' * 100}\n")

        # Overall stats
        print(f"📈 OVERALL STATISTICS:")
        print(f"   Total Trades: {len(closed_trades)}")
        print(f"   Winners: {len(winners)} ({win_rate:.1f}%)")
        print(f"   Losers: {len(losers)}")
        print(f"   Total Realized P&L: ${total_realized:+,.2f}")
        print(f"   Average Win: ${avg_win:,.2f}")
        print(f"   Average Loss: ${avg_loss:,.2f}")
        if winners and losers and avg_loss != 0:
            profit_factor = abs(avg_win * len(winners) / (avg_loss * len(losers)))
            print(f"   Profit Factor: {profit_factor:.2f}")

        # Signal performance
        self._display_signal_performance(closed_trades)

        # Per-ticker performance with rotation tiers
        self._display_ticker_performance(closed_trades, stock_rotator)

        # Trade details (last 75)
        self._display_trade_details(closed_trades)

        # Open positions
        self._display_open_positions(stock_rotator)

        # Safeguard system summary
        if regime_detector:
            self._display_safeguard_summary(regime_detector)

        # Rotation summary
        if stock_rotator:
            self._display_rotation_summary(stock_rotator)

        print(f"\n{'=' * 100}\n")

    def _display_safeguard_summary(self, regime_detector):
        """Display market safeguard system summary"""

        stats = regime_detector.get_statistics()

        print(f"\n{'=' * 100}")
        print(f"🛡️ MARKET SAFEGUARD SUMMARY")
        print(f"{'=' * 100}")
        print(f"   Distribution Days: {stats['distribution_days']} (Level: {stats['distribution_level']})")
        print(f"   Recent Stops (5d): {stats['recent_stops_5d']}")
        print(f"   Recent Stops (10d): {stats['recent_stops_10d']}")
        print(f"   SPY Extension: {stats['spy_extension']:.1f}% from 200 SMA")

        if stats.get('spy_below_50') or stats.get('spy_below_200'):
            print(f"\n   ⚠️  SPY MA Status:")
            if stats['spy_below_50']:
                print(f"      • Below 50 SMA")
            if stats['spy_below_200']:
                print(f"      • Below 200 SMA")

        if stats['in_recovery']:
            print(f"\n   ⚠️  Currently in recovery period")
            if stats['exit_date']:
                print(f"   Exit Date: {stats['exit_date'].strftime('%Y-%m-%d')}")
        else:
            print(f"\n   ✅ Safeguard system armed and monitoring")

        print(f"{'=' * 100}")

    def _display_signal_performance(self, closed_trades):
        """Display performance by signal WITH AVERAGE SCORES"""
        from collections import defaultdict

        signal_stats = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'total_score': 0.0,
            'score_count': 0
        })

        for trade in closed_trades:
            signal = trade['entry_signal']
            signal_stats[signal]['trades'].append(trade)
            signal_stats[signal]['total_pnl'] += trade['pnl_dollars']

            if trade['pnl_dollars'] > 0:
                signal_stats[signal]['wins'] += 1
            else:
                signal_stats[signal]['losses'] += 1

            # Track scores
            entry_score = trade.get('entry_score', 0)
            if entry_score > 0:
                signal_stats[signal]['total_score'] += entry_score
                signal_stats[signal]['score_count'] += 1

        print(f"\n🎯 PERFORMANCE BY ENTRY SIGNAL:")
        print(f"{'─' * 100}")

        sorted_signals = sorted(signal_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        for signal_name, stats in sorted_signals:
            total_trades = len(stats['trades'])
            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0

            wins = [t['pnl_dollars'] for t in stats['trades'] if t['pnl_dollars'] > 0]
            losses = [t['pnl_dollars'] for t in stats['trades'] if t['pnl_dollars'] < 0]

            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = sum(losses) / len(losses) if losses else 0

            # Calculate average score
            avg_score = (stats['total_score'] / stats['score_count']) if stats['score_count'] > 0 else 0

            print(f"\n   📊 {signal_name}")
            print(f"      Trades: {total_trades} ({stats['wins']}W / {stats['losses']}L)")
            print(f"      Win Rate: {win_rate:.1f}%")
            print(f"      Avg Entry Score: {avg_score:.0f}/100")
            print(f"      Total P&L: ${stats['total_pnl']:+,.2f}")
            print(f"      Avg P&L: ${avg_pnl:+,.2f}")
            print(f"      Avg Win: ${avg_win:,.2f}")
            print(f"      Avg Loss: ${avg_loss:,.2f}")

        print(f"\n{'─' * 100}")

    def _display_ticker_performance(self, closed_trades, stock_rotator=None):
        """Display performance by ticker WITH ROTATION TIER"""
        from collections import defaultdict

        ticker_stats = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'total_pnl_pct': 0.0
        })

        for trade in closed_trades:
            ticker = trade['ticker']
            ticker_stats[ticker]['trades'] += 1
            ticker_stats[ticker]['total_pnl'] += trade['pnl_dollars']
            ticker_stats[ticker]['total_pnl_pct'] += trade['pnl_pct']

            if trade['pnl_dollars'] > 0:
                ticker_stats[ticker]['wins'] += 1
            else:
                ticker_stats[ticker]['losses'] += 1

        print(f"\n💰 PERFORMANCE BY TICKER:")
        print(f"{'─' * 110}")

        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        print(f"{'Ticker':<8} {'Trades':<8} {'W/L':<10} {'Win Rate':<10} {'Total P&L':<15} {'Avg P&L':<15} {'Tier'}")
        print(f"{'─' * 110}")

        for ticker, stats in sorted_tickers:
            total_trades = stats['trades']
            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0
            avg_pnl_pct = stats['total_pnl_pct'] / total_trades if total_trades > 0 else 0

            w_l_str = f"{stats['wins']}W/{stats['losses']}L"

            # Get rotation tier
            if stock_rotator:
                tier = stock_rotator.get_award(ticker)
                tier_emoji = {
                    'premium': '🥇',
                    'standard': '🥈',
                    'frozen': '❄️'
                }.get(tier, '❓')
                tier_display = f"{tier_emoji} {tier}"
            else:
                tier_display = "N/A"

            print(f"{ticker:<8} {total_trades:<8} {w_l_str:<10} {win_rate:>5.1f}%     "
                  f"${stats['total_pnl']:>+10,.2f}   ${avg_pnl:>+8,.2f} ({avg_pnl_pct:>+5.1f}%)   {tier_display}")

        print(f"{'─' * 110}")

        if sorted_tickers:
            best = sorted_tickers[0]
            worst = sorted_tickers[-1]

            print(f"\n🏆 BEST PERFORMER: {best[0]} (${best[1]['total_pnl']:+,.2f} from {best[1]['trades']} trades)")
            print(f"⚠️  WORST PERFORMER: {worst[0]} (${worst[1]['total_pnl']:+,.2f} from {worst[1]['trades']} trades)")

    def _display_trade_details(self, closed_trades):
        """Display last 75 trades with entry scores"""

        print(f"\n📋 TRADE DETAILS (Last 75):")
        print(f"{'─' * 100}")
        print(f"{'Ticker':<8} {'P&L':<18} {'Score':<8} {'Signal':<22} {'Exit'}")
        print(f"{'─' * 100}")

        for t in closed_trades[:75]:
            entry_score = t.get('entry_score', 0)
            score_display = f"[{entry_score:.0f}]" if entry_score > 0 else "[--]"
            pnl_str = f"${t['pnl_dollars']:+9,.2f} ({t['pnl_pct']:+6.2f}%)"

            # Truncate long signal names
            signal = t['entry_signal'][:20]
            exit_reason = t['exit_signal'][:20]

            print(f"{t['ticker']:<8} {pnl_str:<18} {score_display:<8} {signal:<22} {exit_reason}")

        print(f"{'─' * 100}")

    def _display_open_positions(self, stock_rotator=None):
        """Display current open positions WITH ROTATION TIER"""
        try:
            import account_broker_data

            positions = self.strategy.get_positions()

            if not positions or len(positions) == 0:
                print(f"\n📊 OPEN POSITIONS: None")
                return

            print(f"\n📊 OPEN POSITIONS ({len(positions)}):")
            print(f"{'─' * 110}")
            print(f"{'Ticker':<8} {'Qty':<8} {'Entry':<12} {'Current':<12} {'P&L':<18} {'%':<10} {'Tier'}")
            print(f"{'─' * 110}")

            total_unrealized = 0

            for position in positions:
                ticker = position.symbol
                quantity = account_broker_data.get_position_quantity(position, ticker)

                # Use centralized utility for entry price
                entry_price = account_broker_data.get_broker_entry_price(position, self.strategy, ticker)

                if not account_broker_data.validate_entry_price(entry_price, ticker, min_price=0.01):
                    print(f"{ticker:<8} {quantity:>6,}   Entry price unavailable")
                    continue

                try:
                    current_price = self.strategy.get_last_price(ticker)
                    unrealized_pnl = (current_price - entry_price) * quantity
                    unrealized_pct = ((current_price - entry_price) / entry_price * 100)
                    total_unrealized += unrealized_pnl

                    # Get rotation tier
                    if stock_rotator:
                        tier = stock_rotator.get_award(ticker)
                        tier_emoji = {
                            'premium': '🥇',
                            'standard': '🥈',
                            'frozen': '❄️'
                        }.get(tier, '❓')
                        tier_display = f"{tier_emoji} {tier}"
                    else:
                        tier_display = "N/A"

                    pnl_str = f"${unrealized_pnl:+,.2f}"
                    pct_str = f"{unrealized_pct:+.1f}%"

                    print(f"{ticker:<8} {quantity:>6,}   ${entry_price:>8.2f}   ${current_price:>8.2f}   "
                          f"{pnl_str:<18} {pct_str:<10} {tier_display}")

                except Exception as e:
                    print(f"{ticker:<8} {quantity:>6,}   ${entry_price:>8.2f}   (price unavailable)")

            print(f"{'─' * 110}")
            print(f"\nTotal Unrealized P&L: ${total_unrealized:+,.2f}")

        except Exception as e:
            print(f"\n⚠️ Could not retrieve open positions: {e}")

    def _display_rotation_summary(self, stock_rotator):
        """Display stock rotation summary"""

        stats = stock_rotator.get_statistics()

        print(f"\n{'=' * 100}")
        print(f"🏆 STOCK ROTATION SUMMARY")
        print(f"{'=' * 100}")
        print(f"   Total Rotations: {stats['rotation_count']}")
        if stats['last_rotation_date']:
            print(f"   Last Rotation: {stats['last_rotation_date'].strftime('%Y-%m-%d')}")
        print(f"   Stocks Tracked: {stats['total_tracked']}")

        print(f"\n   📊 Award Distribution:")
        dist = stats['award_distribution']
        print(f"      🥇 Premium (1.5x): {dist.get('premium', 0)}")
        print(f"      🥈 Standard (1.0x): {dist.get('standard', 0)}")
        print(f"      ❄️  Frozen (BLOCKED): {dist.get('frozen', 0)}")

        if stats['frozen_stocks']:
            print(f"\n   ❄️  Frozen Stocks: {', '.join(stats['frozen_stocks'])}")

        if stats['recovery_tracking']:
            print(f"\n   🔄 Recovery Progress:")
            from stock_rotation import RotationConfig
            for ticker, passes in stats['recovery_tracking'].items():
                remaining = RotationConfig.RECOVERY_CONSECUTIVE_PASSES - passes
                print(
                    f"      {ticker}: {passes}/{RotationConfig.RECOVERY_CONSECUTIVE_PASSES} evaluations ({remaining} more needed)")

        print(f"{'=' * 100}")


# =============================================================================
# ORDER EXECUTION LOGGER
# =============================================================================

class OrderLogger:
    """
    Logs successful order executions - dual mode support
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def log_order(self, ticker, side, quantity, signal_type='unknown',
                  award='none', quality_score=0, limit_price=None,
                  was_watchlisted=False, days_on_watchlist=0):
        """
        Log successful order submission

        Args:
            ticker: Stock symbol
            side: 'buy' or 'sell'
            quantity: Number of shares
            signal_type: Entry/exit signal name
            award: Ticker award level
            quality_score: Opportunity quality score
            limit_price: Limit price if applicable
            was_watchlisted: Whether this came from watchlist confirmation
            days_on_watchlist: Days spent on watchlist before confirmation
        """
        try:
            # Get current price as filled price approximation
            try:
                filled_price = self.strategy.get_last_price(ticker)
            except:
                filled_price = limit_price if limit_price else None

            portfolio_value = self.strategy.portfolio_value
            cash_before = self.strategy.get_cash()
            submitted_at = self.strategy.get_datetime()

            if Config.BACKTESTING:
                # In-memory logging
                self.db.insert_order_log(
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    order_type='market',
                    limit_price=limit_price,
                    filled_price=filled_price,
                    submitted_at=submitted_at,
                    signal_type=signal_type,
                    portfolio_value=portfolio_value,
                    cash_before=cash_before,
                    award=award,
                    quality_score=quality_score,
                    broker_order_id=None,
                    was_watchlisted=was_watchlisted,
                    days_on_watchlist=days_on_watchlist
                )
            else:
                # PostgreSQL logging
                conn = self.db.get_connection()
                try:
                    cursor = conn.cursor()

                    cursor.execute("""
                        INSERT INTO order_log
                        (ticker, side, quantity, order_type, limit_price, filled_price,
                         submitted_at, signal_type, portfolio_value, cash_before,
                         award, quality_score, was_watchlisted, days_on_watchlist)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        ticker, side, quantity, 'market', limit_price, filled_price,
                        submitted_at, signal_type, portfolio_value, cash_before,
                        award, quality_score, was_watchlisted, days_on_watchlist
                    ))

                    conn.commit()

                finally:
                    cursor.close()
                    self.db.return_connection(conn)

        except Exception as e:
            print(f"[WARN] Failed to log order for {ticker}: {e}")