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
                     entry_signal, entry_score, exit_signal, exit_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    exit_date
                ))

                conn.commit()
                cursor.close()

            # Display immediate feedback
            emoji = "✅" if total_pnl > 0 else "❌"
            print(f"\n{emoji} TRADE CLOSED: {ticker} | ${total_pnl:+,.2f} ({pnl_pct:+.1f}%) | "
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

        # Signal performance
        self._display_signal_performance(closed_trades)

        # Per-ticker performance
        self._display_ticker_performance(closed_trades)

        # Display last 50 trades
        print(f"\n📋 Trade Details (Last 50):")
        for t in closed_trades[:50]:
            score_display = f"[{t.get('entry_score', 0):.0f}]"
            print(f"   {t['ticker']:6} | ${t['pnl_dollars']:+9,.2f} ({t['pnl_pct']:+6.2f}%) | "
                  f"{score_display:5} {t['entry_signal']:15} → {t['exit_signal']:20}")

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

    # =========================================================================
    # PORTFOLIO OVERVIEW
    # =========================================================================

    print(f"💰 PORTFOLIO STATUS:")
    print(f"   Total Value: ${strategy.portfolio_value:,.2f}")
    print(f"   Cash: ${strategy.get_cash():,.2f}")
    print(f"   Invested: ${strategy.portfolio_value - strategy.get_cash():,.2f}")

    # =========================================================================
    # ACTIVE POSITIONS SUMMARY
    # =========================================================================

    positions = strategy.get_positions()
    print(f"\n📈 ACTIVE POSITIONS: {len(positions)}")

    if positions:
        print(f"\n{'Ticker':<8} {'Qty':<8} {'Entry':<10} {'Current':<10} {'P&L $':<12} {'P&L %':<8} {'Award':<10}")
        print(f"{'─' * 80}")

        total_unrealized = 0

        for position in positions:
            ticker = position.symbol
            qty = int(position.quantity)
            entry_price = float(getattr(position, 'avg_entry_price', None) or
                                getattr(position, 'avg_fill_price', 0))

            try:
                current_price = strategy.get_last_price(ticker)
                pnl_dollars = (current_price - entry_price) * qty
                pnl_pct = ((current_price - entry_price) / entry_price * 100)
                total_unrealized += pnl_dollars

                award = strategy.stock_rotator.get_award(ticker)
                award_emoji = {
                    'premium': '🥇',
                    'standard': '🥈',
                    'trial': '🔬',
                    'none': '⚪',
                    'frozen': '❄️'
                }.get(award, '❓')
                award_display = f"{award_emoji} {award}"

                print(f"{ticker:<8} {qty:<8} ${entry_price:<9.2f} ${current_price:<9.2f} "
                      f"${pnl_dollars:>+10,.2f} {pnl_pct:>+6.1f}%  {award_display}")
            except:
                print(f"{ticker:<8} {qty:<8} ${entry_price:<9.2f} {'N/A':<10} {'N/A':<12} {'N/A':<8}")

        print(f"{'─' * 80}")
        print(f"{'TOTAL UNREALIZED P&L:':<50} ${total_unrealized:>+10,.2f}")

    # =========================================================================
    # TODAY'S CLOSED TRADES (Dual-mode)
    # =========================================================================

    db = get_database()

    if Config.BACKTESTING:
        # In-memory retrieval
        today_trades_data = db.get_trades_by_date(current_date.date())
        today_trades = [
            (t['ticker'], t['quantity'], t['entry_price'], t['exit_price'],
             t['pnl_dollars'], t['pnl_pct'], t['entry_signal'])
            for t in today_trades_data
        ]
    else:
        # PostgreSQL retrieval
        conn = db.get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct, entry_signal
                FROM closed_trades
                WHERE DATE(exit_date) = %s
                ORDER BY exit_date DESC
            """, (current_date.date(),))

            today_trades = cursor.fetchall()

        finally:
            cursor.close()
            db.return_connection(conn)

    if today_trades:
        print(f"\n🔄 TODAY'S CLOSED TRADES: {len(today_trades)}")
        print(f"\n{'Ticker':<8} {'Qty':<8} {'Entry':<10} {'Exit':<10} {'P&L $':<12} {'P&L %':<8} {'Signal'}")
        print(f"{'─' * 80}")

        total_realized_today = 0
        winners_today = 0

        for trade in today_trades:
            ticker = trade[0]
            qty = trade[1]
            entry = float(trade[2])
            exit_price = float(trade[3])
            pnl = float(trade[4])
            pnl_pct = float(trade[5])
            signal = trade[6]

            total_realized_today += pnl
            if pnl > 0:
                winners_today += 1

            emoji = "✅" if pnl > 0 else "❌"
            print(f"{emoji} {ticker:<6} {qty:<8} ${entry:<9.2f} ${exit_price:<9.2f} "
                  f"${pnl:>+10,.2f} {pnl_pct:>+6.1f}%  {signal}")

        print(f"{'─' * 80}")
        print(f"TODAY'S REALIZED P&L: ${total_realized_today:>+10,.2f}")

        if len(today_trades) > 0:
            today_wr = winners_today / len(today_trades) * 100
            print(f"Win Rate Today: {winners_today}/{len(today_trades)} ({today_wr:.1f}%)")
    else:
        print(f"\n🔄 TODAY'S CLOSED TRADES: None")

    # =========================================================================
    # STOCK ROTATION SUMMARY
    # =========================================================================

    print(f"\n🏆 STOCK ROTATION STATUS:")

    award_counts = {}
    for award in strategy.stock_rotator.ticker_awards.values():
        award_counts[award] = award_counts.get(award, 0) + 1

    for award_type in ['premium', 'standard', 'trial', 'none', 'frozen']:
        count = award_counts.get(award_type, 0)
        emoji = {
            'premium': '🥇',
            'standard': '🥈',
            'trial': '🔬',
            'none': '⚪',
            'frozen': '❄️'
        }.get(award_type, '❓')

        multiplier = {
            'premium': '1.3x',
            'standard': '1.0x',
            'trial': '1.0x',
            'none': '0.6x',
            'frozen': '0.0x'
        }.get(award_type, 'N/A')

        print(f"   {emoji} {award_type.title():<10} ({multiplier}): {count} stocks")

    # =========================================================================
    # PER-TICKER PERFORMANCE (All Time - Top 15)
    # =========================================================================

    print(f"\n📊 PER-TICKER PERFORMANCE (Top 15 - All Time):")
    print(f"\n{'Ticker':<8} {'Trades':<8} {'Wins':<8} {'Win Rate':<10} {'Total P&L':<12} {'Award'}")
    print(f"{'─' * 80}")

    # Get all closed trades
    all_trades = strategy.profit_tracker.get_closed_trades()

    if all_trades:
        from collections import defaultdict
        ticker_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0})

        for trade in all_trades:
            ticker = trade['ticker']
            ticker_stats[ticker]['trades'] += 1
            if trade['pnl_dollars'] > 0:
                ticker_stats[ticker]['wins'] += 1
            ticker_stats[ticker]['total_pnl'] += trade['pnl_dollars']

        # Sort by total P&L
        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        for ticker, stats in sorted_tickers[:15]:  # Top 15
            trades = stats['trades']
            wins = stats['wins']
            wr = (wins / trades * 100) if trades > 0 else 0
            total_pnl = stats['total_pnl']

            award = strategy.stock_rotator.get_award(ticker)
            award_emoji = {
                'premium': '🥇',
                'standard': '🥈',
                'trial': '🔬',
                'none': '⚪',
                'frozen': '❄️'
            }.get(award, '❓')

            emoji = "✅" if total_pnl > 0 else "❌"
            print(f"{emoji} {ticker:<6} {trades:<8} {wins:<8} {wr:>6.1f}%    ${total_pnl:>+10,.2f}  {award_emoji}")

    # =========================================================================
    # OVERALL PERFORMANCE (Dual-mode)
    # =========================================================================

    if Config.BACKTESTING:
        # In-memory calculation
        summary = db.get_all_trades_summary()
        total_trades = summary['total_trades']
        total_wins = summary['total_wins']
        total_realized = summary['total_realized']
    else:
        # PostgreSQL query
        conn = db.get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) as total_trades,
                       SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as total_wins,
                       SUM(pnl_dollars) as total_realized
                FROM closed_trades
            """)

            row = cursor.fetchone()
            total_trades = row[0] or 0
            total_wins = row[1] or 0
            total_realized = float(row[2]) if row[2] else 0.0

        finally:
            cursor.close()
            db.return_connection(conn)

    if total_trades > 0:
        overall_wr = (total_wins / total_trades * 100)

        print(f"\n{'─' * 80}")
        print(f"📊 OVERALL PERFORMANCE:")
        print(f"   Total Trades: {total_trades}")
        print(f"   Win Rate: {total_wins}/{total_trades} ({overall_wr:.1f}%)")
        print(f"   Total Realized P&L: ${total_realized:>+,.2f}")

    print(f"\n{'=' * 80}\n")