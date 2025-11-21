"""
Email Test Script

Tests the email notification system with sample data.
Run this to verify your Resend API configuration before deploying.

Usage:
    python test_email.py
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import email system
import account_email_notifications
from config import Config


def create_test_execution_tracker():
    """Create a sample execution tracker with test data"""
    tracker = account_email_notifications.ExecutionTracker()

    # Add some test actions
    tracker.record_action('entries', count=3)
    tracker.record_action('exits', count=2)
    tracker.record_action('rotation')

    # Add a test warning
    tracker.add_warning("Market volatility detected - reduced position sizing")

    # Add a test error (optional)
    # tracker.add_error("Test Error Context", "This is a test error", "Test traceback...")

    # Complete the tracker
    tracker.complete('SUCCESS')

    return tracker


def create_test_strategy():
    """Create a mock strategy object with test data"""

    class MockPosition:
        def __init__(self, symbol, quantity, avg_entry_price, current_price):
            self.symbol = symbol
            self.quantity = quantity
            self.avg_entry_price = avg_entry_price
            self.current_price = current_price

    class MockTrade:
        def __init__(self, ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct, entry_signal, exit_date):
            self.data = {
                'ticker': ticker,
                'quantity': quantity,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl_dollars': pnl_dollars,
                'pnl_pct': pnl_pct,
                'entry_signal': entry_signal,
                'exit_date': exit_date
            }

        def __getitem__(self, key):
            return self.data[key]

        def get(self, key, default=None):
            return self.data.get(key, default)

    class MockProfitTracker:
        def __init__(self):
            self.closed_trades = [
                MockTrade('AAPL', 10, 150.00, 155.00, 50.00, 3.33, 'swing_trade_1', datetime.now()),
                MockTrade('MSFT', 5, 380.00, 375.00, -25.00, -1.32, 'swing_trade_2', datetime.now()),
                MockTrade('NVDA', 15, 450.00, 475.00, 375.00, 5.56, 'golden_cross', datetime.now()),
            ]

    class MockStockRotator:
        def __init__(self):
            self.ticker_awards = {
                'AAPL': 'standard',
                'MSFT': 'trial',
                'NVDA': 'premium',
                'GOOGL': 'trial',
                'META': 'standard',
            }

        def get_award(self, ticker):
            return self.ticker_awards.get(ticker, 'trial')

    class MockStrategy:
        def __init__(self):
            self.portfolio_value = 100000.00
            self.cash = 45000.00
            self.profit_tracker = MockProfitTracker()
            self.stock_rotator = MockStockRotator()

        def get_cash(self):
            return self.cash

        def get_positions(self):
            return [
                MockPosition('AAPL', 10, 150.00, 152.50),
                MockPosition('NVDA', 15, 450.00, 462.00),
            ]

        def get_last_price(self, ticker):
            prices = {'AAPL': 152.50, 'NVDA': 462.00}
            return prices.get(ticker, 100.00)

    return MockStrategy()


def test_email_sending():
    """Test the email sending functionality"""

    print("\n" + "=" * 80)
    print("EMAIL SYSTEM TEST")
    print("=" * 80)

    # Check configuration
    print("\n1. Checking Configuration...")
    print(f"   EMAIL_SENDER: {Config.EMAIL_SENDER or 'NOT SET'}")
    print(f"   EMAIL_RECIPIENT: {Config.EMAIL_RECIPIENT or 'NOT SET'}")
    print(f"   RESEND_API_KEY: {'SET' if os.getenv('RESEND_API_KEY') else 'NOT SET'}")

    if not Config.EMAIL_SENDER or not Config.EMAIL_RECIPIENT:
        print("\n❌ ERROR: EMAIL_SENDER and EMAIL_RECIPIENT must be set")
        print("   Add them to your .env file or environment variables")
        return False

    if not os.getenv('RESEND_API_KEY'):
        print("\n⚠️  WARNING: RESEND_API_KEY not set")
        print("   Email will be logged to console only")
        print("   Get API key from: https://resend.com/api-keys")

    # Create test data
    print("\n2. Creating Test Data...")
    execution_tracker = create_test_execution_tracker()
    mock_strategy = create_test_strategy()
    test_date = datetime.now()

    print(f"   ✅ Execution tracker created")
    print(f"   ✅ Mock strategy created with 2 positions, 3 closed trades")

    # Send test email
    print("\n3. Sending Test Email...")
    print(f"   From: {Config.EMAIL_SENDER}")
    print(f"   To: {Config.EMAIL_RECIPIENT}")
    print(f"   Subject: Test Trading Bot Report - {test_date.strftime('%Y-%m-%d')}")

    try:
        account_email_notifications.send_daily_summary_email(
            strategy=mock_strategy,
            current_date=test_date,
            execution_tracker=execution_tracker
        )
        print("\n✅ Email function completed")

        if os.getenv('RESEND_API_KEY'):
            print("\n4. Check your inbox!")
            print(f"   Email should arrive at: {Config.EMAIL_RECIPIENT}")
            print("   Check spam folder if not in inbox")
        else:
            print("\n4. Check console output above for email content")
            print("   Add RESEND_API_KEY to send real emails")

        return True

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_crash_notification():
    """Test crash notification email"""

    print("\n" + "=" * 80)
    print("CRASH NOTIFICATION TEST")
    print("=" * 80)

    print("\nSending test crash notification...")

    test_error = "Test error: Something went wrong"
    test_traceback = """Traceback (most recent call last):
  File "test.py", line 42, in main
    raise ValueError("Test error")
ValueError: Test error: Something went wrong"""

    try:
        account_email_notifications.send_crash_notification(
            error_message=test_error,
            error_traceback=test_traceback
        )
        print("✅ Crash notification sent")
        return True
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def main():
    """Run all tests"""

    print("\n" + "=" * 80)
    print("TRADING BOT EMAIL SYSTEM TEST SUITE")
    print("=" * 80)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")

    # Test 1: Daily summary email
    success1 = test_email_sending()

    # Test 2: Crash notification
    print("\n")
    success2 = test_crash_notification()

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Daily Summary Email: {'✅ PASSED' if success1 else '❌ FAILED'}")
    print(f"Crash Notification: {'✅ PASSED' if success2 else '❌ FAILED'}")

    if success1 and success2:
        print("\n🎉 All tests passed!")
        print("\nNext steps:")
        print("1. Check your email inbox (or spam folder)")
        print("2. If no email received, verify RESEND_API_KEY is correct")
        print("3. Deploy to Railway with same environment variables")
    else:
        print("\n⚠️  Some tests failed - check errors above")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()