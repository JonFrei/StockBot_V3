"""
Profit Tracking System - SIMPLIFIED + ENHANCED

Just logs closed trades for reporting.
Does NOT track positions (broker already does that).

Key Fix: Uses broker data for all P&L calculations - no accumulation bugs

ENHANCED: Now includes per-ticker win/loss statistics and entry scores
"""

from datetime import datetime


class ProfitTracker:
    """
    Simplified tracker - just records closed trades
    No position tracking (broker handles that)

    ENHANCED: Now tracks per-ticker performance and entry scores
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.closed_trades = []  # List of completed trades

    def record_trade(self, ticker, quantity_sold, entry_price, exit_price,
                     exit_date, entry_signal, exit_signal, entry_score=0):
        """
        Record a completed trade (full or partial exit)

        Args:
            ticker: Stock symbol
            quantity_sold: Number of shares sold
            entry_price: Average entry price (from broker)
            exit_price: Exit price
            exit_date: Exit date
            entry_signal: Entry signal type
            exit_signal: Exit signal info dict
            entry_score: Entry signal strength score (0-100)
        """
        # Calculate P&L
        pnl_per_share = exit_price - entry_price
        total_pnl = pnl_per_share * quantity_sold
        pnl_pct = (pnl_per_share / entry_price * 100) if entry_price > 0 else 0

        # Record trade
        trade = {
            'ticker': ticker,
            'quantity': quantity_sold,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_dollars': total_pnl,
            'pnl_pct': pnl_pct,
            'entry_signal': entry_signal,
            'entry_score': entry_score,
            'exit_signal': exit_signal.get('reason', 'unknown'),
            'exit_date': exit_date
        }

        self.closed_trades.append(trade)

        # Display immediate feedback
        emoji = "✅" if total_pnl > 0 else "❌"
        print(
            f"\n{emoji} TRADE CLOSED: {ticker} | ${total_pnl:+,.2f} ({pnl_pct:+.1f}%) | {quantity_sold} shares @ ${entry_price:.2f} → ${exit_price:.2f}")

        # Update blacklist/rotation systems immediately
        self._notify_blacklist(ticker, total_pnl > 0, exit_date)

    def _notify_blacklist(self, ticker, is_winner, exit_date):
        """
        Inform the stock rotator's blacklist about the latest trade outcome so it can
        react in near real-time (e.g., consecutive loss tracking, P&L based bans).
        """
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

    def get_signal_stats(self, signal_name, lookback=None):
        """
        Return win/loss stats for a specific entry signal.

        Args:
            signal_name: Name of the entry signal
            lookback: Optional integer limiting analysis to most recent trades

        Returns:
            dict with trade_count, win_rate, avg_pnl, total_pnl
        """
        trades = [t for t in self.closed_trades if t['entry_signal'] == signal_name]
        if lookback is not None and lookback > 0:
            trades = trades[-lookback:]

        trade_count = len(trades)
        if trade_count == 0:
            return {
                'signal': signal_name,
                'trade_count': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0
            }

        wins = [t for t in trades if t['pnl_dollars'] > 0]
        total_pnl = sum(t['pnl_dollars'] for t in trades)
        avg_pnl = total_pnl / trade_count if trade_count else 0.0
        win_rate = (len(wins) / trade_count * 100) if trade_count else 0.0

        return {
            'signal': signal_name,
            'trade_count': trade_count,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': round(avg_pnl, 2)
        }

    def get_underperforming_signals(self, min_trades=6, win_rate_threshold=45.0, lookback=30):
        """
        Identify signals that are currently underperforming so the strategy can
        temporarily pause them.

        Args:
            min_trades: Minimum number of trades required before evaluation
            win_rate_threshold: Disable signals below this win rate (%)
            lookback: Evaluate only the most recent N trades per signal

        Returns:
            dict of {signal_name: stats_dict}
        """
        if not self.closed_trades:
            return {}

        signals = set(trade['entry_signal'] for trade in self.closed_trades)
        underperformers = {}

        for signal_name in signals:
            stats = self.get_signal_stats(signal_name, lookback=lookback)
            if stats['trade_count'] < min_trades:
                continue
            if stats['win_rate'] < win_rate_threshold:
                underperformers[signal_name] = stats

        return underperformers

    def display_final_summary(self):
        """Display P&L summary at end of backtest - ENHANCED with per-ticker stats and entry scores"""
        if not self.closed_trades:
            print("\n📊 No closed trades to report")
            return

        # Calculate summary stats
        winners = [t for t in self.closed_trades if t['pnl_dollars'] > 0]
        losers = [t for t in self.closed_trades if t['pnl_dollars'] < 0]

        total_realized = sum(t['pnl_dollars'] for t in self.closed_trades)
        win_rate = (len(winners) / len(self.closed_trades) * 100) if self.closed_trades else 0

        avg_win = sum(t['pnl_dollars'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl_dollars'] for t in losers) / len(losers) if losers else 0

        # Display summary
        print(f"\n{'=' * 80}")
        print(f"📊 FINAL P&L SUMMARY")
        print(f"{'=' * 80}\n")

        print(f"📈 CLOSED TRADES: {len(self.closed_trades)} trades")
        print(f"   Winners: {len(winners)} trades")
        print(f"   Losers:  {len(losers)} trades")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Total Realized P&L: ${total_realized:+,.2f}")
        print(f"   Avg Win: ${avg_win:,.2f}")
        print(f"   Avg Loss: ${avg_loss:,.2f}")

        # Signal performance breakdown
        self._display_signal_performance()

        # Per-ticker performance breakdown
        self._display_ticker_performance()

        # Display individual trades WITH ENTRY SCORES
        print(f"\n📋 Trade Details:")
        for t in self.closed_trades[-50:]:  # Show last 50 trades
            score_display = f"[{t.get('entry_score', 0):.0f}]"
            print(f"   {t['ticker']:6} | ${t['pnl_dollars']:+9,.2f} ({t['pnl_pct']:+6.2f}%) | "
                  f"{score_display:5} {t['entry_signal']:15} → {t['exit_signal']:20}")

        # Display open positions from broker
        self._display_open_positions()

        print(f"\n{'=' * 80}\n")

    def _display_signal_performance(self):
        """Display performance breakdown by entry signal"""
        from collections import defaultdict

        signal_stats = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0
        })

        for trade in self.closed_trades:
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

    def _display_ticker_performance(self):
        """
        Display performance breakdown by ticker
        Shows which stocks are performing best/worst
        """
        from collections import defaultdict

        ticker_stats = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'total_pnl_pct': 0.0
        })

        for trade in self.closed_trades:
            ticker = trade['ticker']
            ticker_stats[ticker]['trades'].append(trade)
            ticker_stats[ticker]['total_pnl'] += trade['pnl_dollars']
            ticker_stats[ticker]['total_pnl_pct'] += trade['pnl_pct']

            if trade['pnl_dollars'] > 0:
                ticker_stats[ticker]['wins'] += 1
            else:
                ticker_stats[ticker]['losses'] += 1

        print(f"\n💰 PERFORMANCE BY TICKER:")
        print(f"{'─' * 80}")

        # Sort by total P&L (highest first)
        sorted_tickers = sorted(ticker_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        print(f"{'Ticker':<8} {'Trades':<10} {'W/L':<10} {'Win Rate':<12} {'Total P&L':<15} {'Avg P&L':<15}")
        print(f"{'─' * 80}")

        for ticker, stats in sorted_tickers:
            total_trades = len(stats['trades'])
            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0
            avg_pnl_pct = stats['total_pnl_pct'] / total_trades if total_trades > 0 else 0

            w_l_str = f"{stats['wins']}W/{stats['losses']}L"

            print(f"{ticker:<8} {total_trades:<10} {w_l_str:<10} {win_rate:>6.1f}%      "
                  f"${stats['total_pnl']:>+10,.2f}   ${avg_pnl:>+8,.2f} ({avg_pnl_pct:>+5.1f}%)")

        print(f"{'─' * 80}")

        # Display best and worst performers
        if sorted_tickers:
            best = sorted_tickers[0]
            worst = sorted_tickers[-1]

            print(f"\n🏆 BEST PERFORMER: {best[0]} (${best[1]['total_pnl']:+,.2f} from {len(best[1]['trades'])} trades)")
            print(
                f"⚠️  WORST PERFORMER: {worst[0]} (${worst[1]['total_pnl']:+,.2f} from {len(worst[1]['trades'])} trades)")

    def _display_open_positions(self):
        """Display current open positions from broker"""
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
                entry_price = float(position.avg_fill_price)

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