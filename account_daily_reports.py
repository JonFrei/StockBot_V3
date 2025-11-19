"""
Enhanced Trading Window Controls

Adds:
- Market holiday detection
- Mid-window startup handling
- Maintains once-per-day trading logic
"""

from datetime import time, date
import pytz
from config import Config

# =============================================================================
# TRADING WINDOW CONFIGURATION
# =============================================================================

TRADING_START_TIME = time(10, 0)  # 10:00 AM EST
TRADING_END_TIME = time(11, 0)  # 11:00 AM EST

# =============================================================================
# US MARKET HOLIDAYS (2025)
# =============================================================================

# NYSE/NASDAQ holiday schedule
US_MARKET_HOLIDAYS_2025 = {
    date(2025, 1, 1),  # New Year's Day
    date(2025, 1, 20),  # Martin Luther King Jr. Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),  # Independence Day
    date(2025, 9, 1),  # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
}


def is_market_holiday(check_date):
    """
    Check if date is a US market holiday

    Args:
        check_date: datetime.date object

    Returns:
        bool: True if holiday, False otherwise
    """
    # Check if weekend
    if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return True

    # Check if holiday
    return check_date in US_MARKET_HOLIDAYS_2025


# =============================================================================
# TRADING WINDOW VALIDATION
# =============================================================================

def is_within_trading_window(strategy):
    """
    Check if current time is within trading window (10-11 AM EST)

    ENHANCED:
    - Checks for market holidays
    - Checks for weekends
    - Gracefully handles mid-window startup

    Args:
        strategy: Lumibot Strategy instance

    Returns:
        bool: True if within trading window, False otherwise
    """
    if Config.BACKTESTING:
        return True

    try:
        # Get current time in EST
        est = pytz.timezone('US/Eastern')
        current_datetime_est = strategy.get_datetime().astimezone(est)
        current_time_est = current_datetime_est.time()
        current_date = current_datetime_est.date()

        # Check if market holiday
        if is_market_holiday(current_date):
            day_name = current_datetime_est.strftime('%A')
            print(f"[INFO] Market closed - {day_name}, {current_date} is a holiday/weekend")
            return False

        # Check if within window
        is_within = TRADING_START_TIME <= current_time_est <= TRADING_END_TIME

        if not is_within:
            if current_time_est < TRADING_START_TIME:
                print(f"[INFO] Before trading window (current: {current_time_est.strftime('%I:%M %p')} EST, "
                      f"window opens at {TRADING_START_TIME.strftime('%I:%M %p')} EST)")
            else:
                print(f"[INFO] After trading window (current: {current_time_est.strftime('%I:%M %p')} EST, "
                      f"window closed at {TRADING_END_TIME.strftime('%I:%M %p')} EST)")

        return is_within

    except Exception as e:
        print(f"[WARN] Could not check trading window: {e}")
        return False


def has_traded_today(strategy, last_trade_date):
    """
    Check if strategy has already traded today

    MAINTAINS: Once-per-day trading logic

    Args:
        strategy: Lumibot Strategy instance
        last_trade_date: Last date trading occurred (date object)

    Returns:
        bool: True if already traded today, False otherwise
    """
    if Config.BACKTESTING:
        return False

    current_date = strategy.get_datetime().date()

    if last_trade_date == current_date:
        print(f"[INFO] Already traded today ({current_date}) - skipping iteration")
        return True

    return False


# =============================================================================
# DAILY SUMMARY REPORTING (unchanged)
# =============================================================================

def print_daily_summary(strategy, current_date):
    """
    Print comprehensive daily trading summary

    Shows:
    - Portfolio status (value, cash, invested)
    - Active positions with P&L
    - Today's closed trades
    - Stock rotation status
    - Per-ticker performance (all-time)
    - Overall performance metrics

    Args:
        strategy: Lumibot Strategy instance with profit_tracker and stock_rotator
        current_date: Current datetime object
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
            entry_price = float(position.avg_fill_price)

            try:
                current_price = strategy.get_last_price(ticker)
                pnl_dollars = (current_price - entry_price) * qty
                pnl_pct = ((current_price - entry_price) / entry_price * 100)
                total_unrealized += pnl_dollars

                # Get award from stock rotator
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
    # TODAY'S CLOSED TRADES
    # =========================================================================

    today_trades = [t for t in strategy.profit_tracker.closed_trades
                    if t.get('exit_date') and t['exit_date'].date() == current_date.date()]

    if today_trades:
        print(f"\n🔄 TODAY'S CLOSED TRADES: {len(today_trades)}")
        print(f"\n{'Ticker':<8} {'Qty':<8} {'Entry':<10} {'Exit':<10} {'P&L $':<12} {'P&L %':<8} {'Signal'}")
        print(f"{'─' * 80}")

        total_realized_today = 0
        winners_today = 0

        for trade in today_trades:
            ticker = trade['ticker']
            qty = trade['quantity']
            entry = trade['entry_price']
            exit_price = trade['exit_price']
            pnl = trade['pnl_dollars']
            pnl_pct = trade['pnl_pct']
            signal = trade['entry_signal']

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
    # PER-TICKER PERFORMANCE (ALL TIME)
    # =========================================================================

    print(f"\n📊 PER-TICKER PERFORMANCE (All Time):")
    print(f"\n{'Ticker':<8} {'Trades':<8} {'Wins':<8} {'Win Rate':<10} {'Total P&L':<12} {'Award'}")
    print(f"{'─' * 80}")

    # Get ticker stats
    ticker_stats = {}
    for trade in strategy.profit_tracker.closed_trades:
        ticker = trade['ticker']
        if ticker not in ticker_stats:
            ticker_stats[ticker] = {'trades': 0, 'wins': 0, 'total_pnl': 0}

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
    # OVERALL PERFORMANCE
    # =========================================================================

    total_trades = len(strategy.profit_tracker.closed_trades)
    if total_trades > 0:
        total_wins = sum(1 for t in strategy.profit_tracker.closed_trades if t['pnl_dollars'] > 0)
        overall_wr = (total_wins / total_trades * 100)
        total_realized = sum(t['pnl_dollars'] for t in strategy.profit_tracker.closed_trades)

        print(f"\n{'─' * 80}")
        print(f"📊 OVERALL PERFORMANCE:")
        print(f"   Total Trades: {total_trades}")
        print(f"   Win Rate: {total_wins}/{total_trades} ({overall_wr:.1f}%)")
        print(f"   Total Realized P&L: ${total_realized:>+,.2f}")

    print(f"\n{'=' * 80}\n")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_trading_window_info():
    """
    Get trading window configuration info

    Returns:
        dict: Trading window details
    """
    return {
        'start_time': TRADING_START_TIME,
        'end_time': TRADING_END_TIME,
        'start_time_str': TRADING_START_TIME.strftime('%I:%M %p'),
        'end_time_str': TRADING_END_TIME.strftime('%I:%M %p'),
        'timezone': 'US/Eastern'
    }


def print_trading_window_info():
    """Print trading window information"""
    info = get_trading_window_info()
    print(f"\n{'=' * 80}")
    print(f"⏰ TRADING WINDOW CONFIGURATION")
    print(f"{'=' * 80}")
    print(f"Start Time: {info['start_time_str']} {info['timezone']}")
    print(f"End Time:   {info['end_time_str']} {info['timezone']}")
    print(f"Duration:   1 hour")
    print(f"Frequency:  Once per day")
    print(f"{'=' * 80}\n")