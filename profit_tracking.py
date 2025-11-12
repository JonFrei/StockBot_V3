"""
Profit Tracking System - SIMPLIFIED

Just logs closed trades for reporting.
Does NOT track positions (broker already does that).

Key Fix: Uses broker data for all P&L calculations - no accumulation bugs
"""

from datetime import datetime


class ProfitTracker:
    """
    Simplified tracker - just records closed trades
    No position tracking (broker handles that)
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.closed_trades = []  # List of completed trades

    def record_trade(self, ticker, quantity_sold, entry_price, exit_price,
                     exit_date, entry_signal, exit_signal):
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
            'exit_signal': exit_signal.get('reason', 'unknown'),
            'exit_date': exit_date
        }

        self.closed_trades.append(trade)

        # Display immediate feedback
        emoji = "✅" if total_pnl > 0 else "❌"
        print(
            f"\n{emoji} TRADE CLOSED: {ticker} | ${total_pnl:+,.2f} ({pnl_pct:+.1f}%) | {quantity_sold} shares @ ${entry_price:.2f} → ${exit_price:.2f}")

    def display_final_summary(self):
        """Display P&L summary at end of backtest"""
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

        # Display individual trades
        print(f"\n📋 Trade Details:")
        for t in self.closed_trades[-50:]:  # Show last 50 trades
            print(f"   {t['ticker']:6} | ${t['pnl_dollars']:+9,.2f} ({t['pnl_pct']:+6.2f}%) | "
                  f"{t['entry_signal']:15} → {t['exit_signal']:20}")

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