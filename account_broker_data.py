"""
Trading Window Configuration and Market Data

Handles:
- Trading window times and validation
- Market holiday detection
- Trading frequency controls
"""

from datetime import time, date
import pytz
from config import Config

# =============================================================================
# TRADING WINDOW CONFIGURATION
# =============================================================================

TRADING_START_TIME = time(10, 0)  # 10:00 AM EST
TRADING_END_TIME = time(14, 0)  # 11:00 AM EST

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


def is_within_trading_window(strategy):
    """
    Check if current time is within trading window (10-11 AM EST)

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