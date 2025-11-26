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
        """Display comprehensive final P&L summary"""
        closed_trades = self.get_closed_trades()

        if not closed_trades:
            print("\n📊 No closed trades")
            return

        print(f"\n{'=' * 100}")
        print(f"{'📊 FINAL TRADING SUMMARY':^100}")
        print(f"{'=' * 100}")

        # 1. Overall Performance
        self._display_overall_performance(closed_trades)

        # 2. Performance by Signal
        self._display_signal_summary(closed_trades)

        # 3. Performance by Ticker
        self._display_ticker_summary(closed_trades, stock_rotator)

        # 4. Last 100 Trades
        self._display_last_100_trades(closed_trades)

        # 5. Stock Rotation Summary
        self._display_rotation_summary(stock_rotator)

        # 6. Safeguard/Drawdown Protection Summary
        self._display_safeguard_summary(regime_detector)

        print(f"{'=' * 100}\n")

    def _display_overall_performance(self, closed_trades):
        """Display overall performance metrics"""
        from collections import defaultdict

        total_trades = len(closed_trades)
        winners = [t for t in closed_trades if t['pnl_dollars'] > 0]
        losers = [t for t in closed_trades if t['pnl_dollars'] < 0]
        breakeven = [t for t in closed_trades if t['pnl_dollars'] == 0]

        total_realized = sum(t['pnl_dollars'] for t in closed_trades)
        win_rate = (len(winners) / total_trades * 100) if total_trades > 0 else 0

        avg_win = sum(t['pnl_dollars'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl_dollars'] for t in losers) / len(losers) if losers else 0

        gross_profit = sum(t['pnl_dollars'] for t in winners)
        gross_loss = abs(sum(t['pnl_dollars'] for t in losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        print(f"\n{'─' * 100}")
        print(f"📈 OVERALL PERFORMANCE")
        print(f"{'─' * 100}")
        print(f"{'Metric':<25} {'Value':>20}")
        print(f"{'─' * 45}")
        print(f"{'Total Trades':<25} {total_trades:>20}")
        print(f"{'Win Rate':<25} {f'{win_rate:.1f}% ({len(winners)}/{total_trades})':>20}")
        print(f"{'Wins':<25} {len(winners):>20}")
        print(f"{'Losses':<25} {len(losers):>20}")
        print(f"{'Breakeven':<25} {len(breakeven):>20}")
        print(f"{'Avg Win':<25} {f'${avg_win:,.2f}':>20}")
        print(f"{'Avg Loss':<25} {f'${avg_loss:,.2f}':>20}")
        print(f"{'Total Realized P&L':<25} {f'${total_realized:+,.2f}':>20}")
        print(f"{'Profit Factor':<25} {f'{profit_factor:.2f}':>20}")

    def _display_signal_summary(self, closed_trades):
        """Display performance by signal type"""
        from collections import defaultdict

        signal_stats = defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0
        })

        for trade in closed_trades:
            signal = trade['entry_signal']
            pnl = trade['pnl_dollars']
            signal_stats[signal]['trades'] += 1
            signal_stats[signal]['total_pnl'] += pnl

            if pnl > 0:
                signal_stats[signal]['wins'] += 1
                signal_stats[signal]['win_pnl'] += pnl
            elif pnl < 0:
                signal_stats[signal]['losses'] += 1
                signal_stats[signal]['loss_pnl'] += pnl

        print(f"\n{'─' * 100}")
        print(f"📊 PERFORMANCE BY SIGNAL")
        print(f"{'─' * 100}")
        header = f"{'Signal':<25} {'Trades':>7} {'WR%':>8} {'Wins':>6} {'Losses':>7} {'Avg Win':>12} {'Avg Loss':>12} {'Total P&L':>14}"
        print(header)
        print(f"{'─' * 100}")

        for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True):
            trades = stats['trades']
            wins = stats['wins']
            losses = stats['losses']
            wr = (wins / trades * 100) if trades > 0 else 0
            avg_win = (stats['win_pnl'] / wins) if wins > 0 else 0
            avg_loss = (stats['loss_pnl'] / losses) if losses > 0 else 0
            total_pnl = stats['total_pnl']

            print(f"{signal[:25]:<25} {trades:>7} {wr:>7.1f}% {wins:>6} {losses:>7} {f'${avg_win:,.2f}':>12} {f'${avg_loss:,.2f}':>12} {f'${total_pnl:+,.2f}':>14}")

    def _display_ticker_summary(self, closed_trades, stock_rotator=None):
        """Display performance by ticker with rotation tier"""
        from collections import defaultdict

        ticker_stats = defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0
        })

        for trade in closed_trades:
            ticker = trade['ticker']
            pnl = trade['pnl_dollars']
            ticker_stats[ticker]['trades'] += 1
            ticker_stats[ticker]['total_pnl'] += pnl

            if pnl > 0:
                ticker_stats[ticker]['wins'] += 1
                ticker_stats[ticker]['win_pnl'] += pnl
            elif pnl < 0:
                ticker_stats[ticker]['losses'] += 1
                ticker_stats[ticker]['loss_pnl'] += pnl

        print(f"\n{'─' * 100}")
        print(f"📊 PERFORMANCE BY TICKER")
        print(f"{'─' * 100}")
        header = f"{'Ticker':<8} {'Tier':<10} {'Trades':>7} {'WR%':>8} {'Wins':>6} {'Losses':>7} {'Avg Win':>12} {'Avg Loss':>12} {'Total P&L':>14}"
        print(header)
        print(f"{'─' * 100}")

        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        for ticker, stats in sorted_tickers:
            trades = stats['trades']
            wins = stats['wins']
            losses = stats['losses']
            wr = (wins / trades * 100) if trades > 0 else 0
            avg_win = (stats['win_pnl'] / wins) if wins > 0 else 0
            avg_loss = (stats['loss_pnl'] / losses) if losses > 0 else 0
            total_pnl = stats['total_pnl']

            # Get rotation tier
            tier = 'standard'
            tier_icon = '🥈'
            if stock_rotator:
                tier = stock_rotator.get_award(ticker)
                tier_icon = {'premium': '🥇', 'standard': '🥈', 'frozen': '❄️'}.get(tier, '🥈')

            tier_display = f"{tier_icon}{tier[:7]}"
            print(f"{ticker:<8} {tier_display:<10} {trades:>7} {wr:>7.1f}% {wins:>6} {losses:>7} {f'${avg_win:,.2f}':>12} {f'${avg_loss:,.2f}':>12} {f'${total_pnl:+,.2f}':>14}")

    def _display_last_100_trades(self, closed_trades):
        """Display last 100 trades"""
        print(f"\n{'─' * 100}")
        print(f"📜 LAST 100 TRADES")
        print(f"{'─' * 100}")
        header = f"{'#':<4} {'Ticker':<8} {'P&L $':>12} {'P&L %':>8} {'Score':>6} {'Signal':<25} {'Exit Reason':<25}"
        print(header)
        print(f"{'─' * 100}")

        # Get last 100 trades (already sorted by exit_date desc from get_closed_trades)
        recent_trades = closed_trades[:100]

        for i, trade in enumerate(recent_trades, 1):
            ticker = trade['ticker']
            pnl_dollars = trade['pnl_dollars']
            pnl_pct = trade['pnl_pct']
            score = trade.get('entry_score', 0)
            signal = trade['entry_signal']
            exit_reason = trade.get('exit_signal', 'unknown')

            # Truncate long strings
            signal_display = signal[:25] if len(signal) > 25 else signal
            exit_display = exit_reason[:25] if len(exit_reason) > 25 else exit_reason

            emoji = '✅' if pnl_dollars > 0 else '❌' if pnl_dollars < 0 else '➖'
            print(f"{i:<4} {emoji}{ticker:<7} {f'${pnl_dollars:+,.2f}':>12} {f'{pnl_pct:+.1f}%':>8} {score:>6} {signal_display:<25} {exit_display:<25}")

    def _display_rotation_summary(self, stock_rotator):
        """Display stock rotation summary"""
        print(f"\n{'─' * 100}")
        print(f"🏆 STOCK ROTATION SUMMARY")
        print(f"{'─' * 100}")

        if not stock_rotator:
            print("   Stock rotation not available")
            return

        stats = stock_rotator.get_statistics()
        dist = stats['award_distribution']

        print(f"{'Metric':<30} {'Value':>20}")
        print(f"{'─' * 50}")
        print(f"{'Total Rotations':<30} {stats['rotation_count']:>20}")
        print(f"{'Last Rotation':<30} {str(stats['last_rotation_date'])[:19] if stats['last_rotation_date'] else 'N/A':>20}")
        print(f"{'Total Tickers Tracked':<30} {stats['total_tracked']:>20}")

        print(f"\n{'Tier Distribution:'}")
        print(f"   🥇 Premium:  {dist.get('premium', 0):>5} tickers (1.5x size)")
        print(f"   🥈 Standard: {dist.get('standard', 0):>5} tickers (1.0x size)")
        print(f"   ❄️  Frozen:   {dist.get('frozen', 0):>5} tickers (blocked)")

        if stats['premium_stocks']:
            print(f"\n   Premium Tickers: {', '.join(stats['premium_stocks'])}")

        if stats['frozen_stocks']:
            print(f"   Frozen Tickers:  {', '.join(stats['frozen_stocks'])}")

        if stats['recovery_tracking']:
            print(f"\n   Recovery Tracking: {len(stats['recovery_tracking'])} ticker(s) in recovery")
            for ticker, passes in stats['recovery_tracking'].items():
                print(f"      {ticker}: {passes}/3 consecutive passes")

    def _display_safeguard_summary(self, regime_detector):
        """Display drawdown protection / market safeguard summary"""
        print(f"\n{'─' * 100}")
        print(f"🛡️ MARKET SAFEGUARD SUMMARY")
        print(f"{'─' * 100}")

        if not regime_detector:
            print("   Regime detector not available")
            return

        stats = regime_detector.get_statistics()

        # SPY status
        spy_vs_50 = ((stats['spy_close'] - stats['spy_50_sma']) / stats['spy_50_sma'] * 100) if stats['spy_50_sma'] > 0 else 0
        spy_vs_200 = ((stats['spy_close'] - stats['spy_200_sma']) / stats['spy_200_sma'] * 100) if stats['spy_200_sma'] > 0 else 0

        print(f"{'Metric':<35} {'Value':>25}")
        print(f"{'─' * 60}")
        print(f"{'SPY Close':<35} {f'${stats["spy_close"]:.2f}':>25}")
        print(f"{'SPY 50 SMA':<35} {f'${stats["spy_50_sma"]:.2f} ({spy_vs_50:+.1f}%)':>25}")
        print(f"{'SPY 200 SMA':<35} {f'${stats["spy_200_sma"]:.2f} ({spy_vs_200:+.1f}%)':>25}")

        # Status indicators
        status_50 = '🟢 Above' if not stats['spy_below_50'] else '🔴 Below'
        status_200 = '🟢 Above' if not stats['spy_below_200'] else '🔴 Below'
        print(f"{'SPY vs 50 SMA':<35} {status_50:>25}")
        print(f"{'SPY vs 200 SMA':<35} {status_200:>25}")

        # Distribution/Accumulation
        print(f"\n{'Distribution/Accumulation Days (25-day lookback):'}")
        print(f"   Distribution Days:  {stats['distribution_days']:>5}")
        print(f"   Accumulation Days:  {stats['accumulation_days']:>5}")
        print(f"   Net Distribution:   {stats['net_distribution']:>5}")

        # Distribution level interpretation
        level = stats['distribution_level']
        level_desc = {
            'normal': '🟢 Normal (100% size)',
            'caution': '🟡 Caution (75% size)',
            'warning': '🟠 Warning (50% size)',
            'danger': '🔴 Danger (0% - stop buying)',
            'exit': '🚨 Exit All (waiting for follow-through)'
        }.get(level, level)
        print(f"   Current Level:      {level_desc}")

        # Rally attempt status
        if stats['in_rally_attempt'] or stats['in_recovery']:
            print(f"\n{'Rally Attempt Status:'}")
            print(f"   In Rally Attempt:   {'Yes' if stats['in_rally_attempt'] else 'No'}")
            print(f"   Rally Day Count:    {stats['rally_day_count']}/4+")
            print(f"   Follow-Through:     {'✅ Confirmed' if stats['follow_through_confirmed'] else '⏳ Waiting'}")

        if stats['exit_date']:
            print(f"   Exit Triggered:     {str(stats['exit_date'])[:19]}")

    def generate_final_summary_html(self, stock_rotator=None, regime_detector=None):
        """Generate HTML version of final summary for email"""
        closed_trades = self.get_closed_trades()

        if not closed_trades:
            return "<p>No closed trades</p>"

        html = ""

        # 1. Overall Performance
        html += self._generate_overall_performance_html(closed_trades)

        # 2. Performance by Signal
        html += self._generate_signal_summary_html(closed_trades)

        # 3. Performance by Ticker
        html += self._generate_ticker_summary_html(closed_trades, stock_rotator)

        # 4. Last 100 Trades
        html += self._generate_last_100_trades_html(closed_trades)

        # 5. Stock Rotation Summary
        html += self._generate_rotation_summary_html(stock_rotator)

        # 6. Safeguard Summary
        html += self._generate_safeguard_summary_html(regime_detector)

        return html

    def _generate_overall_performance_html(self, closed_trades):
        """Generate HTML for overall performance"""
        total_trades = len(closed_trades)
        winners = [t for t in closed_trades if t['pnl_dollars'] > 0]
        losers = [t for t in closed_trades if t['pnl_dollars'] < 0]

        total_realized = sum(t['pnl_dollars'] for t in closed_trades)
        win_rate = (len(winners) / total_trades * 100) if total_trades > 0 else 0
        avg_win = sum(t['pnl_dollars'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl_dollars'] for t in losers) / len(losers) if losers else 0

        gross_profit = sum(t['pnl_dollars'] for t in winners)
        gross_loss = abs(sum(t['pnl_dollars'] for t in losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        pnl_color = '#27ae60' if total_realized > 0 else '#e74c3c'

        return f"""
        <h3>📈 Overall Performance</h3>
        <table>
            <tr><td><strong>Total Trades:</strong></td><td>{total_trades}</td></tr>
            <tr><td><strong>Win Rate:</strong></td><td>{win_rate:.1f}% ({len(winners)}/{total_trades})</td></tr>
            <tr><td><strong>Wins:</strong></td><td>{len(winners)}</td></tr>
            <tr><td><strong>Losses:</strong></td><td>{len(losers)}</td></tr>
            <tr><td><strong>Avg Win:</strong></td><td>${avg_win:,.2f}</td></tr>
            <tr><td><strong>Avg Loss:</strong></td><td>${avg_loss:,.2f}</td></tr>
            <tr><td><strong>Total P&L:</strong></td><td style="color: {pnl_color}; font-weight: bold;">${total_realized:+,.2f}</td></tr>
            <tr><td><strong>Profit Factor:</strong></td><td>{profit_factor:.2f}</td></tr>
        </table>
        """

    def _generate_signal_summary_html(self, closed_trades):
        """Generate HTML for signal performance"""
        from collections import defaultdict

        signal_stats = defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0
        })

        for trade in closed_trades:
            signal = trade['entry_signal']
            pnl = trade['pnl_dollars']
            signal_stats[signal]['trades'] += 1
            signal_stats[signal]['total_pnl'] += pnl
            if pnl > 0:
                signal_stats[signal]['wins'] += 1
                signal_stats[signal]['win_pnl'] += pnl
            elif pnl < 0:
                signal_stats[signal]['losses'] += 1
                signal_stats[signal]['loss_pnl'] += pnl

        html = """
        <h3>📊 Performance by Signal</h3>
        <table>
            <tr>
                <th>Signal</th><th>Trades</th><th>WR%</th><th>Wins</th><th>Losses</th>
                <th>Avg Win</th><th>Avg Loss</th><th>Total P&L</th>
            </tr>
        """

        for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True):
            trades = stats['trades']
            wins = stats['wins']
            losses = stats['losses']
            wr = (wins / trades * 100) if trades > 0 else 0
            avg_win = (stats['win_pnl'] / wins) if wins > 0 else 0
            avg_loss = (stats['loss_pnl'] / losses) if losses > 0 else 0
            total_pnl = stats['total_pnl']
            pnl_color = '#27ae60' if total_pnl > 0 else '#e74c3c'

            html += f"""
            <tr>
                <td><strong>{signal}</strong></td>
                <td>{trades}</td>
                <td>{wr:.1f}%</td>
                <td>{wins}</td>
                <td>{losses}</td>
                <td>${avg_win:,.2f}</td>
                <td>${avg_loss:,.2f}</td>
                <td style="color: {pnl_color}; font-weight: bold;">${total_pnl:+,.2f}</td>
            </tr>
            """

        html += "</table>"
        return html

    def _generate_ticker_summary_html(self, closed_trades, stock_rotator=None):
        """Generate HTML for ticker performance"""
        from collections import defaultdict

        ticker_stats = defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0
        })

        for trade in closed_trades:
            ticker = trade['ticker']
            pnl = trade['pnl_dollars']
            ticker_stats[ticker]['trades'] += 1
            ticker_stats[ticker]['total_pnl'] += pnl
            if pnl > 0:
                ticker_stats[ticker]['wins'] += 1
                ticker_stats[ticker]['win_pnl'] += pnl
            elif pnl < 0:
                ticker_stats[ticker]['losses'] += 1
                ticker_stats[ticker]['loss_pnl'] += pnl

        html = """
        <h3>📊 Performance by Ticker</h3>
        <table>
            <tr>
                <th>Ticker</th><th>Tier</th><th>Trades</th><th>WR%</th><th>Wins</th><th>Losses</th>
                <th>Avg Win</th><th>Avg Loss</th><th>Total P&L</th>
            </tr>
        """

        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        for ticker, stats in sorted_tickers:
            trades = stats['trades']
            wins = stats['wins']
            losses = stats['losses']
            wr = (wins / trades * 100) if trades > 0 else 0
            avg_win = (stats['win_pnl'] / wins) if wins > 0 else 0
            avg_loss = (stats['loss_pnl'] / losses) if losses > 0 else 0
            total_pnl = stats['total_pnl']
            pnl_color = '#27ae60' if total_pnl > 0 else '#e74c3c'

            tier = 'standard'
            tier_icon = '🥈'
            if stock_rotator:
                tier = stock_rotator.get_award(ticker)
                tier_icon = {'premium': '🥇', 'standard': '🥈', 'frozen': '❄️'}.get(tier, '🥈')

            html += f"""
            <tr>
                <td><strong>{ticker}</strong></td>
                <td>{tier_icon} {tier}</td>
                <td>{trades}</td>
                <td>{wr:.1f}%</td>
                <td>{wins}</td>
                <td>{losses}</td>
                <td>${avg_win:,.2f}</td>
                <td>${avg_loss:,.2f}</td>
                <td style="color: {pnl_color}; font-weight: bold;">${total_pnl:+,.2f}</td>
            </tr>
            """

        html += "</table>"
        return html

    def _generate_last_100_trades_html(self, closed_trades):
        """Generate HTML for last 100 trades"""
        html = """
        <h3>📜 Last 100 Trades</h3>
        <table>
            <tr>
                <th>#</th><th>Ticker</th><th>P&L $</th><th>P&L %</th>
                <th>Score</th><th>Signal</th><th>Exit</th>
            </tr>
        """

        recent_trades = closed_trades[:100]

        for i, trade in enumerate(recent_trades, 1):
            pnl_dollars = trade['pnl_dollars']
            pnl_pct = trade['pnl_pct']
            pnl_color = '#27ae60' if pnl_dollars > 0 else '#e74c3c' if pnl_dollars < 0 else '#7f8c8d'
            emoji = '✅' if pnl_dollars > 0 else '❌' if pnl_dollars < 0 else '➖'

            html += f"""
            <tr>
                <td>{i}</td>
                <td>{emoji} <strong>{trade['ticker']}</strong></td>
                <td style="color: {pnl_color};">${pnl_dollars:+,.2f}</td>
                <td style="color: {pnl_color};">{pnl_pct:+.1f}%</td>
                <td>{trade.get('entry_score', 0)}</td>
                <td>{trade['entry_signal']}</td>
                <td>{trade.get('exit_signal', 'unknown')}</td>
            </tr>
            """

        html += "</table>"
        return html

    def _generate_rotation_summary_html(self, stock_rotator):
        """Generate HTML for rotation summary"""
        if not stock_rotator:
            return "<h3>🏆 Stock Rotation</h3><p>Not available</p>"

        stats = stock_rotator.get_statistics()
        dist = stats['award_distribution']

        html = f"""
        <h3>🏆 Stock Rotation Summary</h3>
        <table>
            <tr><td><strong>Total Rotations:</strong></td><td>{stats['rotation_count']}</td></tr>
            <tr><td><strong>Tickers Tracked:</strong></td><td>{stats['total_tracked']}</td></tr>
        </table>
        <h4>Tier Distribution</h4>
        <table>
            <tr><td>🥇 Premium (1.5x)</td><td>{dist.get('premium', 0)} tickers</td></tr>
            <tr><td>🥈 Standard (1.0x)</td><td>{dist.get('standard', 0)} tickers</td></tr>
            <tr><td>❄️ Frozen (blocked)</td><td>{dist.get('frozen', 0)} tickers</td></tr>
        </table>
        """

        if stats['premium_stocks']:
            html += f"<p><strong>Premium:</strong> {', '.join(stats['premium_stocks'])}</p>"
        if stats['frozen_stocks']:
            html += f"<p><strong>Frozen:</strong> {', '.join(stats['frozen_stocks'])}</p>"

        return html

    def _generate_safeguard_summary_html(self, regime_detector):
        """Generate HTML for safeguard summary"""
        if not regime_detector:
            return "<h3>🛡️ Market Safeguard</h3><p>Not available</p>"

        stats = regime_detector.get_statistics()

        spy_vs_50 = ((stats['spy_close'] - stats['spy_50_sma']) / stats['spy_50_sma'] * 100) if stats['spy_50_sma'] > 0 else 0
        spy_vs_200 = ((stats['spy_close'] - stats['spy_200_sma']) / stats['spy_200_sma'] * 100) if stats['spy_200_sma'] > 0 else 0

        status_50 = '🟢 Above' if not stats['spy_below_50'] else '🔴 Below'
        status_200 = '🟢 Above' if not stats['spy_below_200'] else '🔴 Below'

        level = stats['distribution_level']
        level_desc = {
            'normal': '🟢 Normal (100%)',
            'caution': '🟡 Caution (75%)',
            'warning': '🟠 Warning (50%)',
            'danger': '🔴 Danger (0%)',
            'exit': '🚨 Exit All'
        }.get(level, level)

        html = f"""
        <h3>🛡️ Market Safeguard Summary</h3>
        <table>
            <tr><td><strong>SPY Close:</strong></td><td>${stats['spy_close']:.2f}</td></tr>
            <tr><td><strong>SPY vs 50 SMA:</strong></td><td>{status_50} ({spy_vs_50:+.1f}%)</td></tr>
            <tr><td><strong>SPY vs 200 SMA:</strong></td><td>{status_200} ({spy_vs_200:+.1f}%)</td></tr>
            <tr><td><strong>Distribution Days:</strong></td><td>{stats['distribution_days']}</td></tr>
            <tr><td><strong>Accumulation Days:</strong></td><td>{stats['accumulation_days']}</td></tr>
            <tr><td><strong>Net Distribution:</strong></td><td>{stats['net_distribution']}</td></tr>
            <tr><td><strong>Current Level:</strong></td><td>{level_desc}</td></tr>
        </table>
        """

        if stats['in_rally_attempt'] or stats['in_recovery']:
            html += f"""
            <h4>Rally Attempt Status</h4>
            <table>
                <tr><td>Rally Day Count:</td><td>{stats['rally_day_count']}/4+</td></tr>
                <tr><td>Follow-Through:</td><td>{'✅ Confirmed' if stats['follow_through_confirmed'] else '⏳ Waiting'}</td></tr>
            </table>
            """

        return html


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