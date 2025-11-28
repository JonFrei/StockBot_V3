"""
Profit Tracking System - WITH ROTATION INTEGRATION AND ADD-ON SUPPORT

MODIFICATIONS:
- record_trade() now notifies stock_rotator of trade results
- This enables real-time tier updates based on actual performance
- NEW: DailySummary now tracks add-ons separately from new entries
- NEW: OrderLogger supports is_addon flag
"""

from datetime import datetime
from database import get_database
from config import Config


class DailySummary:
    def __init__(self):
        self.reset()

    def reset(self):
        self.date = None
        self.portfolio_value = 0
        self.cash_balance = 0
        self.regime_status = None
        self.regime_reason = None
        self.regime_multiplier = 1.0
        self.recovery_mode_active = False
        self.recovery_max_positions = None
        self.recovery_profit_target = None
        self.recovery_signals = None
        self.exits = []
        self.entries = []
        self.addons = []  # NEW: Track add-ons separately
        self.profit_takes = []
        self.signals_found = []
        self.signals_skipped = []
        self.tier_changes = []
        self.warnings = []
        self.errors = []

    def set_context(self, date, portfolio_value, cash_balance):
        self.date = date
        self.portfolio_value = portfolio_value
        self.cash_balance = cash_balance

    def set_regime(self, status, reason, multiplier, recovery_details=None):
        self.regime_status = status
        self.regime_reason = reason
        self.regime_multiplier = multiplier

        if recovery_details:
            self.recovery_mode_active = recovery_details.get('active', False)
            self.recovery_max_positions = recovery_details.get('max_positions')
            self.recovery_profit_target = recovery_details.get('profit_target')
            self.recovery_signals = recovery_details.get('signals')

    def add_exit(self, ticker, qty, pnl, pnl_pct, reason):
        self.exits.append({'ticker': ticker, 'qty': qty, 'pnl': pnl, 'pnl_pct': pnl_pct, 'reason': reason})

    def add_entry(self, ticker, qty, price, cost, signal, score):
        self.entries.append(
            {'ticker': ticker, 'qty': qty, 'price': price, 'cost': cost, 'signal': signal, 'score': score})

    def add_addon(self, ticker, qty, price, cost, signal, score, existing_qty, new_total_exposure_pct):
        """NEW: Track add-on to existing position"""
        self.addons.append({
            'ticker': ticker,
            'qty': qty,
            'price': price,
            'cost': cost,
            'signal': signal,
            'score': score,
            'existing_qty': existing_qty,
            'new_total_exposure_pct': new_total_exposure_pct
        })

    def add_profit_take(self, ticker, level, qty, pnl, pnl_pct):
        self.profit_takes.append({'ticker': ticker, 'level': level, 'qty': qty, 'pnl': pnl, 'pnl_pct': pnl_pct})

    def add_signal(self, ticker, signal, score):
        self.signals_found.append({'ticker': ticker, 'signal': signal, 'score': score})

    def add_skip(self, ticker, reason):
        self.signals_skipped.append({'ticker': ticker, 'reason': reason})

    def add_tier_change(self, ticker, old_tier, new_tier, reason):
        """Track tier changes"""
        self.tier_changes.append({
            'ticker': ticker,
            'old_tier': old_tier,
            'new_tier': new_tier,
            'reason': reason
        })

    def add_warning(self, msg):
        self.warnings.append(msg)

    def add_error(self, msg):
        self.errors.append(msg)

    def print_summary(self):
        date_str = self.date.strftime('%Y-%m-%d') if self.date else 'Unknown'
        print(f"\n{'═' * 80}")
        print(f"📅 {date_str} | Portfolio: ${self.portfolio_value:,.0f} | Cash: ${self.cash_balance:,.0f}")

        if self.regime_status:
            regime_icon = {'normal': '✅', 'caution': '⚠️', 'stop_buying': '🚫', 'exit_all': '🚨',
                           'recovery_mode': '🔓'}.get(self.regime_status, '❓')
            print(
                f"   {regime_icon} Regime: {self.regime_status.upper()} ({self.regime_multiplier:.0%}) - {self.regime_reason}")

            if self.recovery_mode_active or self.regime_status == 'recovery_mode':
                print(f"   {'─' * 76}")
                print(f"   🔓 RECOVERY MODE ACTIVE")
                if self.recovery_max_positions:
                    print(f"      • Position Limit: {self.recovery_max_positions} positions")
                if self.recovery_profit_target:
                    print(f"      • Profit Target: {self.recovery_profit_target:.1f}%")
                print(f"   {'─' * 76}")

        # Show tier changes
        for tc in self.tier_changes:
            emoji_map = {'premium': '🥇', 'active': '🥈', 'probation': '⚠️', 'rehabilitation': '🔄', 'frozen': '❄️'}
            old_emoji = emoji_map.get(tc['old_tier'], '❓')
            new_emoji = emoji_map.get(tc['new_tier'], '❓')
            print(f"   {old_emoji}→{new_emoji} TIER: {tc['ticker']} {tc['old_tier']} → {tc['new_tier']}")

        for pt in self.profit_takes:
            print(
                f"   💰 PROFIT L{pt['level']}: {pt['ticker']} x{pt['qty']} | ${pt['pnl']:+,.2f} ({pt['pnl_pct']:+.1f}%)")

        for ex in self.exits:
            emoji = '✅' if ex['pnl'] > 0 else '❌'
            print(
                f"   {emoji} EXIT: {ex['ticker']} x{ex['qty']} | ${ex['pnl']:+,.2f} ({ex['pnl_pct']:+.1f}%) - {ex['reason']}")

        # Show new entries
        for en in self.entries:
            print(
                f"   🟢 BUY: {en['ticker']} x{en['qty']} @ ${en['price']:.2f} (${en['cost']:,.0f}) | {en['signal']} [{en['score']}]")

        # NEW: Show add-ons
        for ad in self.addons:
            print(
                f"   🔵 ADD: {ad['ticker']} +{ad['qty']} @ ${ad['price']:.2f} (${ad['cost']:,.0f}) | {ad['signal']} [{ad['score']}] | Now {ad['existing_qty']+ad['qty']} shares ({ad['new_total_exposure_pct']:.1f}%)")

        if self.signals_found and not self.entries and not self.addons:
            tickers = [f"{s['ticker']}[{s['score']}]" for s in self.signals_found[:5]]
            print(f"   📊 Signals: {', '.join(tickers)}" + (" ..." if len(self.signals_found) > 5 else ""))

        for w in self.warnings[:3]:
            print(f"   ⚠️ {w}")
        for e in self.errors[:3]:
            print(f"   ❌ {e}")

        if not any([self.profit_takes, self.exits, self.entries, self.addons, self.tier_changes, self.warnings, self.errors]):
            if self.regime_status not in ['stop_buying', 'exit_all', 'recovery_mode']:
                print(f"   (No activity)")
            elif self.regime_status == 'recovery_mode':
                print(f"   (Recovery mode active - waiting for qualified signals)")

        print(f"{'═' * 80}")


_summary = None


def get_summary():
    global _summary
    if _summary is None:
        _summary = DailySummary()
    return _summary


def reset_summary():
    global _summary
    if _summary:
        _summary.reset()
    else:
        _summary = DailySummary()
    return _summary


class ProfitTracker:
    def __init__(self, strategy, stock_rotator=None):
        """
        Initialize profit tracker

        Args:
            strategy: Lumibot Strategy instance
            stock_rotator: StockRotator instance (optional, for real-time tier updates)
        """
        self.strategy = strategy
        self.db = get_database()
        self.stock_rotator = stock_rotator

    def set_stock_rotator(self, stock_rotator):
        """Set stock rotator reference (can be set after initialization)"""
        self.stock_rotator = stock_rotator

    def record_trade(self, ticker, quantity_sold, entry_price, exit_price, exit_date, entry_signal, exit_signal,
                     entry_score=0):
        """
        Record a closed trade and notify rotation system

        Returns:
            dict: Trade record with tier change info if applicable
        """
        pnl_per_share = exit_price - entry_price
        total_pnl = pnl_per_share * quantity_sold
        pnl_pct = (pnl_per_share / entry_price * 100) if entry_price > 0 else 0

        # Save to database
        conn = self.db.get_connection()
        try:
            if Config.BACKTESTING:
                self.db.insert_trade(ticker=ticker, quantity=quantity_sold, entry_price=entry_price,
                                     exit_price=exit_price, pnl_dollars=total_pnl, pnl_pct=pnl_pct,
                                     entry_signal=entry_signal,
                                     entry_score=entry_score, exit_signal=exit_signal.get('reason', 'unknown'),
                                     exit_date=exit_date)
            else:
                cursor = conn.cursor()
                cursor.execute("""INSERT INTO closed_trades (ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date, was_watchlisted, confirmation_date, days_to_confirmation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                               (ticker, quantity_sold, entry_price, exit_price, total_pnl, pnl_pct, entry_signal,
                                entry_score,
                                exit_signal.get('reason', 'unknown'), exit_date, False, None, 0))
                conn.commit()
                cursor.close()
        except Exception as e:
            if not Config.BACKTESTING:
                conn.rollback()
            raise
        finally:
            self.db.return_connection(conn)

        # Notify rotation system of trade result
        tier_change = None
        if self.stock_rotator:
            tier_change = self.stock_rotator.record_trade_result(ticker, total_pnl, exit_date)

        return {
            'ticker': ticker,
            'pnl_dollars': total_pnl,
            'pnl_pct': pnl_pct,
            'tier_change': tier_change
        }

    def get_closed_trades(self, limit=None):
        if Config.BACKTESTING:
            return self.db.get_closed_trades(limit)
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct, entry_signal, entry_score, exit_signal, exit_date FROM closed_trades ORDER BY exit_date DESC"
            if limit:
                cursor.execute(query + " LIMIT %s", (limit,))
            else:
                cursor.execute(query)
            trades = []
            for row in cursor.fetchall():
                trades.append(
                    {'ticker': row[0], 'quantity': row[1], 'entry_price': float(row[2]), 'exit_price': float(row[3]),
                     'pnl_dollars': float(row[4]), 'pnl_pct': float(row[5]), 'entry_signal': row[6],
                     'entry_score': row[7],
                     'exit_signal': row[8], 'exit_date': row[9]})
            return trades
        finally:
            cursor.close()
            self.db.return_connection(conn)

    def display_final_summary(self, stock_rotator=None, regime_detector=None, recovery_manager=None):
        closed_trades = self.get_closed_trades()
        if not closed_trades:
            print("\n📊 No closed trades")
            return

        print(f"\n{'=' * 100}")
        print(f"{'📊 FINAL TRADING SUMMARY':^100}")
        print(f"{'=' * 100}")

        self._display_overall_performance(closed_trades)
        self._display_signal_summary(closed_trades)
        self._display_exit_breakdown(closed_trades)
        self._display_ticker_summary(closed_trades, stock_rotator)
        self._display_last_100_trades(closed_trades)
        self._display_rotation_summary(stock_rotator)
        self._display_safeguard_summary(regime_detector)
        self._display_recovery_mode_summary(recovery_manager)

        print(f"{'=' * 100}\n")

    def _display_overall_performance(self, closed_trades):
        from collections import defaultdict
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

        print(f"\n{'─' * 100}")
        print(f"📈 OVERALL PERFORMANCE")
        print(f"{'─' * 100}")
        print(f"{'Total Trades':<25} {total_trades:>20}")
        print(f"{'Win Rate':<25} {f'{win_rate:.1f}% ({len(winners)}/{total_trades})':>20}")
        print(f"{'Avg Win':<25} {f'${avg_win:,.2f}':>20}")
        print(f"{'Avg Loss':<25} {f'${avg_loss:,.2f}':>20}")
        print(f"{'Total Realized P&L':<25} {f'${total_realized:+,.2f}':>20}")
        print(f"{'Profit Factor':<25} {f'{profit_factor:.2f}':>20}")

    def _display_signal_summary(self, closed_trades):
        from collections import defaultdict
        signal_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0})
        for trade in closed_trades:
            signal = trade['entry_signal']
            pnl = trade['pnl_dollars']
            signal_stats[signal]['trades'] += 1
            signal_stats[signal]['total_pnl'] += pnl
            if pnl > 0:
                signal_stats[signal]['wins'] += 1
                signal_stats[signal]['win_pnl'] += pnl
            elif pnl < 0:
                signal_stats[signal]['loss_pnl'] += pnl

        print(f"\n{'─' * 100}")
        print(f"📊 PERFORMANCE BY SIGNAL")
        print(f"{'─' * 100}")
        print(f"{'Signal':<25} {'Trades':>7} {'WR%':>8} {'Avg Win':>12} {'Avg Loss':>12} {'Total P&L':>14}")
        print(f"{'─' * 100}")

        for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True):
            trades = stats['trades']
            wins = stats['wins']
            losses = trades - wins
            wr = (wins / trades * 100) if trades > 0 else 0
            avg_win = (stats['win_pnl'] / wins) if wins > 0 else 0
            avg_loss = (stats['loss_pnl'] / losses) if losses > 0 else 0
            print(
                f"{signal[:25]:<25} {trades:>7} {wr:>7.1f}% {f'${avg_win:,.2f}':>12} {f'${avg_loss:,.2f}':>12} {f'${stats['total_pnl']:+,.2f}':>14}")

    def _display_exit_breakdown(self, closed_trades):
        from collections import defaultdict
        exit_stats = defaultdict(lambda: {'count': 0, 'wins': 0, 'total_pnl': 0.0})
        for trade in closed_trades:
            exit_type = trade.get('exit_signal', 'unknown')
            pnl = trade['pnl_dollars']
            exit_stats[exit_type]['count'] += 1
            exit_stats[exit_type]['total_pnl'] += pnl
            if pnl > 0:
                exit_stats[exit_type]['wins'] += 1

        total_trades = len(closed_trades)
        print(f"\n{'─' * 100}")
        print(f"🚪 EXIT BREAKDOWN")
        print(f"{'─' * 100}")
        print(f"{'Exit Type':<30} {'Count':>7} {'Freq%':>7} {'WR%':>8} {'Total P&L':>14}")
        print(f"{'─' * 100}")

        for exit_type, stats in sorted(exit_stats.items(), key=lambda x: x[1]['count'], reverse=True):
            count = stats['count']
            freq_pct = (count / total_trades * 100) if total_trades > 0 else 0
            wr = (stats['wins'] / count * 100) if count > 0 else 0
            print(f"{exit_type[:30]:<30} {count:>7} {freq_pct:>6.1f}% {wr:>7.1f}% {f'${stats['total_pnl']:+,.2f}':>14}")

    def _display_ticker_summary(self, closed_trades, stock_rotator=None):
        from collections import defaultdict
        ticker_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0})
        for trade in closed_trades:
            ticker = trade['ticker']
            pnl = trade['pnl_dollars']
            ticker_stats[ticker]['trades'] += 1
            ticker_stats[ticker]['total_pnl'] += pnl
            if pnl > 0:
                ticker_stats[ticker]['wins'] += 1

        print(f"\n{'─' * 100}")
        print(f"📊 PERFORMANCE BY TICKER")
        print(f"{'─' * 100}")
        print(f"{'Ticker':<8} {'Tier':<12} {'Trades':>7} {'WR%':>8} {'Total P&L':>14}")
        print(f"{'─' * 100}")

        for ticker, stats in sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True):
            trades = stats['trades']
            wr = (stats['wins'] / trades * 100) if trades > 0 else 0
            tier = stock_rotator.get_tier(ticker) if stock_rotator else 'active'
            tier_icon = {'premium': '🥇', 'active': '🥈', 'probation': '⚠️', 'rehabilitation': '🔄', 'frozen': '❄️'}.get(tier, '🥈')
            print(f"{ticker:<8} {tier_icon}{tier[:10]:<11} {trades:>7} {wr:>7.1f}% {f'${stats['total_pnl']:+,.2f}':>14}")

    def _display_last_100_trades(self, closed_trades):
        print(f"\n{'─' * 100}")
        print(f"📜 LAST 100 TRADES")
        print(f"{'─' * 100}")
        print(f"{'#':<4} {'Ticker':<8} {'P&L $':>12} {'P&L %':>8} {'Signal':<25} {'Exit':<25}")
        print(f"{'─' * 100}")

        for i, trade in enumerate(closed_trades[:100], 1):
            pnl = trade['pnl_dollars']
            emoji = '✅' if pnl > 0 else '❌' if pnl < 0 else '➖'
            print(
                f"{i:<4} {emoji}{trade['ticker']:<7} {f'${pnl:+,.2f}':>12} {f'{trade['pnl_pct']:+.1f}%':>8} {trade['entry_signal'][:25]:<25} {trade.get('exit_signal', 'unknown')[:25]:<25}")

    def _display_rotation_summary(self, stock_rotator):
        print(f"\n{'─' * 100}")
        print(f"🏆 STOCK ROTATION SUMMARY")
        print(f"{'─' * 100}")
        if not stock_rotator:
            print("   Not available")
            return
        stats = stock_rotator.get_statistics()
        dist = stats['tier_distribution']
        print(f"{'Total Evaluations':<30} {stats['rotation_count']:>20}")
        print(f"   🥇 Premium: {dist.get('premium', 0)} | "
              f"🥈 Active: {dist.get('active', 0)} | "
              f"⚠️ Probation: {dist.get('probation', 0)} | "
              f"🔄 Rehab: {dist.get('rehabilitation', 0)} | "
              f"❄️ Frozen: {dist.get('frozen', 0)}")

        if stats.get('premium_stocks'):
            print(f"   Premium: {', '.join(stats['premium_stocks'])}")
        if stats.get('frozen_stocks'):
            print(f"   Frozen: {', '.join(stats['frozen_stocks'])}")

    def _display_safeguard_summary(self, regime_detector):
        print(f"\n{'─' * 100}")
        print(f"🛡️ MARKET SAFEGUARD SUMMARY")
        print(f"{'─' * 100}")
        if not regime_detector:
            print("   Not available")
            return
        stats = regime_detector.get_statistics()
        print(
            f"   Distribution: {stats['distribution_days']} | Accumulation: {stats['accumulation_days']} | Net: {stats['net_distribution']}")

    def _display_recovery_mode_summary(self, recovery_manager):
        print(f"\n{'─' * 100}")
        print(f"🔓 RECOVERY MODE SUMMARY")
        print(f"{'─' * 100}")
        if not recovery_manager:
            print("   Not available")
            return
        stats = recovery_manager.get_statistics()
        print(f"{'Times Activated':<35} {stats.get('activation_count', 0):>25}")

    def generate_final_summary_html(self, stock_rotator=None, regime_detector=None, recovery_manager=None):
        closed_trades = self.get_closed_trades()
        if not closed_trades:
            return "<p>No closed trades</p>"

        total_trades = len(closed_trades)
        winners = [t for t in closed_trades if t['pnl_dollars'] > 0]
        total_realized = sum(t['pnl_dollars'] for t in closed_trades)
        win_rate = (len(winners) / total_trades * 100) if total_trades > 0 else 0
        pnl_color = '#27ae60' if total_realized > 0 else '#e74c3c'

        recovery_count = recovery_manager.get_statistics().get('activation_count', 0) if recovery_manager else 0

        # Tier distribution
        tier_html = ""
        if stock_rotator:
            stats = stock_rotator.get_statistics()
            dist = stats['tier_distribution']
            tier_html = f"""
            <tr><td>🥇 Premium:</td><td>{dist.get('premium', 0)}</td></tr>
            <tr><td>🥈 Active:</td><td>{dist.get('active', 0)}</td></tr>
            <tr><td>⚠️ Probation:</td><td>{dist.get('probation', 0)}</td></tr>
            <tr><td>🔄 Rehabilitation:</td><td>{dist.get('rehabilitation', 0)}</td></tr>
            <tr><td>❄️ Frozen:</td><td>{dist.get('frozen', 0)}</td></tr>
            """

        return f"""
        <h3>📈 Performance Summary</h3>
        <table>
            <tr><td>Total Trades:</td><td>{total_trades}</td></tr>
            <tr><td>Win Rate:</td><td>{win_rate:.1f}%</td></tr>
            <tr><td>Total P&L:</td><td style="color:{pnl_color};font-weight:bold;">${total_realized:+,.2f}</td></tr>
            <tr><td>Recovery Mode Activations:</td><td>{recovery_count}</td></tr>
        </table>
        <h3>🏆 Tier Distribution</h3>
        <table>
            {tier_html}
        </table>
        """


class OrderLogger:
    def __init__(self, strategy):
        self.strategy = strategy
        self.db = get_database()

    def log_order(self, ticker, side, quantity, signal_type='unknown', award='none', quality_score=0, limit_price=None,
                  was_watchlisted=False, days_on_watchlist=0, is_addon=False):
        """
        Log an order with add-on tracking

        Args:
            ticker: Stock symbol
            side: 'buy' or 'sell'
            quantity: Number of shares
            signal_type: Entry signal name
            award: Tier level
            quality_score: Signal score
            limit_price: Limit price if applicable
            was_watchlisted: Whether came from watchlist
            days_on_watchlist: Days on watchlist before entry
            is_addon: True if this is an add to existing position (NEW)
        """
        try:
            filled_price = self.strategy.get_last_price(ticker) if limit_price is None else limit_price
            portfolio_value = self.strategy.portfolio_value
            cash_before = self.strategy.get_cash()
            submitted_at = self.strategy.get_datetime()

            # NEW: Modify signal_type to indicate add-on
            if is_addon:
                signal_type = f"addon_{signal_type}"

            if Config.BACKTESTING:
                self.db.insert_order_log(ticker=ticker, side=side, quantity=quantity, order_type='market',
                                         limit_price=limit_price, filled_price=filled_price, submitted_at=submitted_at,
                                         signal_type=signal_type, portfolio_value=portfolio_value,
                                         cash_before=cash_before,
                                         award=award, quality_score=quality_score, broker_order_id=None,
                                         was_watchlisted=was_watchlisted, days_on_watchlist=days_on_watchlist)
            else:
                conn = self.db.get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""INSERT INTO order_log (ticker, side, quantity, order_type, limit_price, filled_price,
                         submitted_at, signal_type, portfolio_value, cash_before, award, quality_score, was_watchlisted, days_on_watchlist)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                   (ticker, side, quantity, 'market', limit_price, filled_price, submitted_at,
                                    signal_type,
                                    portfolio_value, cash_before, award, quality_score, was_watchlisted,
                                    days_on_watchlist))
                    conn.commit()
                finally:
                    cursor.close()
                    self.db.return_connection(conn)
        except:
            pass