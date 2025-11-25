"""
Profit Tracking System - STREAMLINED VERSION

Includes:
- DailySummary: Consolidated daily logging system
- ProfitTracker: Database-backed trade recording
- OrderLogger: Order execution logging
"""

from datetime import datetime
from database import get_database
from config import Config


# =============================================================================
# DAILY SUMMARY LOGGER
# =============================================================================

class DailySummary:
    """Collects events during trading iteration and prints consolidated summary"""

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset for new trading day"""
        self.date = None
        self.portfolio_value = 0
        self.cash_balance = 0
        self.regime_status = None
        self.regime_reason = None
        self.regime_multiplier = 1.0

        # Trades
        self.exits = []  # {'ticker', 'qty', 'pnl', 'pnl_pct', 'reason'}
        self.entries = []  # {'ticker', 'qty', 'price', 'cost', 'signal', 'score'}
        self.profit_takes = []  # {'ticker', 'level', 'qty', 'pnl', 'pnl_pct'}

        # Signals
        self.signals_found = []  # {'ticker', 'signal', 'score'}
        self.signals_skipped = []  # {'ticker', 'reason'}

        # Warnings/Errors
        self.warnings = []
        self.errors = []

    def set_context(self, date, portfolio_value, cash_balance):
        """Set daily context"""
        self.date = date
        self.portfolio_value = portfolio_value
        self.cash_balance = cash_balance

    def set_regime(self, status, reason, multiplier):
        """Set market regime info"""
        self.regime_status = status
        self.regime_reason = reason
        self.regime_multiplier = multiplier

    def add_exit(self, ticker, qty, pnl, pnl_pct, reason):
        """Record an exit"""
        self.exits.append({
            'ticker': ticker, 'qty': qty, 'pnl': pnl,
            'pnl_pct': pnl_pct, 'reason': reason
        })

    def add_entry(self, ticker, qty, price, cost, signal, score):
        """Record an entry"""
        self.entries.append({
            'ticker': ticker, 'qty': qty, 'price': price,
            'cost': cost, 'signal': signal, 'score': score
        })

    def add_profit_take(self, ticker, level, qty, pnl, pnl_pct):
        """Record profit taking"""
        self.profit_takes.append({
            'ticker': ticker, 'level': level, 'qty': qty,
            'pnl': pnl, 'pnl_pct': pnl_pct
        })

    def add_signal(self, ticker, signal, score):
        """Record a signal found"""
        self.signals_found.append({'ticker': ticker, 'signal': signal, 'score': score})

    def add_skip(self, ticker, reason):
        """Record skipped signal"""
        self.signals_skipped.append({'ticker': ticker, 'reason': reason})

    def add_warning(self, msg):
        """Record warning"""
        self.warnings.append(msg)

    def add_error(self, msg):
        """Record error"""
        self.errors.append(msg)

    def print_summary(self):
        """Print consolidated daily summary"""
        date_str = self.date.strftime('%Y-%m-%d') if self.date else 'Unknown'

        # Header
        print(f"\n{'═' * 80}")
        print(f"📅 {date_str} | Portfolio: ${self.portfolio_value:,.0f} | Cash: ${self.cash_balance:,.0f}")

        # Regime (one line)
        if self.regime_status:
            regime_icon = {'normal': '✅', 'caution': '⚠️', 'stop_buying': '🚫', 'exit_all': '🚨'}.get(self.regime_status,
                                                                                                    '❓')
            print(
                f"   {regime_icon} Regime: {self.regime_status.upper()} ({self.regime_multiplier:.0%}) - {self.regime_reason}")

        # Profit Takes
        if self.profit_takes:
            for pt in self.profit_takes:
                print(
                    f"   💰 PROFIT L{pt['level']}: {pt['ticker']} x{pt['qty']} | ${pt['pnl']:+,.2f} ({pt['pnl_pct']:+.1f}%)")

        # Full Exits
        full_exits = [e for e in self.exits if 'profit_level' not in str(e.get('reason', ''))]
        if full_exits:
            for ex in full_exits:
                emoji = '✅' if ex['pnl'] > 0 else '❌'
                print(
                    f"   {emoji} EXIT: {ex['ticker']} x{ex['qty']} | ${ex['pnl']:+,.2f} ({ex['pnl_pct']:+.1f}%) - {ex['reason']}")

        # Entries
        if self.entries:
            for en in self.entries:
                print(
                    f"   🟢 BUY: {en['ticker']} x{en['qty']} @ ${en['price']:.2f} (${en['cost']:,.0f}) | {en['signal']} [{en['score']}]")

        # Signals summary (compact)
        if self.signals_found and not self.entries:
            tickers = [f"{s['ticker']}[{s['score']}]" for s in self.signals_found[:5]]
            print(f"   📊 Signals: {', '.join(tickers)}" + (" ..." if len(self.signals_found) > 5 else ""))

        # Warnings (compact)
        if self.warnings:
            for w in self.warnings[:3]:
                print(f"   ⚠️ {w}")

        # Errors
        if self.errors:
            for e in self.errors[:3]:
                print(f"   ❌ {e}")

        # Nothing happened
        if not any([self.profit_takes, self.exits, self.entries, self.warnings, self.errors]):
            if self.regime_status in ['stop_buying', 'exit_all']:
                pass  # Regime already explains why
            else:
                print(f"   (No activity)")

        print(f"{'═' * 80}")


# Global summary instance
_summary = None


def get_summary():
    """Get or create global summary instance"""
    global _summary
    if _summary is None:
        _summary = DailySummary()
    return _summary


def reset_summary():
    """Reset for new iteration"""
    global _summary
    if _summary:
        _summary.reset()
    else:
        _summary = DailySummary()
    return _summary


# =============================================================================
# PROFIT TRACKER
# =============================================================================

class ProfitTracker:
    """Database-backed profit tracker"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def record_trade(self, ticker, quantity_sold, entry_price, exit_price,
                     exit_date, entry_signal, exit_signal, entry_score=0):
        """Record completed trade - minimal logging"""

        pnl_per_share = exit_price - entry_price
        total_pnl = pnl_per_share * quantity_sold
        pnl_pct = (pnl_per_share / entry_price * 100) if entry_price > 0 else 0

        conn = self.db.get_connection()
        try:
            if Config.BACKTESTING:
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
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO closed_trades 
                    (ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date,
                     was_watchlisted, confirmation_date, days_to_confirmation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    ticker, quantity_sold, entry_price, exit_price, total_pnl, pnl_pct,
                    entry_signal, entry_score, exit_signal.get('reason', 'unknown'),
                    exit_date, False, None, 0
                ))
                conn.commit()
                cursor.close()

        except Exception as e:
            if not Config.BACKTESTING:
                conn.rollback()
            raise
        finally:
            self.db.return_connection(conn)

    def get_closed_trades(self, limit=None):
        """Get closed trades from database"""
        if Config.BACKTESTING:
            return self.db.get_closed_trades(limit)

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if limit:
                cursor.execute("""
                    SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                           entry_signal, entry_score, exit_signal, exit_date
                    FROM closed_trades ORDER BY exit_date DESC LIMIT %s
                """, (limit,))
            else:
                cursor.execute("""
                    SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                           entry_signal, entry_score, exit_signal, exit_date
                    FROM closed_trades ORDER BY exit_date DESC
                """)

            trades = []
            for row in cursor.fetchall():
                trades.append({
                    'ticker': row[0], 'quantity': row[1],
                    'entry_price': float(row[2]), 'exit_price': float(row[3]),
                    'pnl_dollars': float(row[4]), 'pnl_pct': float(row[5]),
                    'entry_signal': row[6], 'entry_score': row[7],
                    'exit_signal': row[8], 'exit_date': row[9]
                })
            return trades
        finally:
            cursor.close()
            self.db.return_connection(conn)

    def display_final_summary(self, stock_rotator=None, regime_detector=None):
        """Display final P&L summary"""
        closed_trades = self.get_closed_trades()

        if not closed_trades:
            print("\n📊 No closed trades")
            return

        winners = [t for t in closed_trades if t['pnl_dollars'] > 0]
        losers = [t for t in closed_trades if t['pnl_dollars'] < 0]
        total_realized = sum(t['pnl_dollars'] for t in closed_trades)
        win_rate = (len(winners) / len(closed_trades) * 100) if closed_trades else 0

        avg_win = sum(t['pnl_dollars'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl_dollars'] for t in losers) / len(losers) if losers else 0

        print(f"\n{'=' * 80}")
        print(f"📊 FINAL SUMMARY")
        print(f"{'=' * 80}")
        print(f"Trades: {len(closed_trades)} | Win Rate: {win_rate:.1f}% ({len(winners)}W/{len(losers)}L)")
        print(f"Total P&L: ${total_realized:+,.2f} | Avg Win: ${avg_win:,.2f} | Avg Loss: ${avg_loss:,.2f}")

        if winners and losers and avg_loss != 0:
            profit_factor = abs(avg_win * len(winners) / (avg_loss * len(losers)))
            print(f"Profit Factor: {profit_factor:.2f}")

        # Signal performance (compact)
        self._display_signal_summary(closed_trades)

        # Top/Bottom performers (compact)
        self._display_ticker_summary(closed_trades)

        if stock_rotator:
            stats = stock_rotator.get_statistics()
            dist = stats['award_distribution']
            print(f"\n🏆 Rotation: 🥇{dist.get('premium', 0)} 🥈{dist.get('standard', 0)} ❄️{dist.get('frozen', 0)}")

        if regime_detector:
            stats = regime_detector.get_statistics()
            spy_vs_200 = ((stats['spy_close'] - stats['spy_200_sma']) / stats['spy_200_sma'] * 100) if stats['spy_200_sma'] > 0 else 0
            print(f"🛡️ Safeguard: Dist={stats['distribution_days']}d | SPY vs 200: {spy_vs_200:+.1f}%")
        print(f"{'=' * 80}\n")

    def _display_signal_summary(self, closed_trades):
        """Compact signal performance"""
        from collections import defaultdict

        signal_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})

        for trade in closed_trades:
            signal = trade['entry_signal']
            signal_stats[signal]['trades'] += 1
            if trade['pnl_dollars'] > 0:
                signal_stats[signal]['wins'] += 1
            signal_stats[signal]['pnl'] += trade['pnl_dollars']

        print(f"\n📈 BY SIGNAL:")
        for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
            wr = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
            print(f"   {signal[:20]:<20} {stats['trades']:>3} trades | {wr:>5.1f}% WR | ${stats['pnl']:>+10,.2f}")

    def _display_ticker_summary(self, closed_trades):
        """Compact ticker performance"""
        from collections import defaultdict

        ticker_stats = defaultdict(lambda: {'trades': 0, 'pnl': 0.0})

        for trade in closed_trades:
            ticker = trade['ticker']
            ticker_stats[ticker]['trades'] += 1
            ticker_stats[ticker]['pnl'] += trade['pnl_dollars']

        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)

        print(f"\n📊 TOP 5:")
        for ticker, stats in sorted_tickers[:5]:
            print(f"   {ticker:<6} {stats['trades']:>3} trades | ${stats['pnl']:>+10,.2f}")

        if len(sorted_tickers) > 5:
            print(f"\n📉 BOTTOM 3:")
            for ticker, stats in sorted_tickers[-3:]:
                print(f"   {ticker:<6} {stats['trades']:>3} trades | ${stats['pnl']:>+10,.2f}")


# =============================================================================
# ORDER LOGGER
# =============================================================================

class OrderLogger:
    """Order execution logger"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def log_order(self, ticker, side, quantity, signal_type='unknown',
                  award='none', quality_score=0, limit_price=None,
                  was_watchlisted=False, days_on_watchlist=0):
        """Log order - silent operation"""
        try:
            filled_price = self.strategy.get_last_price(ticker) if limit_price is None else limit_price
            portfolio_value = self.strategy.portfolio_value
            cash_before = self.strategy.get_cash()
            submitted_at = self.strategy.get_datetime()

            if Config.BACKTESTING:
                self.db.insert_order_log(
                    ticker=ticker, side=side, quantity=quantity,
                    order_type='market', limit_price=limit_price,
                    filled_price=filled_price, submitted_at=submitted_at,
                    signal_type=signal_type, portfolio_value=portfolio_value,
                    cash_before=cash_before, award=award,
                    quality_score=quality_score, broker_order_id=None,
                    was_watchlisted=was_watchlisted, days_on_watchlist=days_on_watchlist
                )
            else:
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
            pass  # Silent fail for logging