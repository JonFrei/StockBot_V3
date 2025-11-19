"""
Broker API Wrapper with Retry Logic and Rate Limiting

Wraps Alpaca broker calls with:
- Automatic retry on transient failures
- Exponential backoff
- Rate limit detection and handling
- Circuit breaker for persistent failures
"""

import time
from functools import wraps
from datetime import datetime, timedelta


class RateLimitError(Exception):
    """Raised when API rate limit is hit"""
    pass


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open"""
    pass


class CircuitBreaker:
    """
    Circuit breaker pattern for API calls

    Opens after N consecutive failures, preventing further calls
    Closes after cooldown period
    """

    def __init__(self, failure_threshold=5, cooldown_seconds=300):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'closed'  # 'closed', 'open', 'half_open'

    def record_success(self):
        """Record successful API call"""
        self.failure_count = 0
        if self.state == 'half_open':
            self.state = 'closed'
            print("[CIRCUIT BREAKER] Closed - API recovered")

    def record_failure(self):
        """Record failed API call"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.failure_count >= self.failure_threshold and self.state == 'closed':
            self.state = 'open'
            print(
                f"[CIRCUIT BREAKER] OPENED after {self.failure_count} failures - API calls blocked for {self.cooldown_seconds}s")

    def can_attempt(self):
        """Check if API call can be attempted"""
        if self.state == 'closed':
            return True

        if self.state == 'open':
            # Check if cooldown period has passed
            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed >= self.cooldown_seconds:
                    self.state = 'half_open'
                    print("[CIRCUIT BREAKER] Half-open - Testing API recovery")
                    return True
            return False

        # Half-open - allow single test request
        return True

    def get_status(self):
        """Get circuit breaker status"""
        return {
            'state': self.state,
            'failure_count': self.failure_count,
            'last_failure': self.last_failure_time
        }


def retry_on_failure(max_retries=3, initial_delay=1.0, backoff_factor=2.0, rate_limit_delay=60):
    """
    Decorator for automatic retry with exponential backoff

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay on each retry
        rate_limit_delay: Delay in seconds when rate limit hit
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    return result

                except RateLimitError as e:
                    if attempt == max_retries:
                        print(f"[BROKER API] Rate limit - max retries exceeded")
                        raise
                    print(
                        f"[BROKER API] Rate limit hit - waiting {rate_limit_delay}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(rate_limit_delay)

                except Exception as e:
                    if attempt == max_retries:
                        print(f"[BROKER API] Call failed after {max_retries} retries: {e}")
                        raise

                    # Check for rate limit indicators in error message
                    error_str = str(e).lower()
                    if 'rate limit' in error_str or '429' in error_str:
                        print(f"[BROKER API] Rate limit detected - waiting {rate_limit_delay}s")
                        time.sleep(rate_limit_delay)
                    else:
                        print(f"[BROKER API] Call failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
                        time.sleep(delay)
                        delay *= backoff_factor

            # Should never reach here
            raise Exception(f"Retry logic failed for {func.__name__}")

        return wrapper

    return decorator


class BrokerAPIWrapper:
    """
    Wraps strategy broker calls with retry logic and circuit breaker

    Usage:
        wrapper = BrokerAPIWrapper(strategy)
        positions = wrapper.get_positions()
        price = wrapper.get_last_price('AAPL')
    """

    def __init__(self, strategy):
        self.strategy = strategy
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            cooldown_seconds=300  # 5 minutes
        )
        self.call_count = 0
        self.failure_count = 0
        self.last_rate_limit_time = None

    @retry_on_failure(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
    def get_positions(self):
        """Get positions with retry logic"""
        if not self.circuit_breaker.can_attempt():
            raise CircuitBreakerOpen("Circuit breaker is open - API unavailable")

        try:
            self.call_count += 1
            positions = self.strategy.get_positions()
            self.circuit_breaker.record_success()
            return positions

        except Exception as e:
            self.failure_count += 1
            self.circuit_breaker.record_failure()

            # Check for rate limit
            if 'rate limit' in str(e).lower() or '429' in str(e):
                self.last_rate_limit_time = datetime.now()
                raise RateLimitError(str(e))
            raise

    @retry_on_failure(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
    def get_last_price(self, ticker):
        """Get last price with retry logic"""
        if not self.circuit_breaker.can_attempt():
            raise CircuitBreakerOpen("Circuit breaker is open - API unavailable")

        try:
            self.call_count += 1
            price = self.strategy.get_last_price(ticker)
            self.circuit_breaker.record_success()
            return price

        except Exception as e:
            self.failure_count += 1
            self.circuit_breaker.record_failure()

            if 'rate limit' in str(e).lower() or '429' in str(e):
                self.last_rate_limit_time = datetime.now()
                raise RateLimitError(str(e))
            raise

    @retry_on_failure(max_retries=3, initial_delay=2.0, backoff_factor=2.0)
    def submit_order(self, order):
        """Submit order with retry logic"""
        if not self.circuit_breaker.can_attempt():
            raise CircuitBreakerOpen("Circuit breaker is open - API unavailable")

        try:
            self.call_count += 1
            result = self.strategy.submit_order(order)
            self.circuit_breaker.record_success()
            return result

        except Exception as e:
            self.failure_count += 1
            self.circuit_breaker.record_failure()

            if 'rate limit' in str(e).lower() or '429' in str(e):
                self.last_rate_limit_time = datetime.now()
                raise RateLimitError(str(e))
            raise

    def get_cash(self):
        """Get cash balance - no retry needed (cached value)"""
        return self.strategy.get_cash()

    def get_datetime(self):
        """Get current datetime - no retry needed"""
        return self.strategy.get_datetime()

    def create_order(self, *args, **kwargs):
        """Create order object - no retry needed (local operation)"""
        return self.strategy.create_order(*args, **kwargs)

    def get_statistics(self):
        """Get wrapper statistics"""
        return {
            'total_calls': self.call_count,
            'total_failures': self.failure_count,
            'failure_rate': self.failure_count / self.call_count if self.call_count > 0 else 0,
            'circuit_breaker': self.circuit_breaker.get_status(),
            'last_rate_limit': self.last_rate_limit_time
        }

    def print_statistics(self):
        """Print API call statistics"""
        stats = self.get_statistics()
        print(f"\n{'=' * 80}")
        print(f"BROKER API STATISTICS")
        print(f"{'=' * 80}")
        print(f"Total Calls: {stats['total_calls']}")
        print(f"Total Failures: {stats['total_failures']}")
        print(f"Failure Rate: {stats['failure_rate'] * 100:.2f}%")
        print(f"Circuit Breaker: {stats['circuit_breaker']['state'].upper()}")
        if stats['last_rate_limit']:
            print(f"Last Rate Limit: {stats['last_rate_limit'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")