"""
Profit Tracking System - DUAL MODE (PostgreSQL for live, in-memory for backtesting)

Records trades to database and queries for all summaries
No in-memory accumulation in live mode
"""

from datetime import datetime
from database import get_database
from config import Config


class ProfitTracker:
    """
    Database-backed profit tracker with dual-mode support and confirmation tracking
    - Live: Records to PostgreSQL, queries for summaries
    - Backtest: Records to in-memory database
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def record_trade(self, ticker, quantity_sold, entry_price, exit_price,
                     exit_date, entry_signal, exit_signal, entry_score=0,
                     was_watchlisted=False, confirmation_date=None, days_to_confirmation=0):
        """Record completed trade to database (PostgreSQL or in-memory) with confirmation tracking"""

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
                    exit_date=exit_date,
                    was_watchlisted=was_watchlisted,
                    confirmation_date=confirmation_date,
                    days_to_confirmation=days_to_confirmation
                )
            else:
                # PostgreSQL insert with confirmation tracking
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
                    was_watchlisted,
                    confirmation_date,
                    days_to_confirmation
                ))

                conn.commit()
                cursor.close()

            # Display immediate feedback
            emoji = "✅" if total_pnl > 0 else "❌"
            watchlist_label = " [CONFIRMED]" if was_watchlisted else ""
            conf_label = f" ({days_to_confirmation}d)" if was_watchlisted and days_to_confirmation > 0 else ""

            print(
                f"\n{emoji} TRADE CLOSED: {ticker}{watchlist_label}{conf_label} | ${total_pnl:+,.2f} ({pnl_pct:+.1f}%) | "
                f"{quantity_sold} shares @ ${entry_price:.2f} → ${exit_price:.2f}")

            # Notify blacklist
            self._notify_blacklist(ticker, total_pnl > 0, exit_date)

        except Exception as e:
            if not Config.BACKTESTING:
                conn.rollback()
            print(f"[ERROR] Failed to record trade: {e}")
            raise
        finally:
            self.db.return_connection(conn)

    def _notify_blacklist(self, ticker, is_winner, exit_date):
        """Inform blacklist about trade outcome"""
        stock_rotator = getattr(self.strategy, 'stock_rotator', None)
        if not stock_rotator:
            return

        blacklist = getattr(stock_rotator, 'blacklist', None)
        if not blacklist:
            return

        try:
            blacklist.update_from_trade(ticker, is_winner, exit_date)
        except Exception as err:
            print(f"[WARN] Could not notify blacklist for {ticker}: {err}")

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
                           entry_signal, entry_score, exit_signal, exit_date,
                           was_watchlisted, confirmation_date, days_to_confirmation
                    FROM closed_trades
                    ORDER BY exit_date DESC
                    LIMIT %s
                """, (limit,))
            else:
                cursor.execute("""
                    SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                           entry_signal, entry_score, exit_signal, exit_date,
                           was_watchlisted, confirmation_date, days_to_confirmation
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
                    'exit_date': row[9],
                    'was_watchlisted': row[10] if len(row) > 10 else False,
                    'confirmation_date': row[11] if len(row) > 11 else None,
                    'days_to_confirmation': row[12] if len(row) > 12 else 0
                })

            return trades

        finally:
            cursor.close()
            self.db.return_connection(conn)

    def get_signal_stats(self, signal_name, lookback=None):
        """Get win/loss stats for a signal (PostgreSQL or in-memory)"""

        if Config.BACKTESTING:
            # In-memory calculation
            trades = self.db.get_trades_by_signal(signal_name, lookback)

            trade_count = len(trades)
            if trade_count == 0:
                return {
                    'signal': signal_name,
                    'trade_count': 0,
                    'win_rate': 0.0,
                    'total_pnl': 0.0,
                    'avg_pnl': 0.0
                }

            wins = sum(1 for t in trades if t['pnl_dollars'] > 0)
            total_pnl = sum(t['pnl_dollars'] for t in trades)
            avg_pnl = total_pnl / trade_count
            win_rate = (wins / trade_count * 100)

            return {
                'signal': signal_name,
                'trade_count': trade_count,
                'win_rate': round(win_rate, 2),
                'total_pnl': round(total_pnl, 2),
                'avg_pnl': round(avg_pnl, 2)
            }

        # PostgreSQL query
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            if lookback:
                cursor.execute("""
                    SELECT COUNT(*) as trade_count,
                           SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
                           SUM(pnl_dollars) as total_pnl,
                           AVG(pnl_dollars) as avg_pnl
                    FROM (
                        SELECT * FROM closed_trades
                        WHERE entry_signal = %s
                        ORDER BY exit_date DESC
                        LIMIT %s
                    ) recent
                """, (signal_name, lookback))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as trade_count,
                           SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
                           SUM(pnl_dollars) as total_pnl,
                           AVG(pnl_dollars) as avg_pnl
                    FROM closed_trades
                    WHERE entry_signal = %s
                """, (signal_name,))

            row = cursor.fetchone()

            trade_count = row[0] or 0
            wins = row[1] or 0
            total_pnl = float(row[2]) if row[2] else 0.0
            avg_pnl = float(row[3]) if row[3] else 0.0
            win_rate = (wins / trade_count * 100) if trade_count > 0 else 0.0

            return {
                'signal': signal_name,
                'trade_count': trade_count,
                'win_rate': round(win_rate, 2),
                'total_pnl': round(total_pnl, 2),
                'avg_pnl': round(avg_pnl, 2)
            }

        finally:
            cursor.close()
            self.db.return_connection(conn)

    def get_underperforming_signals(self, min_trades=6, win_rate_threshold=45.0, lookback=30):
        """
        Identify signals that are currently underperforming
        Works in both PostgreSQL and in-memory modes

        Args:
            min_trades: Minimum number of trades required before evaluation
            win_rate_threshold: Disable signals below this win rate (%)
            lookback: Evaluate only the most recent N trades per signal

        Returns:
            dict of {signal_name: stats_dict}
        """
        # Get all closed trades to find unique signals
        all_trades = self.get_closed_trades()

        if not all_trades:
            return {}

        signals = set(trade['entry_signal'] for trade in all_trades)
        underperformers = {}

        for signal_name in signals:
            stats = self.get_signal_stats(signal_name, lookback=lookback)
            if stats['trade_count'] < min_trades:
                continue
            if stats['win_rate'] < win_rate_threshold:
                underperformers[signal_name] = stats

        return underperformers

    def display_confirmation_analysis(self):
        """Display confirmation system performance analysis"""

        all_trades = self.get_closed_trades()

        if not all_trades:
            return

        print(f"\n{'=' * 80}")
        print(f"🎯 CONFIRMATION SYSTEM ANALYSIS")
        print(f"{'=' * 80}\n")

        # Separate immediate vs confirmed trades
        immediate_trades = [t for t in all_trades if not t.get('was_watchlisted', False)]
        confirmed_trades = [t for t in all_trades if t.get('was_watchlisted', False)]

        # Immediate trades stats
        if immediate_trades:
            immediate_wins = sum(1 for t in immediate_trades if t['pnl_dollars'] > 0)
            immediate_wr = (immediate_wins / len(immediate_trades) * 100)
            immediate_pnl = sum(t['pnl_dollars'] for t in immediate_trades)
            immediate_avg = immediate_pnl / len(immediate_trades)

            print(f"🟢 IMMEDIATE BUYS (No Watchlist):")
            print(f"   Trades: {len(immediate_trades)}")
            print(f"   Win Rate: {immediate_wr:.1f}% ({immediate_wins}/{len(immediate_trades)})")
            print(f"   Total P&L: ${immediate_pnl:+,.2f}")
            print(f"   Avg P&L: ${immediate_avg:+,.2f}")

        # Confirmed trades stats
        if confirmed_trades:
            confirmed_wins = sum(1 for t in confirmed_trades if t['pnl_dollars'] > 0)
            confirmed_wr = (confirmed_wins / len(confirmed_trades) * 100)
            confirmed_pnl = sum(t['pnl_dollars'] for t in confirmed_trades)
            confirmed_avg = confirmed_pnl / len(confirmed_trades)

            avg_days = sum(t.get('days_to_confirmation', 0) for t in confirmed_trades) / len(confirmed_trades)

            print(f"\n✅ CONFIRMED ENTRIES (From Watchlist):")
            print(f"   Trades: {len(confirmed_trades)}")
            print(f"   Win Rate: {confirmed_wr:.1f}% ({confirmed_wins}/{len(confirmed_trades)})")
            print(f"   Total P&L: ${confirmed_pnl:+,.2f}")
            print(f"   Avg P&L: ${confirmed_avg:+,.2f}")
            print(f"   Avg Days to Confirmation: {avg_days:.1f}")

        # Comparison
        if immediate_trades and confirmed_trades:
            wr_improvement = confirmed_wr - immediate_wr
            pnl_improvement = confirmed_avg - immediate_avg

            print(f"\n📊 COMPARISON:")
            print(f"   Win Rate Improvement: {wr_improvement:+.1f}%")
            print(f"   Avg P&L Improvement: ${pnl_improvement:+,.2f}")

            if wr_improvement > 0:
                print(f"   ✅ Confirmation system improving win rate!")
            else:
                print(f"   ⚠️  Immediate entries performing better")

        # Per-signal breakdown
        print(f"\n{'─' * 80}")
        print(f"📋 BY SIGNAL TYPE:")
        print(f"{'─' * 80}")

        signal_stats = {}
        for trade in all_trades:
            signal = trade['entry_signal']
            was_watchlisted = trade.get('was_watchlisted', False)

            key = (signal, was_watchlisted)
            if key not in signal_stats:
                signal_stats[key] = {'trades': 0, 'wins': 0, 'total_pnl': 0}

            signal_stats[key]['trades'] += 1
            if trade['pnl_dollars'] > 0:
                signal_stats[key]['wins'] += 1
            signal_stats[key]['total_pnl'] += trade['pnl_dollars']

        for (signal, was_watchlisted), stats in sorted(signal_stats.items()):
            wr = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
            avg_pnl = stats['total_pnl'] / stats['trades'] if stats['trades'] > 0 else 0

            label = f"{signal} [CONFIRMED]" if was_watchlisted else f"{signal} [IMMEDIATE]"
            emoji = "✅" if was_watchlisted else "🟢"

            print(f"\n{emoji} {label}")
            print(f"   Trades: {stats['trades']} | WR: {wr:.1f}% | Avg: ${avg_pnl:+,.2f}")

        print(f"\n{'=' * 80}\n")

    def display_final_summary(self):
        """Display P&L summary from database (works in both modes)"""

        # Get all closed trades
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

        # Display summary
        mode = "From Memory (Backtest)" if Config.BACKTESTING else "From Database"
        print(f"\n{'=' * 80}")
        print(f"📊 FINAL P&L SUMMARY ({mode})")
        print(f"{'=' * 80}\n")

        print(f"📈 CLOSED TRADES: {len(closed_trades)} trades")
        print(f"   Winners: {len(winners)} trades")
        print(f"   Losers:  {len(losers)} trades")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Total Realized P&L: ${total_realized:+,.2f}")
        print(f"   Avg Win: ${avg_win:,.2f}")
        print(f"   Avg Loss: ${avg_loss:,.2f}")

        # Confirmation analysis
        self.display_confirmation_analysis()

        # Signal performance
        self._display_signal_performance(closed_trades)

        # Per-ticker performance
        self._display_ticker_performance(closed_trades)

        # Display last 50 trades
        print(f"\n📋 Trade Details (Last 50):")
        for t in closed_trades[:50]:
            score_display = f"[{t.get('entry_score', 0):.0f}]"
            watchlist_marker = " ✅" if t.get('was_watchlisted', False) else ""
            days_marker = f" ({t.get('days_to_confirmation', 0)}d)" if t.get('was_watchlisted', False) else ""
            print(f"   {t['ticker']:6} | ${t['pnl_dollars']:+9,.2f} ({t['pnl_pct']:+6.2f}%) | "
                  f"{score_display:5} {t['entry_signal']:15} → {t['exit_signal']:20}{watchlist_marker}{days_marker}")

        # Display open positions
        self._display_open_positions()

        print(f"\n{'=' * 80}\n")

    def _display_signal_performance(self, closed_trades):
        """Display performance by signal"""
        from collections import defaultdict

        signal_stats = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0
        })

        for trade in closed_trades:
            signal = trade['entry_signal']
            signal_stats[signal]['trades'].append(trade)
            signal_stats[signal]['total_pnl'] += trade['pnl_dollars']

            if trade['pnl_dollars'] > 0:
                signal_stats[signal]['wins'] += 1
            else:
                signal_stats[signal]['losses'] += 1

        print(f"\n🎯 PERFORMANCE BY ENTRY SIGNAL:")
        print(f"{'─' * 80}")

        sorted_signals = sorted(signal_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        for signal_name, stats in sorted_signals:
            total_trades = len(stats['trades'])
            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0

            wins = [t['pnl_dollars'] for t in stats['trades'] if t['pnl_dollars'] > 0]
            losses = [t['pnl_dollars'] for t in stats['trades'] if t['pnl_dollars'] < 0]

            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = sum(losses) / len(losses) if losses else 0

            print(f"\n   📊 {signal_name}")
            print(f"      Trades: {total_trades} ({stats['wins']}W / {stats['losses']}L)")
            print(f"      Win Rate: {win_rate:.1f}%")
            print(f"      Total P&L: ${stats['total_pnl']:+,.2f}")
            print(f"      Avg P&L: ${avg_pnl:+,.2f}")
            print(f"      Avg Win: ${avg_win:,.2f}")
            print(f"      Avg Loss: ${avg_loss:,.2f}")

        print(f"\n{'─' * 80}")

    def _display_ticker_performance(self, closed_trades):
        """Display performance by ticker"""
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

        print(f"\n💰 PERFORMANCE BY TICKER (WITH AWARDS):")
        print(f"{'─' * 100}")

        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        # Get award info
        award_info = {}
        try:
            if hasattr(self.strategy, 'stock_rotator'):
                rotator = self.strategy.stock_rotator
                for ticker in ticker_stats.keys():
                    award = rotator.get_award(ticker)
                    award_info[ticker] = award
        except:
            pass

        print(f"{'Ticker':<8} {'Award':<10} {'Trades':<8} {'W/L':<10} {'Win Rate':<10} {'Total P&L':<15} {'Avg P&L'}")
        print(f"{'─' * 100}")

        for ticker, stats in sorted_tickers:
            total_trades = stats['trades']
            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0
            avg_pnl_pct = stats['total_pnl_pct'] / total_trades if total_trades > 0 else 0

            w_l_str = f"{stats['wins']}W/{stats['losses']}L"

            award = award_info.get(ticker, 'unknown')
            award_emoji = {
                'premium': '🥇',
                'standard': '🥈',
                'trial': '🔬',
                'none': '⚪',
                'frozen': '❄️',
                'unknown': '❓'
            }.get(award, '❓')

            award_display = f"{award_emoji} {award[:7]}"

            print(f"{ticker:<8} {award_display:<10} {total_trades:<8} {w_l_str:<10} {win_rate:>5.1f}%     "
                  f"${stats['total_pnl']:>+10,.2f}   ${avg_pnl:>+8,.2f} ({avg_pnl_pct:>+5.1f}%)")

        print(f"{'─' * 100}")

        if sorted_tickers:
            best = sorted_tickers[0]
            worst = sorted_tickers[-1]

            best_award = award_info.get(best[0], 'unknown')
            worst_award = award_info.get(worst[0], 'unknown')

            print(
                f"\n🏆 BEST PERFORMER: {best[0]} [{best_award}] (${best[1]['total_pnl']:+,.2f} from {best[1]['trades']} trades)")
            print(
                f"⚠️  WORST PERFORMER: {worst[0]} [{worst_award}] (${worst[1]['total_pnl']:+,.2f} from {worst[1]['trades']} trades)")

    def _display_open_positions(self):
        """Display current open positions"""
        try:
            positions = self.strategy.get_positions()

            if not positions or len(positions) == 0:
                print(f"\n📊 No open positions")
                return

            print(f"\n📊 OPEN POSITIONS: {len(positions)}")
            total_unrealized = 0

            for position in positions:
                ticker = position.symbol
                quantity = int(position.quantity)
                entry_price = float(getattr(position, 'avg_entry_price', None) or
                                    getattr(position, 'avg_fill_price', 0))

                try:
                    current_price = self.strategy.get_last_price(ticker)
                    unrealized_pnl = (current_price - entry_price) * quantity
                    unrealized_pct = ((current_price - entry_price) / entry_price * 100)
                    total_unrealized += unrealized_pnl

                    print(f"   {ticker:6} | {quantity:,} shares @ ${entry_price:7.2f} | "
                          f"Current: ${current_price:7.2f} | "
                          f"P&L: ${unrealized_pnl:+,.2f} ({unrealized_pct:+.1f}%)")
                except:
                    print(f"   {ticker:6} | {quantity:,} shares @ ${entry_price:7.2f} | "
                          f"(price unavailable)")

            print(f"\n   Total Unrealized P&L: ${total_unrealized:+,.2f}")
        except Exception as e:
            print(f"\n⚠️ Could not retrieve open positions: {e}")


# =============================================================================
# ORDER EXECUTION LOGGER
# =============================================================================

class OrderLogger:
    """
    Logs successful order executions - dual mode support with confirmation tracking
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def log_order(self, ticker, side, quantity, signal_type='unknown',
                  award='none', quality_score=0, limit_price=None,
                  was_watchlisted=False, days_on_watchlist=0):
        """
        Log successful order submission with confirmation tracking

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


# =============================================================================
# DAILY METRICS RECORDER
# =============================================================================

class DailyMetricsRecorder:
    """
    Records daily portfolio metrics and signal performance cache - dual mode
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def record_daily_metrics(self, spy_close=None, market_regime=None):
        """
        Record daily portfolio metrics and update signal performance cache

        Args:
            spy_close: SPY closing price (optional)
            market_regime: Current market regime (optional)
        """
        try:
            current_date = self.strategy.get_datetime().date()

            # Calculate metrics
            portfolio_value = self.strategy.portfolio_value
            cash_balance = self.strategy.get_cash()

            positions = self.strategy.get_positions()
            num_positions = len(positions)

            # Calculate unrealized P&L
            unrealized_pnl = 0
            for position in positions:
                try:
                    ticker = position.symbol
                    qty = int(position.quantity)

                    entry_price = self._get_entry_price(position, ticker)
                    current_price = self.strategy.get_last_price(ticker)

                    if entry_price > 0:
                        unrealized_pnl += (current_price - entry_price) * qty
                except:
                    continue

            # Get today's trades
            if Config.BACKTESTING:
                today_trades = self.db.get_trades_by_date(current_date)
            else:
                conn = self.db.get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT pnl_dollars FROM closed_trades
                        WHERE DATE(exit_date) = %s
                    """, (current_date,))
                    today_trades = [{'pnl_dollars': row[0]} for row in cursor.fetchall()]
                finally:
                    cursor.close()
                    self.db.return_connection(conn)

            num_trades = len(today_trades)
            realized_pnl = sum(t['pnl_dollars'] for t in today_trades)

            if num_trades > 0:
                wins = sum(1 for t in today_trades if t['pnl_dollars'] > 0)
                win_rate = (wins / num_trades * 100)
            else:
                win_rate = 0

            # Save daily metrics
            if Config.BACKTESTING:
                self.db.upsert_daily_metrics(
                    date=current_date,
                    portfolio_value=portfolio_value,
                    cash_balance=cash_balance,
                    num_positions=num_positions,
                    num_trades=num_trades,
                    realized_pnl=realized_pnl,
                    unrealized_pnl=unrealized_pnl,
                    win_rate=win_rate,
                    spy_close=spy_close,
                    market_regime=market_regime
                )
            else:
                conn = self.db.get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO daily_metrics
                        (date, portfolio_value, cash_balance, num_positions, num_trades,
                         realized_pnl, unrealized_pnl, win_rate, spy_close, market_regime)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (date) DO UPDATE SET
                            portfolio_value = EXCLUDED.portfolio_value,
                            cash_balance = EXCLUDED.cash_balance,
                            num_positions = EXCLUDED.num_positions,
                            num_trades = EXCLUDED.num_trades,
                            realized_pnl = EXCLUDED.realized_pnl,
                            unrealized_pnl = EXCLUDED.unrealized_pnl,
                            win_rate = EXCLUDED.win_rate,
                            spy_close = EXCLUDED.spy_close,
                            market_regime = EXCLUDED.market_regime
                    """, (
                        current_date, portfolio_value, cash_balance, num_positions,
                        num_trades, realized_pnl, unrealized_pnl, win_rate,
                        spy_close, market_regime
                    ))
                    conn.commit()
                finally:
                    cursor.close()
                    self.db.return_connection(conn)

            print(f"[METRICS] Daily metrics recorded for {current_date}")

            # Update signal performance cache
            self._update_signal_performance_cache()

        except Exception as e:
            print(f"[WARN] Failed to record daily metrics: {e}")

    def _get_entry_price(self, position, ticker):
        """Helper to extract entry price from position"""
        if hasattr(position, 'avg_entry_price') and position.avg_entry_price:
            try:
                return float(position.avg_entry_price)
            except:
                pass

        if hasattr(position, 'cost_basis') and position.cost_basis:
            try:
                cost_basis = float(position.cost_basis)
                qty = float(position.quantity)
                return cost_basis / qty if qty > 0 else 0
            except:
                pass

        try:
            return self.strategy.get_last_price(ticker)
        except:
            return 0

    def _update_signal_performance_cache(self):
        """Update signal performance cache from all trades"""
        try:
            # Get all trades
            all_trades = self.strategy.profit_tracker.get_closed_trades()

            if not all_trades:
                return

            # Group by signal
            signal_stats = {}
            for trade in all_trades:
                signal = trade['entry_signal']

                if signal not in signal_stats:
                    signal_stats[signal] = {'trades': [], 'wins': 0, 'total_pnl': 0}

                signal_stats[signal]['trades'].append(trade)
                signal_stats[signal]['total_pnl'] += trade['pnl_dollars']

                if trade['pnl_dollars'] > 0:
                    signal_stats[signal]['wins'] += 1

            # Save each signal's performance
            for signal_name, stats in signal_stats.items():
                total_trades = len(stats['trades'])
                wins = stats['wins']
                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
                total_pnl = stats['total_pnl']
                avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

                if Config.BACKTESTING:
                    self.db.upsert_signal_performance(
                        signal_name=signal_name,
                        total_trades=total_trades,
                        wins=wins,
                        win_rate=win_rate,
                        total_pnl=total_pnl,
                        avg_pnl=avg_pnl
                    )
                else:
                    conn = self.db.get_connection()
                    try:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO signal_performance
                            (signal_name, total_trades, wins, win_rate, total_pnl, avg_pnl, last_updated)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (signal_name) DO UPDATE SET
                                total_trades = EXCLUDED.total_trades,
                                wins = EXCLUDED.wins,
                                win_rate = EXCLUDED.win_rate,
                                total_pnl = EXCLUDED.total_pnl,
                                avg_pnl = EXCLUDED.avg_pnl,
                                last_updated = EXCLUDED.last_updated
                        """, (
                            signal_name, total_trades, wins, win_rate,
                            total_pnl, avg_pnl, datetime.now()
                        ))
                        conn.commit()
                    finally:
                        cursor.close()
                        self.db.return_connection(conn)

            print(f"[METRICS] Signal performance cache updated ({len(signal_stats)} signals)")

        except Exception as e:
            print(f"[WARN] Failed to update signal performance cache: {e}")


# =============================================================================
# DAILY SUMMARY REPORTING (Dual-mode support)
# =============================================================================

def print_daily_summary(strategy, current_date):
    """
    Print comprehensive daily trading summary (queries database)
    Works in both PostgreSQL and in-memory modes
    """

    print(f"\n{'=' * 80}")
    print(f"📊 DAILY TRADING SUMMARY - {current_date.strftime('%Y-%m-%d')}")
    print(f"{'=' * 80}\n")

    # Portfolio overview continues in next message...