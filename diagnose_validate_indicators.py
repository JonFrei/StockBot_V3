"""
Indicator Validation Script
Compares custom indicator calculations against pandas_ta library

Usage: python validate_indicators.py
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import Config
import stock_indicators as indicators

# =============================================================================
# CONFIGURATION
# =============================================================================

TEST_TICKERS = ['AAPL', 'NVDA', 'TSLA', 'SPY', 'AMD']
TOLERANCE_PCT = 1.0  # Allow 1% difference
DAYS_OF_DATA = 250


# =============================================================================
# DATA FETCHING
# =============================================================================

def fetch_test_data(symbols):
    """Fetch historical data for validation"""
    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_API_SECRET
    )

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_OF_DATA + 50)

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start_date,
        end=end_date,
        adjustment='all'
    )

    bars = client.get_stock_bars(request)

    result = {}
    for symbol in symbols:
        symbol_bars = [b for b in bars.data.get(symbol, [])]
        if not symbol_bars:
            continue

        df = pd.DataFrame([{
            'timestamp': b.timestamp,
            'open': float(b.open),
            'high': float(b.high),
            'low': float(b.low),
            'close': float(b.close),
            'volume': float(b.volume)
        } for b in symbol_bars])

        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        result[symbol] = df

    return result


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_rsi(df):
    """Compare RSI calculations"""
    # Your calculation (updated signature)
    your_rsi = indicators.get_rsi(df, period=14)

    # pandas_ta calculation
    pta_rsi = ta.rsi(df['close'], length=14).iloc[-1]

    return your_rsi, pta_rsi


def validate_ema(df, period):
    """Compare EMA calculations"""
    your_ema = indicators.get_ema(df, period=period)
    pta_ema = ta.ema(df['close'], length=period).iloc[-1]
    return your_ema, pta_ema


def validate_sma(df, period):
    """Compare SMA calculations"""
    sma_data = indicators.get_sma(df, period=period)
    your_sma = sma_data['sma']
    pta_sma = ta.sma(df['close'], length=period).iloc[-1]
    return your_sma, pta_sma


def validate_bollinger(df):
    """Compare Bollinger Bands calculations"""
    your_bb = indicators.get_bollinger(df, stdev=2, period=20)
    pta_bb = ta.bbands(df['close'], length=20, std=2)

    # Find correct column names (may vary by pandas_ta version)
    upper_col = [c for c in pta_bb.columns if 'BBU' in c][0]
    mid_col = [c for c in pta_bb.columns if 'BBM' in c][0]
    lower_col = [c for c in pta_bb.columns if 'BBL' in c][0]

    return {
        'upper': (your_bb['bollinger_upper'], pta_bb[upper_col].iloc[-1]),
        'middle': (your_bb['bollinger_mean'], pta_bb[mid_col].iloc[-1]),
        'lower': (your_bb['bollinger_lower'], pta_bb[lower_col].iloc[-1])
    }


def validate_atr(df):
    """Compare ATR calculations"""
    your_atr = indicators.get_atr(df, period=14)
    pta_atr = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
    return your_atr, pta_atr


def validate_macd(df):
    """Compare MACD calculations"""
    your_macd = indicators.get_macd(df)
    pta_macd = ta.macd(df['close'], fast=12, slow=26, signal=9)

    # Find correct column names
    macd_col = [c for c in pta_macd.columns if c.startswith('MACD_')][0]
    signal_col = [c for c in pta_macd.columns if 'MACDs' in c][0]
    hist_col = [c for c in pta_macd.columns if 'MACDh' in c][0]

    return {
        'macd': (your_macd['macd'], pta_macd[macd_col].iloc[-1]),
        'signal': (your_macd['macd_signal'], pta_macd[signal_col].iloc[-1]),
        'histogram': (your_macd['macd_histogram'], pta_macd[hist_col].iloc[-1])
    }


def validate_adx(df):
    """Compare ADX calculations"""
    your_adx = indicators.get_adx(df, period=14)
    pta_adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)

    # Find ADX column
    adx_col = [c for c in pta_adx_df.columns if c.startswith('ADX')][0]
    pta_adx = pta_adx_df[adx_col].iloc[-1]

    return your_adx, pta_adx


def validate_stochastic(df):
    """Compare Stochastic calculations"""
    your_stoch = indicators.get_stochastic(df, k_period=14, d_period=3)
    pta_stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3)

    # Find correct column names
    k_col = [c for c in pta_stoch.columns if 'STOCHk' in c][0]
    d_col = [c for c in pta_stoch.columns if 'STOCHd' in c][0]

    return {
        'k': (your_stoch['stoch_k'], pta_stoch[k_col].iloc[-1]),
        'd': (your_stoch['stoch_d'], pta_stoch[d_col].iloc[-1])
    }


def validate_williams_r(df):
    """Compare Williams %R calculations"""
    your_willr = indicators.get_williams_r(df, period=14)
    pta_willr = ta.willr(df['high'], df['low'], df['close'], length=14).iloc[-1]
    return your_willr, pta_willr


def validate_roc(df):
    """Compare Rate of Change calculations"""
    your_roc = indicators.get_roc(df, period=12)
    pta_roc = ta.roc(df['close'], length=12).iloc[-1]
    return your_roc, pta_roc


def validate_obv(df):
    """Compare OBV calculations"""
    your_obv_data = indicators.get_obv_trend(df, period=20)
    your_obv = your_obv_data['obv']
    pta_obv = ta.obv(df['close'], df['volume']).iloc[-1]
    return your_obv, pta_obv


def validate_historical_volatility(df):
    """Compare Historical Volatility calculations"""
    your_hvol = indicators.get_historical_volatility(df, period=20)

    # pandas_ta doesn't have direct hvol, calculate manually for reference
    returns = df['close'].pct_change().dropna().tail(20)
    pta_hvol = returns.std() * (252 ** 0.5) * 100

    return your_hvol, pta_hvol


# =============================================================================
# COMPARISON & REPORTING
# =============================================================================

def calc_diff_pct(yours, reference):
    """Calculate percentage difference"""
    if reference == 0:
        return 0 if yours == 0 else 100
    return abs((yours - reference) / reference) * 100


def check_status(diff_pct):
    """Return PASS/FAIL based on tolerance"""
    return "✓ PASS" if diff_pct <= TOLERANCE_PCT else "✗ FAIL"


def print_result(indicator, yours, reference, results):
    """Print a single comparison result and update results dict"""
    diff = calc_diff_pct(yours, reference)
    status = check_status(diff)

    if diff <= TOLERANCE_PCT:
        results['pass'] += 1
    else:
        results['fail'] += 1

    print(f"  {indicator:<20} {yours:>14.4f}  {reference:>14.4f}  {diff:>8.2f}%  {status}")


def validate_ticker(ticker, df):
    """Run all validations for a single ticker"""
    print(f"\n{'=' * 75}")
    print(f"  {ticker}")
    print(f"{'=' * 75}")
    print(f"  {'Indicator':<20} {'Yours':>14}  {'pandas_ta':>14}  {'Diff':>8}   Status")
    print(f"  {'-' * 71}")

    results = {'pass': 0, 'fail': 0}

    # --- MOMENTUM INDICATORS ---
    try:
        yours, ref = validate_rsi(df)
        print_result("RSI(14)", yours, ref, results)
    except Exception as e:
        print(f"  RSI(14)              ERROR: {e}")

    try:
        yours, ref = validate_roc(df)
        print_result("ROC(12)", yours, ref, results)
    except Exception as e:
        print(f"  ROC(12)              ERROR: {e}")

    try:
        yours, ref = validate_williams_r(df)
        print_result("Williams %R(14)", yours, ref, results)
    except Exception as e:
        print(f"  Williams %R(14)      ERROR: {e}")

    try:
        stoch = validate_stochastic(df)
        print_result("Stoch %K(14,3)", stoch['k'][0], stoch['k'][1], results)
        print_result("Stoch %D(14,3)", stoch['d'][0], stoch['d'][1], results)
    except Exception as e:
        print(f"  Stochastic           ERROR: {e}")

    # --- TREND INDICATORS ---
    print(f"  {'-' * 71}")

    for period in [8, 12, 20, 50]:
        try:
            yours, ref = validate_ema(df, period)
            print_result(f"EMA({period})", yours, ref, results)
        except Exception as e:
            print(f"  EMA({period})             ERROR: {e}")

    for period in [20, 50, 200]:
        try:
            yours, ref = validate_sma(df, period)
            print_result(f"SMA({period})", yours, ref, results)
        except Exception as e:
            print(f"  SMA({period})             ERROR: {e}")

    try:
        yours, ref = validate_adx(df)
        print_result("ADX(14)", yours, ref, results)
    except Exception as e:
        print(f"  ADX(14)              ERROR: {e}")

    try:
        macd = validate_macd(df)
        print_result("MACD Line", macd['macd'][0], macd['macd'][1], results)
        print_result("MACD Signal", macd['signal'][0], macd['signal'][1], results)
        print_result("MACD Histogram", macd['histogram'][0], macd['histogram'][1], results)
    except Exception as e:
        print(f"  MACD                 ERROR: {e}")

    # --- VOLATILITY INDICATORS ---
    print(f"  {'-' * 71}")

    try:
        bb = validate_bollinger(df)
        print_result("BB Upper(20,2)", bb['upper'][0], bb['upper'][1], results)
        print_result("BB Middle(20,2)", bb['middle'][0], bb['middle'][1], results)
        print_result("BB Lower(20,2)", bb['lower'][0], bb['lower'][1], results)
    except Exception as e:
        print(f"  Bollinger Bands      ERROR: {e}")

    try:
        yours, ref = validate_atr(df)
        print_result("ATR(14)", yours, ref, results)
    except Exception as e:
        print(f"  ATR(14)              ERROR: {e}")

    try:
        yours, ref = validate_historical_volatility(df)
        print_result("Hist Volatility(20)", yours, ref, results)
    except Exception as e:
        print(f"  Hist Volatility      ERROR: {e}")

    # --- VOLUME INDICATORS ---
    print(f"  {'-' * 71}")

    try:
        yours, ref = validate_obv(df)
        print_result("OBV", yours, ref, results)
    except Exception as e:
        print(f"  OBV                  ERROR: {e}")

    return results


def main():
    print("\n" + "=" * 75)
    print("  INDICATOR VALIDATION REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Tolerance: {TOLERANCE_PCT}%")
    print(f"  Reference: pandas_ta library")
    print("=" * 75)

    print("\nFetching data for test tickers...")
    data = fetch_test_data(TEST_TICKERS)
    print(f"Loaded data for: {list(data.keys())}")

    total_pass = 0
    total_fail = 0

    for ticker, df in data.items():
        try:
            results = validate_ticker(ticker, df)
            total_pass += results['pass']
            total_fail += results['fail']
        except Exception as e:
            print(f"\n  CRITICAL ERROR validating {ticker}: {e}")

    # Summary
    total = total_pass + total_fail
    pass_rate = (total_pass / total * 100) if total > 0 else 0

    print(f"\n{'=' * 75}")
    print("  SUMMARY")
    print(f"{'=' * 75}")
    print(f"  Total Tests:  {total}")
    print(f"  Passed:       {total_pass} ✓")
    print(f"  Failed:       {total_fail} ✗")
    print(f"  Pass Rate:    {pass_rate:.1f}%")
    print(f"{'=' * 75}")

    if total_fail > 0:
        print("\n  ⚠ FAILURES DETECTED")
        print("  Common causes of differences:")
        print("    - RSI: SMA vs EMA (Wilder's) smoothing method")
        print("    - EMA: Different seeding (first N values)")
        print("    - ATR: Wilder's smoothing vs standard EMA")
        print("    - Stochastic: Different smoothing for %D")
        print("\n  Review failures above. Differences under 5% are often")
        print("  acceptable due to implementation variations.\n")
    else:
        print("\n  ✓ All indicators validated successfully!\n")


if __name__ == "__main__":
    main()