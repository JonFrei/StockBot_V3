"""
Profit Tracking System - WITH ROTATION INTEGRATION, ADD-ON SUPPORT, AND METRICS

MODIFICATIONS:
- record_trade() now notifies stock_rotator of trade results
- This enables real-time tier updates based on actual performance
- DailySummary tracks add-ons separately from new entries
- NEW: update_end_of_day_metrics() updates daily_metrics and signal_performance tables
"""

from datetime import datetime
from collections import defaultdict
from database import get_database
from config import Config
from psycopg2.extras import RealDictCursor
import account_broker_data


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
        # self.recovery_profit_target = None
        self.recovery_entry_method = None
        # self.recovery_eligible_tiers = None
        # self.recovery_stop_multiplier = None
        self.exits = []
        self.entries = []
        self.addons = []
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
            self.recovery_mode_active = recovery_details.get('entry_method') is not None
            self.recovery_max_positions = recovery_details.get('max_positions')
            # self.recovery_profit_target = recovery_details.get('profit_target')
            self.recovery_entry_method = recovery_details.get('entry_method')
            # self.recovery_eligible_tiers = recovery_details.get('eligible_tiers')
            # self.recovery_stop_multiplier = recovery_details.get('stop_multiplier')

    def add_exit(self, ticker, qty, pnl, pnl_pct, reason):
        self.exits.append({'ticker': ticker, 'qty': qty, 'pnl': pnl, 'pnl_pct': pnl_pct, 'reason': reason})

    def add_entry(self, ticker, qty, price, cost, signal, score):
        self.entries.append(
            {'ticker': ticker, 'qty': qty, 'price': price, 'cost': cost, 'signal': signal, 'score': score})

    def add_addon(self, ticker, qty, price, cost, signal, score, existing_qty, new_total_exposure_pct):
        """Track add-on to existing position"""
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
                mode_type = "FULL" if self.recovery_entry_method == 'structure' else "CAUTIOUS"
                print(f"   🔓 RECOVERY MODE ACTIVE ({mode_type})")
                if self.recovery_max_positions:
                    print(f"      • Position Limit: {self.recovery_max_positions} positions")
                # if self.recovery_profit_target:
                #     print(f"      • Profit Target: {self.recovery_profit_target:.1f}%")
                # if self.recovery_eligible_tiers:
                #     print(f"      • Eligible Tiers: {', '.join(self.recovery_eligible_tiers)}")
                # if self.recovery_stop_multiplier and self.recovery_stop_multiplier != 1.0:
                #     print(f"      • Stop Multiplier: {self.recovery_stop_multiplier}x")
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

        # Show add-ons
        for ad in self.addons:
            print(
                f"   🔵 ADD: {ad['ticker']} +{ad['qty']} @ ${ad['price']:.2f} (${ad['cost']:,.0f}) | {ad['signal']} [{ad['score']}] | Now {ad['existing_qty'] + ad['qty']} shares ({ad['new_total_exposure_pct']:.1f}%)")

        if self.signals_found and not self.entries and not self.addons:
            tickers = [f"{s['ticker']}[{s['score']}]" for s in self.signals_found[:5]]
            print(f"   📊 Signals: {', '.join(tickers)}" + (" ..." if len(self.signals_found) > 5 else ""))

        for w in self.warnings[:3]:
            print(f"   ⚠️ {w}")
        for e in self.errors[:3]:
            print(f"   ❌ {e}")

        if not any([self.profit_takes, self.exits, self.entries, self.addons, self.tier_changes, self.warnings,
                    self.errors]):
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


# =============================================================================
# END OF DAY METRICS UPDATE
# =============================================================================

def update_end_of_day_metrics(strategy, current_date, regime_result=None):
    """
    Update daily_metrics and signal_performance tables at end of iteration.

    Called from account_strategies.py after successful iteration completion.

    Args:
        strategy: SwingTradeStrategy instance
        current_date: Current datetime
        regime_result: Result from regime detector (optional, for SPY/regime data)
    """
    try:
        _update_metrics_internal(strategy, current_date, regime_result)
    except Exception as e:
        print(f"[METRICS] Error updating end-of-day metrics: {e}")


def _update_metrics_internal(strategy, current_date, regime_result):
    """Internal implementation of metrics update"""

    db = get_database()

    # =================================================================
    # GATHER DAILY METRICS DATA
    # =================================================================

    # Portfolio basics
    portfolio_value = strategy.portfolio_value
    cash_balance = strategy.get_cash()
    positions = strategy.get_positions()
    num_positions = len(positions)

    # Calculate unrealized P&L from positions
    unrealized_pnl = 0
    for pos in positions:
        try:
            if hasattr(pos, 'unrealized_pl') and pos.unrealized_pl is not None:
                unrealized_pnl += float(pos.unrealized_pl)
        except:
            pass

    # Get closed trades for today and calculate realized P&L
    closed_trades = []
    if hasattr(strategy, 'profit_tracker'):
        closed_trades = strategy.profit_tracker.get_closed_trades() or []

    # Filter to today's trades
    today_date = current_date.date() if hasattr(current_date, 'date') else current_date
    today_trades = []
    for t in closed_trades:
        try:
            exit_date = t.get('exit_date')
            if exit_date:
                trade_date = exit_date.date() if hasattr(exit_date, 'date') else exit_date
                if trade_date == today_date:
                    today_trades.append(t)
        except:
            pass

    num_trades = len(today_trades)
    realized_pnl = sum(t.get('pnl_dollars', 0) for t in today_trades)

    # Calculate overall win rate from all closed trades
    win_rate = 0
    if closed_trades:
        winners = [t for t in closed_trades if t.get('pnl_dollars', 0) > 0]
        win_rate = (len(winners) / len(closed_trades)) * 100

    # Get SPY close and regime from regime_result
    spy_close = 0
    market_regime = 'unknown'
    if regime_result:
        # Try to get SPY close from details
        details = regime_result.get('details', {})
        spy_close = details.get('spy_close', 0) or regime_result.get('spy_close', 0)
        market_regime = regime_result.get('action', 'unknown')

    # =================================================================
    # SAVE DAILY METRICS
    # =================================================================

    try:
        db.save_daily_metrics(
            date=today_date,
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
    except Exception as e:
        print(f"[METRICS] Failed to save daily metrics: {e}")

# =============================================================================
# PROFIT TRACKER CLASS
# =============================================================================

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

    def record_trade(self, ticker, quantity_sold, entry_price, exit_price, exit_date,
                     entry_signal='unknown', exit_signal=None, entry_score=0):
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
                self.db.record_closed_trade(
                    ticker=ticker,
                    quantity=quantity_sold,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_dollars=total_pnl,
                    pnl_pct=pnl_pct,
                    entry_signal=entry_signal,
                    entry_score=entry_score,
                    exit_signal=exit_signal.get('reason', 'unknown') if isinstance(exit_signal, dict) else str(
                        exit_signal),
                    exit_date=exit_date
                )
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO closed_trades 
                    (ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct, 
                     entry_signal, entry_score, exit_signal, exit_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    ticker, quantity_sold, entry_price, exit_price, total_pnl, pnl_pct,
                    entry_signal, entry_score,
                    exit_signal.get('reason', 'unknown') if isinstance(exit_signal, dict) else str(exit_signal),
                    exit_date
                ))
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
            # cursor = conn.cursor()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            query = "SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct, entry_signal, entry_score, exit_signal, exit_date FROM closed_trades ORDER BY exit_date DESC"
            if limit:
                cursor.execute(query + " LIMIT %s", (limit,))
            else:
                cursor.execute(query)
            trades = []
            for row in cursor.fetchall():
                trades.append({
                    'ticker': row['ticker'],
                    'quantity': row['quantity'],
                    'entry_price': float(row['entry_price']),
                    'exit_price': float(row['exit_price']),
                    'pnl_dollars': float(row['pnl_dollars']),
                    'pnl_pct': float(row['pnl_pct']),
                    'entry_signal': row['entry_signal'],
                    'entry_score': row['entry_score'],
                    'exit_signal': row['exit_signal'],  # Map column to exit_signal key
                    'exit_date': row['exit_date']
                })
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

        account_broker_data.split_tracker.display_summary()

        print(f"{'=' * 100}\n")

    def _display_overall_performance(self, closed_trades):
        total_trades = len(closed_trades)
        winners = [t for t in closed_trades if t['pnl_dollars'] > 0]
        losers = [t for t in closed_trades if t['pnl_dollars'] < 0]
        total_realized = sum(t['pnl_dollars'] for t in closed_trades)
        win_rate = (len(winners) / total_trades * 100) if total_trades > 0 else 0

        gross_profit = sum(t['pnl_dollars'] for t in winners)
        gross_loss = abs(sum(t['pnl_dollars'] for t in losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        avg_win = (sum(t['pnl_dollars'] for t in winners) / len(winners)) if winners else 0
        avg_loss = (sum(t['pnl_dollars'] for t in losers) / len(losers)) if losers else 0
        avg_win_pct = (sum(t['pnl_pct'] for t in winners) / len(winners)) if winners else 0
        avg_loss_pct = (sum(t['pnl_pct'] for t in losers) / len(losers)) if losers else 0

        print(f"\n{'OVERALL PERFORMANCE':^100}")
        print(f"{'-' * 100}")
        print(f"{'Total Trades':<35} {total_trades:>25}")
        print(f"{'Winners':<35} {len(winners):>25}")
        print(f"{'Losers':<35} {len(losers):>25}")
        print(f"{'Win Rate':<35} {win_rate:>24.1f}%")
        print(f"{'Total Realized P&L':<35} ${total_realized:>24,.2f}")
        print(f"{'Profit Factor':<35} {profit_factor:>25.2f}")
        print(f"{'Avg Win':<35} ${avg_win:>24,.2f} ({avg_win_pct:+.1f}%)")
        print(f"{'Avg Loss':<35} ${avg_loss:>24,.2f} ({avg_loss_pct:+.1f}%)")

    def _display_signal_summary(self, closed_trades):
        signal_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0, 'pnl_pct_sum': 0})
        for t in closed_trades:
            signal = t['entry_signal']
            signal_stats[signal]['trades'] += 1
            signal_stats[signal]['pnl'] += t['pnl_dollars']
            signal_stats[signal]['pnl_pct_sum'] += t['pnl_pct']
            if t['pnl_dollars'] > 0:
                signal_stats[signal]['wins'] += 1

        print(f"\n{'SIGNAL PERFORMANCE':^100}")
        print(f"{'-' * 100}")
        print(f"{'Signal':<25} {'Trades':>10} {'Wins':>10} {'Win%':>10} {'Total P&L':>20} {'Avg P&L%':>15}")
        print(f"{'-' * 100}")

        for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
            win_rate = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
            avg_pnl_pct = stats['pnl_pct_sum'] / stats['trades'] if stats['trades'] > 0 else 0
            print(
                f"{signal:<25} {stats['trades']:>10} {stats['wins']:>10} {win_rate:>9.1f}% ${stats['pnl']:>19,.2f} {avg_pnl_pct:>14.1f}%")

    def _display_exit_breakdown(self, closed_trades):
        exit_stats = defaultdict(lambda: {'count': 0, 'pnl': 0})
        for t in closed_trades:
            exit_signal = t['exit_signal']
            exit_stats[exit_signal]['count'] += 1
            exit_stats[exit_signal]['pnl'] += t['pnl_dollars']

        print(f"\n{'EXIT BREAKDOWN':^100}")
        print(f"{'-' * 100}")
        print(f"{'Exit Reason':<40} {'Count':>15} {'Total P&L':>20} {'Avg P&L':>15}")
        print(f"{'-' * 100}")

        for reason, stats in sorted(exit_stats.items(), key=lambda x: x[1]['count'], reverse=True):
            avg_pnl = stats['pnl'] / stats['count'] if stats['count'] > 0 else 0
            print(f"{reason:<40} {stats['count']:>15} ${stats['pnl']:>19,.2f} ${avg_pnl:>14,.2f}")

    def _display_ticker_summary(self, closed_trades, stock_rotator=None):
        ticker_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0})
        for t in closed_trades:
            ticker = t['ticker']
            ticker_stats[ticker]['trades'] += 1
            ticker_stats[ticker]['pnl'] += t['pnl_dollars']
            if t['pnl_dollars'] > 0:
                ticker_stats[ticker]['wins'] += 1

        print(f"\n{'TOP/BOTTOM TICKERS':^100}")
        print(f"{'-' * 100}")

        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)

        print("TOP 5:")
        for ticker, stats in sorted_tickers[:5]:
            win_rate = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
            tier = stock_rotator.get_tier(ticker) if stock_rotator else 'N/A'
            print(
                f"   {ticker:<10} {stats['trades']:>3} trades | {win_rate:>5.1f}% WR | ${stats['pnl']:>10,.2f} | Tier: {tier}")

        print("\nBOTTOM 5:")
        for ticker, stats in sorted_tickers[-5:]:
            win_rate = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
            tier = stock_rotator.get_tier(ticker) if stock_rotator else 'N/A'
            print(
                f"   {ticker:<10} {stats['trades']:>3} trades | {win_rate:>5.1f}% WR | ${stats['pnl']:>10,.2f} | Tier: {tier}")

    def _display_last_100_trades(self, closed_trades):
        last_40 = closed_trades[:40]
        if len(last_40) < 5:
            return

        # Summary stats
        winners = [t for t in last_40 if t['pnl_dollars'] > 0]
        total_pnl = sum(t['pnl_dollars'] for t in last_40)
        win_rate = (len(winners) / len(last_40) * 100)

        print(f"\n{'LAST 40 TRADES':^100}")
        print(f"{'-' * 100}")
        print(
            f"{'Trades':<20} {len(last_40):>10} | {'Win Rate':<15} {win_rate:>6.1f}% | {'Total P&L':<15} ${total_pnl:>12,.2f}")
        print(f"{'-' * 100}")
        print(f"{'Ticker':<10} {' | Entry Signal':<20} {'Entry':>12} {' | Exit Signal':<20} {'Exit':>12} {' | P&L %':>12}")
        print(f"{'-' * 100}")

        for trade in reversed(last_40):
            ticker = trade['ticker']
            entry_signal = trade.get('entry_signal', 'unknown')[:18]
            exit_signal = trade.get('exit_signal', 'unknown')[:18]
            entry_price = trade['entry_price']
            exit_price = trade['exit_price']
            pnl_pct = trade['pnl_pct']

            pnl_str = f"{pnl_pct:>+.1f}%"
            print(
                f"{ticker:<10} | {entry_signal:<20} ${entry_price:>10,.2f} | {exit_signal:<20} ${exit_price:>10,.2f} | {pnl_str:>12}")

    def _display_rotation_summary(self, stock_rotator):
        if not stock_rotator:
            return

        stats = stock_rotator.get_statistics()
        dist = stats['tier_distribution']

        print(f"\n{'ROTATION SUMMARY':^100}")
        print(f"{'-' * 100}")
        print(f"{'Rotation Count':<35} {stats['rotation_count']:>25}")
        print(f"{'🥇 Premium':<35} {dist.get('premium', 0):>25}")
        print(f"{'🥈 Active':<35} {dist.get('active', 0):>25}")
        print(f"{'⚠️ Probation':<35} {dist.get('probation', 0):>25}")
        print(f"{'🔄 Rehabilitation':<35} {dist.get('rehabilitation', 0):>25}")
        print(f"{'❄️ Frozen':<35} {dist.get('frozen', 0):>25}")

        if stats['premium_stocks']:
            print(f"\nPremium Stocks: {', '.join(stats['premium_stocks'][:10])}")
        if stats['frozen_stocks']:
            print(f"Frozen Stocks: {', '.join(stats['frozen_stocks'][:10])}")

    def _display_safeguard_summary(self, regime_detector):
        if not regime_detector:
            return

        stats = regime_detector.get_statistics()

        print(f"\n{'SAFEGUARD SUMMARY':^100}")
        print(f"{'-' * 100}")
        print(f"{'Crisis Active':<35} {str(stats.get('crisis_active', False)):>25}")
        print(f"{'Portfolio Drawdown Active':<35} {str(stats.get('portfolio_drawdown_active', False)):>25}")

        if stats.get('crisis_trigger_reason'):
            print(f"{'Crisis Reason':<35} {stats['crisis_trigger_reason']:>25}")

    def _display_recovery_mode_summary(self, recovery_manager):
        if not recovery_manager:
            return

        stats = recovery_manager.get_statistics()
        print(f"\n{'RECOVERY MODE SUMMARY':^100}")
        print(f"{'-' * 100}")
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

        # Stock split summary HTML
        split_html = ""
        if account_broker_data.split_tracker.has_splits():
            splits = account_broker_data.split_tracker.get_splits()
            split_html = f"""
            <h3>🔄 Stock Splits ({len(splits)})</h3>
            <table>
            """
            for split in splits:
                conf_emoji = '✅' if split['confidence'] == 'high' else '⚠️'
                split_html += f"""
                <tr>
                    <td>{split['ticker']}</td>
                    <td>{split['split_type']} {split['display_ratio']}</td>
                    <td>${split['old_entry']:.2f} → ${split['new_entry']:.2f}</td>
                    <td>{conf_emoji}</td>
                </tr>
                """
            split_html += "</table>"

        return f"""
        <h3>📈 Performance Summary</h3>
        <table>
            <tr><td>Total Trades:</td><td>{total_trades}</td></tr>
            <tr><td>Win Rate:</td><td>{win_rate:.1f}%</td></tr>
            <tr><td>Total P&L:</td><td style="color:{pnl_color};font-weight:bold;">${total_realized:+,.2f}</td></tr>
            <tr><td>Recovery Mode Activations:</td><td>{recovery_count}</td></tr>
        </table>
        {split_html}
        <h3>🏆 Tier Distribution</h3>
        <table>
            {tier_html}
        </table>
        """

