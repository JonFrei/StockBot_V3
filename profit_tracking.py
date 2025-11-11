# profit_tracking.py - New file for profit tracking functionality

class ProfitTracker:
    """Handles position tracking and P&L calculations"""

    def __init__(self, strategy):
        """
        Initialize profit tracker

        Args:
            strategy: Reference to the Strategy object for accessing methods like get_datetime()
        """
        self.strategy = strategy
        self.positions = {}
        self.closed_positions = []

    def record_position(self, ticker, quantity, entry_price, signal_type):
        """Record a new position when buying"""
        self.positions[ticker] = {
            'quantity': quantity,
            'entry_price': entry_price,
            'entry_date': self.strategy.get_datetime(),
            'signal': signal_type
        }

    def close_position(self, ticker, exit_price, exit_date, sell_signal):
        """Close a position and display realized P&L"""
        position = self.positions[ticker]
        entry_price = position['entry_price']
        quantity = position['quantity']

        # Calculate realized P&L
        pnl = (exit_price - entry_price) * quantity
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        # Display realized P&L
        print(f"\n{'=' * 60}")
        print(f"💰 REALIZED P&L - {ticker}")
        print(f"{'=' * 60}")
        print(f"Entry:  ${entry_price:.2f} x {quantity} shares")
        print(f"Exit:   ${exit_price:.2f} x {quantity} shares")
        print(f"P&L:    ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
        print(f"{'=' * 60}\n")

        # Record closed position
        self.closed_positions.append({
            'ticker': ticker,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'quantity': quantity,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'entry_date': position['entry_date'],
            'exit_date': exit_date,
            'entry_signal': position['signal'],
            'exit_signal': sell_signal.get('signal_type', 'unknown')
        })

        # Remove from open positions
        del self.positions[ticker]

    def has_position(self, ticker):
        """Check if we have an open position for ticker"""
        return ticker in self.positions

    def get_position_quantity(self, ticker):
        """Get quantity for an open position"""
        return self.positions.get(ticker, {}).get('quantity', 0)

    def display_final_summary(self):
        """Display comprehensive P&L summary at end of strategy"""
        print("\n" + "=" * 80)
        print("📊 FINAL P&L SUMMARY")
        print("=" * 80)

        # Display closed positions summary
        self._display_closed_positions_summary()

        # Display signal-specific performance
        self._display_signal_performance()

        # Display open positions with unrealized P&L
        self._display_open_positions_summary()

        print("\n" + "=" * 80 + "\n")

    def _display_closed_positions_summary(self):
        """Display summary of all closed positions"""
        if not self.closed_positions:
            print("\n📈 No closed positions")
            return

        total_realized = sum(pos['pnl'] for pos in self.closed_positions)
        winners = [p for p in self.closed_positions if p['pnl'] > 0]
        losers = [p for p in self.closed_positions if p['pnl'] <= 0]

        print(f"\n📈 CLOSED POSITIONS: {len(self.closed_positions)} trades")
        print(f"   Winners: {len(winners)} trades")
        print(f"   Losers:  {len(losers)} trades")
        print(f"   Win Rate: {(len(winners) / len(self.closed_positions) * 100):.1f}%")
        print(f"   Total Realized P&L: ${total_realized:+,.2f}")

        if winners:
            avg_win = sum(p['pnl'] for p in winners) / len(winners)
            print(f"   Avg Win: ${avg_win:,.2f}")

        if losers:
            avg_loss = sum(p['pnl'] for p in losers) / len(losers)
            print(f"   Avg Loss: ${avg_loss:,.2f}")

        print("\n📋 Trade Details:")
        for pos in self.closed_positions:
            print(f"   {pos['ticker']:6s} | ${pos['pnl']:+8,.2f} ({pos['pnl_pct']:+6.2f}%) | "
                  f"{pos['entry_signal'][:15]:15s} → {pos['exit_signal'][:15]:15s}")

    def _display_signal_performance(self):
        """Display performance breakdown by entry signal type"""
        if not self.closed_positions:
            return

        print(f"\n🎯 SIGNAL PERFORMANCE BREAKDOWN")
        print(f"{'=' * 80}")

        # Group trades by entry signal
        signal_stats = {}

        for pos in self.closed_positions:
            signal = pos['entry_signal']

            if signal not in signal_stats:
                signal_stats[signal] = {
                    'trades': [],
                    'winners': 0,
                    'losers': 0,
                    'total_pnl': 0,
                    'total_pnl_pct': 0
                }

            signal_stats[signal]['trades'].append(pos)
            signal_stats[signal]['total_pnl'] += pos['pnl']
            signal_stats[signal]['total_pnl_pct'] += pos['pnl_pct']

            if pos['pnl'] > 0:
                signal_stats[signal]['winners'] += 1
            else:
                signal_stats[signal]['losers'] += 1

        # Display stats for each signal type
        for signal, stats in sorted(signal_stats.items()):
            total_trades = len(stats['trades'])
            win_rate = (stats['winners'] / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0
            avg_pnl_pct = stats['total_pnl_pct'] / total_trades if total_trades > 0 else 0

            # Calculate avg win and avg loss
            winners = [t for t in stats['trades'] if t['pnl'] > 0]
            losers = [t for t in stats['trades'] if t['pnl'] <= 0]

            avg_win = sum(t['pnl'] for t in winners) / len(winners) if winners else 0
            avg_loss = sum(t['pnl'] for t in losers) / len(losers) if losers else 0

            # Profit factor (total wins / total losses)
            total_wins = sum(t['pnl'] for t in winners)
            total_losses = abs(sum(t['pnl'] for t in losers))
            profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

            print(f"\n📌 {signal.upper()}")
            print(f"   Trades:       {total_trades}")
            print(f"   Win Rate:     {win_rate:.1f}% ({stats['winners']}W / {stats['losers']}L)")
            print(f"   Total P&L:    ${stats['total_pnl']:+,.2f}")
            print(f"   Avg P&L:      ${avg_pnl:+,.2f} ({avg_pnl_pct:+.2f}%)")
            print(f"   Avg Win:      ${avg_win:+,.2f}")
            print(f"   Avg Loss:     ${avg_loss:+,.2f}")
            print(f"   Profit Factor: {profit_factor:.2f}x")

            # Show individual trades for this signal
            print(f"   Trades:")
            for pos in stats['trades']:
                print(f"      {pos['ticker']:6s} | ${pos['pnl']:+8,.2f} ({pos['pnl_pct']:+6.2f}%) | "
                      f"Exit: {pos['exit_signal'][:25]:25s}")

        print(f"\n{'=' * 80}")


    def _display_open_positions_summary(self):
        """Display unrealized P&L for open positions"""
        if not self.positions:
            print("\n📊 No open positions")
            return

        print(f"\n📊 OPEN POSITIONS: {len(self.positions)}")
        total_unrealized = 0

        for ticker, pos in self.positions.items():
            try:
                current_price = self.strategy.get_last_price(ticker)
                unrealized_pnl = (current_price - pos['entry_price']) * pos['quantity']
                unrealized_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                total_unrealized += unrealized_pnl

                print(f"   {ticker:6s} | {pos['quantity']:3d} shares @ ${pos['entry_price']:7.2f} | "
                      f"Current: ${current_price:7.2f} | P&L: ${unrealized_pnl:+8,.2f} ({unrealized_pct:+6.2f}%)")
            except:
                print(f"   {ticker:6s} | Could not calculate unrealized P&L")

        print(f"\n   Total Unrealized P&L: ${total_unrealized:+,.2f}")