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
        print(f"Signal: {sell_signal['msg']}")
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