"""
Profit Tracking System - Records and reports realized P&L
"""

from datetime import datetime


class ProfitTracker:
    """Tracks position entries and exits for P&L reporting"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions = {}  # {ticker: {'quantity': int, 'entry_price': float, ...}}
        self.closed_positions = []  # List of closed position dicts

    def record_position(self, ticker, quantity, entry_price, signal_type):
        """Record a new position or add to existing"""
        if ticker not in self.positions:
            self.positions[ticker] = {
                'quantity': quantity,
                'entry_price': entry_price,
                'signal_type': signal_type,
                'entry_date': datetime.now()
            }
        else:
            # Adding to existing position - calculate new average entry
            existing = self.positions[ticker]
            total_quantity = existing['quantity'] + quantity
            total_cost = (existing['quantity'] * existing['entry_price']) + (quantity * entry_price)
            new_avg_entry = total_cost / total_quantity

            self.positions[ticker] = {
                'quantity': total_quantity,
                'entry_price': new_avg_entry,
                'signal_type': signal_type,
                'entry_date': existing['entry_date']
            }

    def close_position(self, ticker, exit_price, exit_date, exit_signal):
        """Record position close and calculate realized P&L"""
        if ticker not in self.positions:
            return

        position = self.positions[ticker]

        # Calculate P&L
        pnl_per_share = exit_price - position['entry_price']
        total_pnl = pnl_per_share * position['quantity']
        pnl_pct = (pnl_per_share / position['entry_price'] * 100)

        # Record closed position
        closed_position = {
            'ticker': ticker,
            'quantity': position['quantity'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'pnl_dollars': total_pnl,
            'pnl_pct': pnl_pct,
            'entry_signal': position['signal_type'],
            'exit_signal': exit_signal.get('signal_type', 'unknown'),
            'entry_date': position['entry_date'],
            'exit_date': exit_date
        }

        self.closed_positions.append(closed_position)

        # Display immediate P&L
        emoji = "✅" if total_pnl > 0 else "❌"
        print(
            f"\n{emoji} CLOSED: {ticker} | ${total_pnl:+,.2f} ({pnl_pct:+.1f}%) | {position['quantity']} shares @ ${position['entry_price']:.2f} → ${exit_price:.2f}")

        # Remove from active positions
        del self.positions[ticker]

    def record_partial_exit(self, ticker, sell_quantity, exit_price, exit_date, exit_signal):
        """
        Record partial position exit (e.g., selling 75% at profit target)

        Args:
            ticker: Stock symbol
            sell_quantity: Number of shares sold
            exit_price: Exit price per share
            exit_date: Exit date
            exit_signal: Dict with signal info
        """
        if ticker not in self.positions:
            print(f"⚠️ WARNING: Attempted to record partial exit for {ticker} but no position found")
            return

        position = self.positions[ticker]

        # Calculate P&L for sold portion
        pnl_per_share = exit_price - position['entry_price']
        total_pnl = pnl_per_share * sell_quantity
        pnl_pct = (pnl_per_share / position['entry_price'] * 100)

        # Record as closed position
        closed_position = {
            'ticker': ticker,
            'quantity': sell_quantity,
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'pnl_dollars': total_pnl,
            'pnl_pct': pnl_pct,
            'entry_signal': position['signal_type'],
            'exit_signal': exit_signal.get('signal_type', exit_signal.get('msg', 'partial_exit')),
            'entry_date': position['entry_date'],
            'exit_date': exit_date,
            'partial': True  # Flag to indicate this was a partial exit
        }

        self.closed_positions.append(closed_position)

        # Display immediate P&L
        emoji = "✅" if total_pnl > 0 else "❌"
        remaining_qty = position['quantity'] - sell_quantity
        print(
            f"\n{emoji} PARTIAL EXIT: {ticker} | ${total_pnl:+,.2f} ({pnl_pct:+.1f}%) | Sold {sell_quantity}/{position['quantity']} shares @ ${exit_price:.2f} | Remaining: {remaining_qty}")

        # Update position (reduce quantity, keep entry price)
        self.positions[ticker]['quantity'] -= sell_quantity

        # If position is now zero, remove it
        if self.positions[ticker]['quantity'] <= 0:
            del self.positions[ticker]

    def display_final_summary(self):
        """Display comprehensive P&L summary at end of backtest"""
        if not self.closed_positions:
            print("\n📊 No closed positions to report")
            return

        # Calculate summary stats
        winners = [p for p in self.closed_positions if p['pnl_dollars'] > 0]
        losers = [p for p in self.closed_positions if p['pnl_dollars'] < 0]

        total_realized = sum(p['pnl_dollars'] for p in self.closed_positions)
        win_rate = (len(winners) / len(self.closed_positions) * 100) if self.closed_positions else 0

        avg_win = sum(p['pnl_dollars'] for p in winners) / len(winners) if winners else 0
        avg_loss = sum(p['pnl_dollars'] for p in losers) / len(losers) if losers else 0

        # Display summary
        print(f"\n{'=' * 80}")
        print(f"📊 FINAL P&L SUMMARY")
        print(f"{'=' * 80}\n")

        print(f"📈 CLOSED POSITIONS: {len(self.closed_positions)} trades")
        print(f"   Winners: {len(winners)} trades")
        print(f"   Losers:  {len(losers)} trades")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Total Realized P&L: ${total_realized:+,.2f}")
        print(f"   Avg Win: ${avg_win:,.2f}")
        print(f"   Avg Loss: ${avg_loss:,.2f}")

        # === NEW: SIGNAL PERFORMANCE BREAKDOWN ===
        self._display_signal_performance()

        # Display individual trades
        print(f"\n📋 Trade Details:")
        for p in self.closed_positions:
            print(
                f"   {p['ticker']:6} | ${p['pnl_dollars']:+9,.2f} ({p['pnl_pct']:+6.2f}%) | {p['entry_signal']:15} → {p['exit_signal']:15} ")

        # Display open positions
        if self.positions:
            print(f"\n📊 OPEN POSITIONS: {len(self.positions)}")
            total_unrealized = 0

            for ticker, pos in self.positions.items():
                try:
                    current_price = self.strategy.get_last_price(ticker)
                    unrealized_pnl = (current_price - pos['entry_price']) * pos['quantity']
                    unrealized_pct = ((current_price - pos['entry_price']) / pos['entry_price'] * 100)
                    total_unrealized += unrealized_pnl

                    print(
                        f"   {ticker:6} | {pos['quantity']} shares @ ${pos['entry_price']:7.2f} | Current: ${current_price:7.2f} | P&L: ${unrealized_pnl:+9,.2f} ({unrealized_pct:+6.2f}%)")
                except:
                    print(
                        f"   {ticker:6} | {pos['quantity']} shares @ ${pos['entry_price']:7.2f} | (price unavailable)")

            print(f"\n   Total Unrealized P&L: ${total_unrealized:+,.2f}")

        print(f"\n{'=' * 80}\n")

    def _display_signal_performance(self):
        """Display performance breakdown by entry signal type"""
        from collections import defaultdict

        # Group trades by entry signal
        signal_stats = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0
        })

        for pos in self.closed_positions:
            signal = pos['entry_signal']
            signal_stats[signal]['trades'].append(pos)
            signal_stats[signal]['total_pnl'] += pos['pnl_dollars']

            if pos['pnl_dollars'] > 0:
                signal_stats[signal]['wins'] += 1
            else:
                signal_stats[signal]['losses'] += 1

        # Display breakdown
        print(f"\n🎯 PERFORMANCE BY ENTRY SIGNAL:")
        print(f"{'─' * 80}")

        # Sort by total P&L (best performing first)
        sorted_signals = sorted(signal_stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

        for signal_name, stats in sorted_signals:
            total_trades = len(stats['trades'])
            win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0

            # Calculate average win and loss for this signal
            wins = [p['pnl_dollars'] for p in stats['trades'] if p['pnl_dollars'] > 0]
            losses = [p['pnl_dollars'] for p in stats['trades'] if p['pnl_dollars'] < 0]

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
