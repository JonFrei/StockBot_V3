"""
Diagnostic Script: Test All Methods to Get Average Entry Price from Alpaca

This script connects to Alpaca and attempts to extract the average entry price
using all known attributes and methods from alpaca-trade-api.

Run this script to see which attributes are actually available and working.
"""

from alpaca_trade_api import REST
from config import Config

# Initialize Alpaca client
api = REST(
    Config.ALPACA_API_KEY,
    Config.ALPACA_API_SECRET,
    base_url='https://paper-api.alpaca.markets' if Config.ALPACA_PAPER else 'https://api.alpaca.markets'
)


def diagnose_position_attributes(position):
    """Test all known methods to extract entry price from a position object"""

    ticker = position.symbol
    results = {
        'ticker': ticker,
        'quantity': position.qty,
        'working_methods': [],
        'failed_methods': [],
        'all_attributes': []
    }

    print(f"\n{'=' * 80}")
    print(f"DIAGNOSING: {ticker}")
    print(f"{'=' * 80}")

    # List all available attributes
    print(f"\n📋 All available attributes:")
    for attr in dir(position):
        if not attr.startswith('_'):
            results['all_attributes'].append(attr)
            try:
                value = getattr(position, attr)
                if not callable(value):
                    print(f"   {attr}: {value} (type: {type(value).__name__})")
            except:
                print(f"   {attr}: [Error accessing]")

    print(f"\n🔍 Testing entry price extraction methods:")
    print(f"{'─' * 80}")

    # Method 1: avg_entry_price
    try:
        price = float(position.avg_entry_price)
        if price > 0:
            print(f"✅ position.avg_entry_price = ${price:.2f}")
            results['working_methods'].append({
                'method': 'position.avg_entry_price',
                'value': price
            })
        else:
            print(f"⚠️  position.avg_entry_price exists but is {price}")
            results['failed_methods'].append('avg_entry_price (zero or negative)')
    except AttributeError:
        print(f"❌ position.avg_entry_price - AttributeError (doesn't exist)")
        results['failed_methods'].append('avg_entry_price (AttributeError)')
    except (ValueError, TypeError) as e:
        print(f"❌ position.avg_entry_price - {type(e).__name__}: {e}")
        results['failed_methods'].append(f'avg_entry_price ({type(e).__name__})')

    # Method 2: cost_basis / qty
    try:
        cost_basis = float(position.cost_basis)
        qty = float(position.qty)
        if qty > 0:
            price = cost_basis / qty
            print(f"✅ position.cost_basis / position.qty = ${price:.2f}")
            results['working_methods'].append({
                'method': 'position.cost_basis / position.qty',
                'value': price
            })
        else:
            print(f"⚠️  cost_basis/qty exists but qty is {qty}")
            results['failed_methods'].append('cost_basis/qty (zero quantity)')
    except AttributeError as e:
        print(f"❌ cost_basis/qty - AttributeError: {e}")
        results['failed_methods'].append('cost_basis/qty (AttributeError)')
    except (ValueError, TypeError, ZeroDivisionError) as e:
        print(f"❌ cost_basis/qty - {type(e).__name__}: {e}")
        results['failed_methods'].append(f'cost_basis/qty ({type(e).__name__})')

    # Method 3: avg_fill_price
    try:
        price = float(position.avg_fill_price)
        if price > 0:
            print(f"✅ position.avg_fill_price = ${price:.2f}")
            results['working_methods'].append({
                'method': 'position.avg_fill_price',
                'value': price
            })
        else:
            print(f"⚠️  position.avg_fill_price exists but is {price}")
            results['failed_methods'].append('avg_fill_price (zero or negative)')
    except AttributeError:
        print(f"❌ position.avg_fill_price - AttributeError (doesn't exist)")
        results['failed_methods'].append('avg_fill_price (AttributeError)')
    except (ValueError, TypeError) as e:
        print(f"❌ position.avg_fill_price - {type(e).__name__}: {e}")
        results['failed_methods'].append(f'avg_fill_price ({type(e).__name__})')

    # Method 4: current_price (last resort)
    try:
        price = float(position.current_price)
        print(f"ℹ️  position.current_price = ${price:.2f} (fallback, not entry price)")
        results['working_methods'].append({
            'method': 'position.current_price (fallback)',
            'value': price
        })
    except AttributeError:
        print(f"❌ position.current_price - AttributeError")
        results['failed_methods'].append('current_price (AttributeError)')
    except (ValueError, TypeError) as e:
        print(f"❌ position.current_price - {type(e).__name__}: {e}")
        results['failed_methods'].append(f'current_price ({type(e).__name__})')

    # Method 5: Check for any other price-related attributes
    price_attrs = [attr for attr in dir(position)
                   if 'price' in attr.lower() or 'cost' in attr.lower() or 'basis' in attr.lower()]

    if price_attrs:
        print(f"\n🔎 Other price-related attributes found:")
        for attr in price_attrs:
            if attr not in ['avg_entry_price', 'avg_fill_price', 'current_price', 'cost_basis']:
                try:
                    value = getattr(position, attr)
                    if not callable(value):
                        print(f"   {attr}: {value}")
                except:
                    pass

    return results


def main():
    """Main diagnostic routine"""

    print("\n" + "=" * 80)
    print("ALPACA POSITION ENTRY PRICE DIAGNOSTIC")
    print("=" * 80)
    print(f"API Mode: {'PAPER' if Config.ALPACA_PAPER else 'LIVE'}")
    print("=" * 80)

    try:
        # Get all positions
        positions = api.list_positions()

        if not positions:
            print("\n⚠️  No open positions found. Please open at least one position to test.")
            return

        print(f"\n📊 Found {len(positions)} open position(s)\n")

        all_results = []

        # Test each position
        for position in positions:
            results = diagnose_position_attributes(position)
            all_results.append(results)

        # Summary
        print(f"\n{'=' * 80}")
        print("SUMMARY")
        print(f"{'=' * 80}")

        for results in all_results:
            print(f"\n{results['ticker']}:")
            print(f"   Working methods: {len(results['working_methods'])}")
            for method in results['working_methods']:
                print(f"      ✅ {method['method']}: ${method['value']:.2f}")

            if results['failed_methods']:
                print(f"   Failed methods: {len(results['failed_methods'])}")
                for method in results['failed_methods'][:3]:  # Show first 3
                    print(f"      ❌ {method}")

        # Recommendation
        print(f"\n{'=' * 80}")
        print("RECOMMENDATION")
        print(f"{'=' * 80}")

        # Find most common working method
        method_counts = {}
        for results in all_results:
            for method in results['working_methods']:
                method_name = method['method']
                method_counts[method_name] = method_counts.get(method_name, 0) + 1

        if method_counts:
            best_method = max(method_counts.items(), key=lambda x: x[1])
            print(f"\n✅ Most reliable method: {best_method[0]}")
            print(f"   (worked for {best_method[1]}/{len(all_results)} positions)")

            print(f"\n💡 Suggested fallback order:")
            sorted_methods = sorted(method_counts.items(), key=lambda x: x[1], reverse=True)
            for i, (method, count) in enumerate(sorted_methods, 1):
                print(f"   {i}. {method} ({count}/{len(all_results)})")
        else:
            print("\n❌ No working methods found!")
            print("   This is a serious issue. Check Alpaca API documentation.")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()