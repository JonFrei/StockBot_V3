"""
Ticker Cooldown System

Prevents buying the same ticker too frequently to reduce:
- Concentration risk
- Chasing behavior (buying higher after initial entry)
- FOMO-driven consecutive purchases

Example Problem (From Your Backtest):
    NVDA bought 3 consecutive days:
    - Jan 8:  Buy @ $52.25
    - Jan 9:  Buy @ $53.14 (+1.7% higher)
    - Jan 10: Buy @ $54.35 (+4.0% higher)

    Result: Inflated average price, increased risk

With Cooldown:
    NVDA:
    - Jan 8:  Buy @ $52.25
    - Jan 9:  SKIP (cooldown)
    - Jan 10: SKIP (cooldown)
    - Jan 11: Can buy again if signal valid

    Result: Only 1 position, no chasing
"""

from datetime import datetime, timedelta


class TickerCooldown:
    """
    Manages cooldown periods for ticker re-purchases

    Usage:
        cooldown = TickerCooldown(cooldown_days=3)

        if cooldown.can_buy('NVDA', current_date):
            # Place order
            cooldown.record_buy('NVDA', current_date)

        # When position fully closed
        cooldown.clear('NVDA')
    """

    def __init__(self, cooldown_days=3):
        """
        Initialize cooldown tracker

        Args:
            cooldown_days: Minimum days between purchases of same ticker
                          3 = Balanced (recommended)
                          5 = Conservative
                          1 = Aggressive
        """
        self.cooldown_days = cooldown_days
        self.last_buy_dates = {}  # {ticker: last_buy_date}
        self.buy_count = {}  # {ticker: total_buys} for statistics

    def can_buy(self, ticker, current_date):
        """
        Check if enough time has passed since last buy

        Args:
            ticker: Stock symbol (e.g., 'NVDA')
            current_date: Current date (datetime object)

        Returns:
            bool: True if can buy, False if still in cooldown
        """
        if ticker not in self.last_buy_dates:
            return True  # Never bought before

        last_buy = self.last_buy_dates[ticker]
        days_since_last_buy = (current_date - last_buy).days

        return days_since_last_buy >= self.cooldown_days

    def days_until_can_buy(self, ticker, current_date):
        """
        Get number of days until ticker can be bought again

        Returns:
            int: Days remaining (0 if can buy now)
        """
        if ticker not in self.last_buy_dates:
            return 0

        last_buy = self.last_buy_dates[ticker]
        days_since_last_buy = (current_date - last_buy).days
        days_remaining = self.cooldown_days - days_since_last_buy

        return max(0, days_remaining)

    def record_buy(self, ticker, buy_date):
        """
        Record when we bought this ticker

        Args:
            ticker: Stock symbol
            buy_date: Date of purchase (datetime object)
        """
        self.last_buy_dates[ticker] = buy_date

        # Track statistics
        if ticker not in self.buy_count:
            self.buy_count[ticker] = 0
        self.buy_count[ticker] += 1

    def clear(self, ticker):
        """
        Clear cooldown when position is fully closed

        Args:
            ticker: Stock symbol
        """
        if ticker in self.last_buy_dates:
            del self.last_buy_dates[ticker]

    def get_status(self, ticker, current_date):
        """
        Get detailed status for a ticker

        Returns:
            dict with status information
        """
        if ticker not in self.last_buy_dates:
            return {
                'can_buy': True,
                'days_since_last_buy': None,
                'days_until_can_buy': 0,
                'total_buys': self.buy_count.get(ticker, 0)
            }

        last_buy = self.last_buy_dates[ticker]
        days_since = (current_date - last_buy).days
        days_until = max(0, self.cooldown_days - days_since)

        return {
            'can_buy': days_until == 0,
            'last_buy_date': last_buy,
            'days_since_last_buy': days_since,
            'days_until_can_buy': days_until,
            'total_buys': self.buy_count.get(ticker, 0)
        }

    def get_all_cooldowns(self, current_date):
        """
        Get status for all tickers currently on cooldown

        Returns:
            list of (ticker, days_remaining) tuples
        """
        cooldowns = []

        for ticker, last_buy in self.last_buy_dates.items():
            days_since = (current_date - last_buy).days
            days_remaining = self.cooldown_days - days_since

            if days_remaining > 0:
                cooldowns.append((ticker, days_remaining))

        return sorted(cooldowns, key=lambda x: x[1])  # Sort by days remaining

    def get_statistics(self):
        """
        Get cooldown statistics

        Returns:
            dict with stats
        """
        return {
            'cooldown_days': self.cooldown_days,
            'tickers_tracked': len(self.last_buy_dates),
            'total_buys_recorded': sum(self.buy_count.values()),
            'buy_count_by_ticker': dict(sorted(
                self.buy_count.items(),
                key=lambda x: x[1],
                reverse=True
            ))
        }
