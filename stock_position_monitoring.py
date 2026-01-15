"""
Stock Position Monitoring - Structure-Anchored Trailing Exit System (V5)

CORE PHILOSOPHY: Kill switch proved highly effective. Tighten hard stop and
activate kill switch earlier to catch failures before they become large losses.

EXIT SYSTEM:
1. Initial Stop: Tighter of structure-based OR ATR-based (max 5% from entry)
2. Trailing Stop: Chandelier Exit (highest close - 2.5×ATR after profit lock)
3. Kill Switch: Momentum fade detection after 3 days held (with restrictive override)
4. Profit Take: Sell 50% at +2R
5. Dead Money Filter: 5 consecutive closes below EMA50
6. Hard Stop: 6% max loss (circuit breaker)

PHASES:
- Entry: Stop = tighter of (lowest low - 0.5%) or (entry - 3.0×ATR)
- Breakeven Lock: When price reaches +2.0×ATR, stop moves to entry
- Profit Lock: When price reaches +3.0×ATR, stop moves to entry + 1.25×ATR
- Trailing: After profit lock, Chandelier trailing (peak - 2.5×ATR)

KILL SWITCH (Momentum Fade Detection):
- Activates after: 3 days holding period
- Momentum Fade signals (ANY triggers):
  * MACD histogram divergence (price higher high, histogram lower high)
  * RSI(5) break (higher high then breaks swing low)
  * EMA slope flattening (EMA5/EMA8 slopes drop 50%+)
  * ATR+Volume contraction (both declining 3+ bars)
- Price Confirmation required (ANY triggers):
  * Close below EMA(8) or EMA(10)
  * Break previous 2-bar swing low
- Strength Override (RESTRICTIVE - all required):
  * Position must be at least +1R profitable
  * MUST be above EMA50
  * MUST have bullish EMA stack OR outperforming SPY by 2%+
  * Score >= 3/6 on strength signals
- EXIT = Momentum Fade + Price Confirmation - Strength Override

V5 CHANGES (from V4):
- Hard stop: 8% → 6% (cap catastrophic losses)
- Kill switch activation: 5 days → 3 days (catch failures earlier)
- Max initial stop: 7% → 5% (must be inside hard stop)

V5.1 CHANGES:
- Added kill switch strength override with RESTRICTIVE requirements:
  * Profit requirement: +1R minimum (positions below this always trigger kill switch)
  * Mandatory signals: above EMA50 + (bullish stack OR RS > 2%)
  * Tightened criteria: ADX > 30, RS lookback 20 bars, RS outperformance 2%+
"""

import stock_indicators
from config import Config
import stock_position_sizing
import account_broker_data


class ExitConfig:
    """Structure-Anchored Trailing Exit Configuration - V5

    V5 Philosophy: Kill switch proved highly effective (+$87K in V4).
    Tighten hard stop and activate kill switch earlier to reduce losses.

    Key insight: Hard stop triggers when initial stop is outside hard stop.
    Solution: Ensure initial stop (5%) is always inside hard stop (6%).
    """

    # Structure-based initial stop - V5: TIGHTENED to stay inside hard stop
    STRUCTURE_LOOKBACK_BARS = 10  # Bars for lowest low
    STRUCTURE_BUFFER_PCT = 0.5  # Buffer below lowest low (%)
    MAX_INITIAL_STOP_PCT = 5.0  # V5: 5% (was 7% in V4) - must be inside hard stop

    # ATR-based stop fallback - V4: LOOSENED
    ATR_STOP_MULTIPLIER = 3.0  # V4: 3.0×ATR (was 2.5 in V2/V3)
    USE_TIGHTER_OF_STRUCTURE_OR_ATR = True  # Keep safety net

    # ATR settings
    ATR_PERIOD = 10  # Faster ATR for adaptation

    # Chandelier trailing
    CHANDELIER_MULTIPLIER = 3.0  # Peak - (3.0 × ATR)

    # Phase transitions - V4: LOOSENED back toward V1
    BREAKEVEN_LOCK_ATR = 2.0  # V4: 2.0 (was 1.5 in V2/V3, 2.0 in V1)
    PROFIT_LOCK_ATR = 3.5  # V4: 3.0 (was 2.5 in V2/V3, 3.5 in V1)
    PROFIT_LOCK_STOP_ATR = 1.5  # V4: 1.25 (was 1.0 in V2/V3, 1.5 in V1)

    # Trailing multiplier after profit lock
    TRAILING_ATR_MULT = 2.5  # Keep at 2.5 (working well in V3)

    # Profit taking
    PROFIT_TAKE_R_MULTIPLE = 2.0  # Keep at 2R (working well)
    PROFIT_TAKE_PCT = 50.0  # Sell 50% at profit target

    # Dead money filter
    DEAD_MONEY_EMA_PERIOD = 50  # EMA period for dead money check
    DEAD_MONEY_BARS_BELOW = 5  # Consecutive bars below EMA to trigger
    DEAD_MONEY_MAX_LOSS_R = 1.0  # Only trigger if loss < 1R

    # Hard stop (circuit breaker) - V5: TIGHTENED
    HARD_STOP_PCT = 6.0  # V5: 6% (was 8% V4, 7% V3, 6% V2)

    # Regime adjustment
    REGIME_TIGHTENING_PCT = 20.0  # V4: Back to 20% (was 25% in V2/V3)

    # Remnant cleanup
    MIN_REMNANT_SHARES = 5
    MIN_REMNANT_VALUE = 300.0

    # Kill Switch - Momentum Fade Detection
    KILL_SWITCH_ENABLED = True
    KILL_SWITCH_MIN_HOLD_DAYS = 3  # V5: 3 days (was 5 in V4) - catch failures earlier

    # Kill Switch Strength Override - V5.1 (RESTRICTIVE)
    KILL_SWITCH_STRENGTH_OVERRIDE_ENABLED = False
    KILL_SWITCH_STRENGTH_THRESHOLD = 6  # Minimum score to override kill switch (0-6)

    # Tightened criteria
    KILL_SWITCH_ADX_THRESHOLD = 30  # Was 25 - require stronger trend
    KILL_SWITCH_RS_LOOKBACK = 20  # Was 10 - longer-term outperformance
    KILL_SWITCH_RS_MIN_OUTPERFORM = 2.0  # Must beat SPY by 2%+, not just any positive

    # Profit requirement
    KILL_SWITCH_OVERRIDE_MIN_PROFIT_R = 1.0  # Must be at least +1R to override


class PositionMonitor:
    """Tracks position state for structure-anchored trailing exits"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}

    def track_position(self, ticker, entry_date, entry_signal='unknown', entry_score=0,
                       is_addon=False, entry_price=None, raw_df=None, atr=None):
        """
        Initialize or update position tracking with structure-based stop

        Args:
            ticker: Stock symbol
            entry_date: Entry datetime
            entry_signal: Entry signal name
            entry_score: Entry quality score
            is_addon: True if adding to existing position
            entry_price: Entry price
            raw_df: DataFrame with OHLC for structure calculation
            atr: ATR value for R calculation
        """
        current_price = entry_price if entry_price and entry_price > 0 else self._get_current_price(ticker)

        if ticker not in self.positions_metadata:
            # Calculate structure-based initial stop (uses tighter of structure or ATR)
            initial_stop = self._calculate_structure_stop(current_price, raw_df, atr)

            # Calculate R (initial risk)
            R = current_price - initial_stop if initial_stop > 0 else current_price * 0.05

            # Store ATR at entry for reference
            entry_atr = atr if atr and atr > 0 else R / 2.5  # Fallback estimate

            self.positions_metadata[ticker] = {
                'entry_date': entry_date,
                'entry_signal': entry_signal,
                'entry_score': entry_score,
                'entry_price': current_price,
                'initial_stop': initial_stop,
                'R': R,
                'entry_atr': entry_atr,
                'highest_close': current_price,
                'current_stop': initial_stop,
                'phase': 'entry',  # entry, breakeven, profit_lock, trailing
                'partial_taken': False,
                'bars_below_ema50': 0,
                'add_count': 0
            }
        elif is_addon:
            # Add-on: preserve phase state, increment add count
            self.positions_metadata[ticker]['add_count'] = self.positions_metadata[ticker].get('add_count', 0) + 1
            # Entry price will be updated by broker's avg_entry_price

    def _calculate_structure_stop(self, entry_price, raw_df, atr=None):
        """
        Calculate structure-based initial stop

        Stop = Lowest low of past 10 bars minus 0.5% buffer
        Also calculates ATR-based stop and uses the TIGHTER of the two
        Capped at MAX_INITIAL_STOP_PCT from entry
        """
        if entry_price <= 0:
            return entry_price * 0.95

        # Calculate structure-based stop
        structure_stop = None
        if raw_df is not None and len(raw_df) >= ExitConfig.STRUCTURE_LOOKBACK_BARS:
            lookback_lows = raw_df['low'].tail(ExitConfig.STRUCTURE_LOOKBACK_BARS)
            lowest_low = lookback_lows.min()
            structure_stop = lowest_low * (1 - ExitConfig.STRUCTURE_BUFFER_PCT / 100)

        # Calculate ATR-based stop
        atr_stop = None
        if atr and atr > 0:
            atr_stop = entry_price - (ExitConfig.ATR_STOP_MULTIPLIER * atr)
        elif raw_df is not None and len(raw_df) >= 14:
            # Calculate ATR if not provided
            calculated_atr = stock_indicators.get_atr(raw_df, period=ExitConfig.ATR_PERIOD)
            if calculated_atr and calculated_atr > 0:
                atr_stop = entry_price - (ExitConfig.ATR_STOP_MULTIPLIER * calculated_atr)

        # Determine which stop to use
        if ExitConfig.USE_TIGHTER_OF_STRUCTURE_OR_ATR and structure_stop and atr_stop:
            # Use the HIGHER (tighter) of the two stops
            initial_stop = max(structure_stop, atr_stop)
        elif structure_stop:
            initial_stop = structure_stop
        elif atr_stop:
            initial_stop = atr_stop
        else:
            # Fallback: 4% stop
            initial_stop = entry_price * 0.96

        # Cap at maximum stop distance
        min_stop = entry_price * (1 - ExitConfig.MAX_INITIAL_STOP_PCT / 100)
        initial_stop = max(initial_stop, min_stop)

        # Ensure stop is below entry
        if initial_stop >= entry_price:
            initial_stop = entry_price * 0.96

        return initial_stop

    def update_position_state(self, ticker, current_close, current_atr, ema50, regime_bearish=False):
        """
        Update position state each bar

        Updates highest_close, phase transitions, current_stop, bars_below_ema50
        """
        if ticker not in self.positions_metadata:
            return

        meta = self.positions_metadata[ticker]
        entry_price = meta['entry_price']
        R = meta['R']
        entry_atr = meta['entry_atr']

        # Update highest close
        if current_close > meta['highest_close']:
            meta['highest_close'] = current_close

        # Calculate current gain in ATR terms
        gain_atr = (current_close - entry_price) / entry_atr if entry_atr > 0 else 0

        # Apply regime tightening if bearish
        regime_mult = 1.0 - (ExitConfig.REGIME_TIGHTENING_PCT / 100) if regime_bearish else 1.0

        # Phase transitions (only advance, never retreat)
        current_phase = meta['phase']

        if current_phase == 'entry':
            if gain_atr >= ExitConfig.BREAKEVEN_LOCK_ATR:
                meta['phase'] = 'breakeven'
                meta['current_stop'] = entry_price  # Move to breakeven

        if current_phase in ['entry', 'breakeven']:
            if gain_atr >= ExitConfig.PROFIT_LOCK_ATR:
                meta['phase'] = 'profit_lock'
                profit_lock_stop = entry_price + (ExitConfig.PROFIT_LOCK_STOP_ATR * entry_atr)
                meta['current_stop'] = max(meta['current_stop'], profit_lock_stop)

        # Trailing stop calculation (after profit lock)
        if meta['phase'] == 'profit_lock':
            # Use current ATR for trailing, with regime adjustment
            trailing_mult = ExitConfig.TRAILING_ATR_MULT * regime_mult
            chandelier_stop = meta['highest_close'] - (trailing_mult * current_atr)

            # Stop only moves up
            if chandelier_stop > meta['current_stop']:
                meta['current_stop'] = chandelier_stop
                meta['phase'] = 'trailing'

        if meta['phase'] == 'trailing':
            trailing_mult = ExitConfig.TRAILING_ATR_MULT * regime_mult
            chandelier_stop = meta['highest_close'] - (trailing_mult * current_atr)
            meta['current_stop'] = max(meta['current_stop'], chandelier_stop)

        # Update bars below EMA50 counter
        if ema50 and current_close < ema50:
            meta['bars_below_ema50'] = meta.get('bars_below_ema50', 0) + 1
        else:
            meta['bars_below_ema50'] = 0

    def record_partial_taken(self, ticker):
        """Record that partial profit was taken"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['partial_taken'] = True

    def clean_position_metadata(self, ticker):
        """Remove position metadata after full exit"""
        if ticker in self.positions_metadata:
            del self.positions_metadata[ticker]

    def get_position_metadata(self, ticker):
        """Get position metadata"""
        return self.positions_metadata.get(ticker, None)

    def _get_current_price(self, ticker):
        """Get current price from strategy"""
        try:
            return self.strategy.get_last_price(ticker)
        except:
            return 0


# =============================================================================
# EXIT CONDITION CHECKS
# =============================================================================

def check_hard_stop(entry_price, current_price):
    """
    Check hard stop (6% max loss circuit breaker)

    This is the absolute backstop - no exceptions.
    """
    if entry_price <= 0 or current_price <= 0:
        return None

    pnl_pct = ((current_price - entry_price) / entry_price) * 100

    if pnl_pct <= -ExitConfig.HARD_STOP_PCT:
        return {
            'type': 'full_exit',
            'reason': 'hard_stop',
            'sell_pct': 100.0,
            'message': f'HARD STOP: {pnl_pct:.1f}% loss (limit: -{ExitConfig.HARD_STOP_PCT}%)'
        }

    return None


def check_trailing_stop(current_stop, current_close, phase):
    """
    Check if trailing/structure stop hit

    Uses close price, not intraday low, to filter noise.
    """
    if not current_stop or current_stop <= 0:
        return None

    if current_close <= current_stop:
        reason_map = {
            'entry': 'structure_stop',
            'breakeven': 'breakeven_stop',
            'profit_lock': 'profit_lock_stop',
            'trailing': 'chandelier_stop'
        }
        reason = reason_map.get(phase, 'trailing_stop')

        return {
            'type': 'full_exit',
            'reason': reason,
            'sell_pct': 100.0,
            'message': f'{reason.upper()}: Close ${current_close:.2f} <= Stop ${current_stop:.2f}'
        }

    return None


def check_dead_money(bars_below_ema50, pnl_pct, R, entry_price, current_price):
    """
    Check dead money filter

    Exit if:
    - 5+ consecutive closes below EMA50
    - Loss is less than 1R (not already deep in the hole)
    """
    if bars_below_ema50 < ExitConfig.DEAD_MONEY_BARS_BELOW:
        return None

    # Calculate loss in R terms
    loss_dollars = entry_price - current_price
    loss_R = loss_dollars / R if R > 0 else 0

    # Only trigger if not already at a large loss
    if loss_R <= ExitConfig.DEAD_MONEY_MAX_LOSS_R:
        return {
            'type': 'full_exit',
            'reason': 'dead_money',
            'sell_pct': 100.0,
            'message': f'DEAD MONEY: {bars_below_ema50} bars below EMA50, {pnl_pct:+.1f}%'
        }

    return None


def check_profit_take(entry_price, current_price, R, partial_taken):
    """
    Check profit take at 2R

    Sells 50% of position at 2R profit.
    Only triggers once per position.
    """
    if partial_taken:
        return None

    if R <= 0 or entry_price <= 0:
        return None

    gain = current_price - entry_price
    gain_R = gain / R

    if gain_R >= ExitConfig.PROFIT_TAKE_R_MULTIPLE:
        pnl_pct = (gain / entry_price) * 100
        return {
            'type': 'profit_take',
            'reason': 'profit_take_2R',
            'sell_pct': ExitConfig.PROFIT_TAKE_PCT,
            'message': f'PROFIT TAKE: +{gain_R:.1f}R (+{pnl_pct:.1f}%)'
        }

    return None


def check_strength_override(raw_df, indicators, spy_df=None, entry_price=0, current_price=0, R=0):
    """
    Check if position has sufficient trend strength to override kill switch.

    RESTRICTIVE VERSION - Requires ALL of:
    1. Position must be at least +1R profitable
    2. Mandatory signals (above EMA50 + bullish stack OR outperforming SPY by 2%+)
    3. Minimum score threshold (3/6)

    Signals checked (each worth 1 point):
    1. Price above EMA21
    2. Price above EMA50 (MANDATORY)
    3. Bullish EMA stack (EMA8 > EMA21 > EMA50)
    4. ADX > 30 (strong trend)
    5. Outperforming SPY by 2%+ over 20 bars
    6. Higher lows intact (price structure bullish)

    Args:
        raw_df: DataFrame with OHLC data for the stock
        indicators: Dict with current indicators (from all_stock_data)
        spy_df: DataFrame with SPY OHLC data (optional, for RS calc)
        entry_price: Position entry price (for profit check)
        current_price: Current price (for profit check)
        R: Position R value (for profit check)

    Returns:
        dict: {
            'override': bool,
            'score': int (0-6),
            'signals': list of triggered signal names,
            'details': dict with signal details,
            'rejection_reason': str or None
        }
    """
    result = {
        'override': False,
        'score': 0,
        'signals': [],
        'details': {},
        'rejection_reason': None
    }

    if not ExitConfig.KILL_SWITCH_STRENGTH_OVERRIDE_ENABLED:
        result['rejection_reason'] = 'override_disabled'
        return result

    if raw_df is None or len(raw_df) < 50:
        result['rejection_reason'] = 'insufficient_data'
        return result

    # =========================================================================
    # Profit Requirement Check (FIRST - fail fast)
    # Must be at least +1R to even consider override
    # =========================================================================
    if entry_price > 0 and current_price > 0 and R > 0:
        gain = current_price - entry_price
        gain_R = gain / R

        if gain_R < ExitConfig.KILL_SWITCH_OVERRIDE_MIN_PROFIT_R:
            result[
                'rejection_reason'] = f'insufficient_profit ({gain_R:.1f}R < {ExitConfig.KILL_SWITCH_OVERRIDE_MIN_PROFIT_R}R)'
            result['details']['gain_R'] = gain_R
            return result

        result['details']['gain_R'] = gain_R
    else:
        # If we can't calculate profit, don't allow override
        result['rejection_reason'] = 'cannot_calculate_profit'
        return result

    score = 0
    signals = []
    details = result['details']

    current_close = indicators.get('close', 0)
    ema8 = indicators.get('ema8', 0)
    ema21 = indicators.get('ema20', 0)  # Using ema20 as proxy for ema21
    ema50 = indicators.get('ema50', 0)
    adx = indicators.get('adx', 0)

    # -------------------------------------------------------------------------
    # Signal 1: Price above EMA21
    # -------------------------------------------------------------------------
    above_ema21 = current_close > 0 and ema21 > 0 and current_close > ema21
    if above_ema21:
        score += 1
        signals.append('above_ema21')
    details['above_ema21'] = above_ema21

    # -------------------------------------------------------------------------
    # Signal 2: Price above EMA50 (MANDATORY)
    # -------------------------------------------------------------------------
    above_ema50 = current_close > 0 and ema50 > 0 and current_close > ema50
    if above_ema50:
        score += 1
        signals.append('above_ema50')
    details['above_ema50'] = above_ema50

    # -------------------------------------------------------------------------
    # Signal 3: Bullish EMA stack (EMA8 > EMA21 > EMA50)
    # -------------------------------------------------------------------------
    bullish_stack = False
    if ema8 > 0 and ema21 > 0 and ema50 > 0:
        if ema8 > ema21 > ema50:
            bullish_stack = True
            score += 1
            signals.append('bullish_ema_stack')
    details['bullish_ema_stack'] = bullish_stack

    # -------------------------------------------------------------------------
    # Signal 4: ADX > 30 (strong trend) - TIGHTENED from 25
    # -------------------------------------------------------------------------
    strong_adx = adx > ExitConfig.KILL_SWITCH_ADX_THRESHOLD
    if strong_adx:
        score += 1
        signals.append('strong_trend_adx')
    details['adx'] = adx
    details['strong_trend_adx'] = strong_adx

    # -------------------------------------------------------------------------
    # Signal 5: Outperforming SPY by 2%+ over 20 bars - TIGHTENED
    # -------------------------------------------------------------------------
    outperforming_spy = False
    if spy_df is not None and len(spy_df) >= ExitConfig.KILL_SWITCH_RS_LOOKBACK + 1:
        rs_result = stock_indicators.get_relative_strength(
            raw_df, spy_df,
            lookback=ExitConfig.KILL_SWITCH_RS_LOOKBACK
        )
        # Must outperform by minimum threshold, not just any positive amount
        outperformance = rs_result.get('outperformance', 0)
        if outperformance >= ExitConfig.KILL_SWITCH_RS_MIN_OUTPERFORM:
            outperforming_spy = True
            score += 1
            signals.append('outperforming_spy')
        details['relative_strength'] = rs_result
        details['rs_outperformance'] = outperformance
    else:
        details['relative_strength'] = {'outperforming': False, 'outperformance': 0}
        details['rs_outperformance'] = 0

    # -------------------------------------------------------------------------
    # Signal 6: Higher lows intact
    # -------------------------------------------------------------------------
    higher_lows_ok = False
    swing_result = stock_indicators.find_swing_lows(raw_df, lookback=10, swing_size=2)
    if swing_result.get('higher_lows', False) and swing_result.get('current_above_last_swing', False):
        higher_lows_ok = True
        score += 1
        signals.append('higher_lows_intact')
    details['swing_analysis'] = swing_result
    details['higher_lows_intact'] = higher_lows_ok

    # =========================================================================
    # Mandatory Signal Check
    # MUST be above EMA50 AND (bullish stack OR outperforming SPY by 2%+)
    # =========================================================================
    mandatory_met = above_ema50 and (bullish_stack or outperforming_spy)
    details['mandatory_signals_met'] = mandatory_met

    if not mandatory_met:
        result['score'] = score
        result['signals'] = signals
        result['details'] = details

        missing = []
        if not above_ema50:
            missing.append('above_ema50')
        if not bullish_stack and not outperforming_spy:
            missing.append('bullish_stack OR outperforming_spy')

        result['rejection_reason'] = f'mandatory_signals_missing ({", ".join(missing)})'
        return result

    # =========================================================================
    # Final Score Check
    # =========================================================================
    override = score >= ExitConfig.KILL_SWITCH_STRENGTH_THRESHOLD

    result['override'] = override
    result['score'] = score
    result['signals'] = signals
    result['details'] = details

    if not override:
        result['rejection_reason'] = f'score_below_threshold ({score}/{ExitConfig.KILL_SWITCH_STRENGTH_THRESHOLD})'

    return result


def check_kill_switch(raw_df, indicators, entry_date, current_date, spy_df=None, entry_price=0, current_price=0, R=0):
    """
    Check Kill Switch: Momentum Fade + Price Confirmation - Strength Override

    Only active after minimum holding period (default 3 days).
    Detects momentum fade via multiple signals, then confirms with price action.

    Strength Override: If position is +1R profitable AND has strong trend signals,
    kill switch is overridden.

    Args:
        raw_df: DataFrame with OHLC data
        indicators: Dict with current indicators
        entry_date: Position entry date
        current_date: Current date
        spy_df: DataFrame with SPY data (optional, for relative strength)
        entry_price: Position entry price (for profit check)
        current_price: Current price (for profit check)
        R: Position R value (for profit check)

    Returns:
        dict or None: Kill switch exit signal
    """
    if not ExitConfig.KILL_SWITCH_ENABLED:
        return None

    # Check if minimum hold period met
    if entry_date is None or current_date is None:
        return None

    try:
        # Normalize dates for comparison
        entry = entry_date.replace(tzinfo=None) if hasattr(entry_date, 'tzinfo') and entry_date.tzinfo else entry_date
        current = current_date.replace(tzinfo=None) if hasattr(current_date,
                                                               'tzinfo') and current_date.tzinfo else current_date
        days_held = (current - entry).days

        if days_held < ExitConfig.KILL_SWITCH_MIN_HOLD_DAYS:
            return None
    except:
        return None

    if raw_df is None or len(raw_df) < 10:
        return None

    # Check momentum fade (from stock_indicators)
    fade_result = stock_indicators.detect_momentum_fade(raw_df, indicators)

    if not fade_result.get('fade_detected', False):
        return None

    # Check price confirmation (from stock_indicators)
    confirm_result = stock_indicators.detect_price_confirmation(raw_df, indicators)

    if not confirm_result.get('confirmed', False):
        return None

    # =========================================================================
    # Check strength override BEFORE triggering exit
    # Requires: +1R profit, above EMA50, (bullish stack OR RS > 2%), score >= 3
    # =========================================================================
    strength_result = check_strength_override(
        raw_df, indicators, spy_df,
        entry_price=entry_price,
        current_price=current_price,
        R=R
    )

    if strength_result.get('override', False):
        # Strength signals are strong enough - suppress kill switch
        strength_signals = ', '.join(strength_result.get('signals', []))
        gain_R = strength_result.get('details', {}).get('gain_R', 0)
        print(
            f"[KILL SWITCH OVERRIDE] +{gain_R:.1f}R | Score {strength_result['score']}/{ExitConfig.KILL_SWITCH_STRENGTH_THRESHOLD} | Signals: {strength_signals}")
        return None

    # =========================================================================
    # Proceed with kill switch exit
    # =========================================================================
    fade_signals = ', '.join(fade_result.get('signals', []))
    confirm_reason = confirm_result.get('reason', 'price_break')

    # Log why override was rejected (for debugging)
    rejection = strength_result.get('rejection_reason', 'unknown')
    print(f"[KILL SWITCH] Override rejected: {rejection}")

    return {
        'type': 'full_exit',
        'reason': 'kill_switch',
        'sell_pct': 100.0,
        'message': f'KILL SWITCH: Fade [{fade_signals}] + Confirm [{confirm_reason}]'
    }


def check_remnant_position(remaining_shares, current_price):
    """
    Check for remnant position cleanup
    """
    remaining_value = remaining_shares * current_price

    if remaining_shares < ExitConfig.MIN_REMNANT_SHARES:
        return {
            'type': 'full_exit',
            'reason': 'remnant_cleanup',
            'sell_pct': 100.0,
            'message': f'Remnant cleanup: {remaining_shares} shares'
        }

    if remaining_value < ExitConfig.MIN_REMNANT_VALUE:
        return {
            'type': 'full_exit',
            'reason': 'remnant_cleanup',
            'sell_pct': 100.0,
            'message': f'Remnant cleanup: ${remaining_value:.0f}'
        }

    return None


# =============================================================================
# MAIN POSITION CHECKING FUNCTION
# =============================================================================

def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """
    Check all positions for exit signals

    Priority order:
    1. Hard Stop (6% max loss)
    2. Trailing/Structure Stop
    3. Kill Switch (momentum fade after 3 days)
    4. Dead Money Filter
    5. Profit Take (2R)
    6. Remnant Cleanup (handled in execution)

    Args:
        strategy: Lumibot Strategy instance
        current_date: Current datetime
        all_stock_data: Dict of {ticker: {'indicators': {...}, 'raw': DataFrame}}
        position_monitor: PositionMonitor instance

    Returns:
        list: Exit orders to execute
    """
    exit_orders = []
    positions = strategy.get_positions()

    # Check if in bearish regime (SPY < 50 SMA)
    regime_bearish = False
    spy_df = None
    if 'SPY' in all_stock_data:
        spy_data = all_stock_data['SPY']['indicators']
        spy_close = spy_data.get('close', 0)
        spy_sma50 = spy_data.get('sma50', 0)
        if spy_close > 0 and spy_sma50 > 0:
            regime_bearish = spy_close < spy_sma50
        # Get SPY raw data for relative strength calculation
        spy_df = all_stock_data['SPY'].get('raw')

    for position in positions:
        ticker = position.symbol

        if ticker in account_broker_data.SKIP_SYMBOLS:
            continue

        broker_quantity = account_broker_data.get_position_quantity(position, ticker)
        if broker_quantity <= 0:
            continue

        # Get price data
        if ticker not in all_stock_data:
            continue

        data = all_stock_data[ticker]['indicators']
        raw_df = all_stock_data[ticker].get('raw')

        # Yesterday's close - used for signal-based exits
        signal_price = data.get('close', 0)

        # Real-time price - used for hard stop and execution
        try:
            current_price = strategy.get_last_price(ticker)
        except:
            current_price = 0

        # Fallback to indicator data if get_last_price fails
        if current_price <= 0:
            current_price = data.get('close', 0)

        if current_price <= 0:
            continue

        # Get ATR (use ATR10 if available, else ATR14)
        current_atr = stock_indicators.get_atr(raw_df, period=ExitConfig.ATR_PERIOD) if raw_df is not None else 0
        if current_atr <= 0:
            current_atr = data.get('atr_14', 0)

        # Get EMA50
        ema50 = data.get('ema50', 0)

        # Get metadata
        metadata = position_monitor.get_position_metadata(ticker)
        if not metadata:
            # Orphan position - skip (will be adopted by sync)
            continue

        # Get entry price - CRITICAL: Handle backtesting vs live trading differently
        broker_entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)

        if Config.BACKTESTING:
            # In backtesting, use the stored price (matches split-adjusted data feed)
            # Lumibot's position.avg_entry_price can be unreliable in backtests
            stored_entry = metadata.get('entry_price', 0)
            entry_price = stored_entry if stored_entry and stored_entry > 0 else broker_entry_price
        else:
            # In live trading, broker handles splits and add-ons correctly
            entry_price = broker_entry_price if broker_entry_price > 0 else metadata.get('entry_price', 0)

        if entry_price <= 0:
            continue

        # Update position state
        position_monitor.update_position_state(
            ticker=ticker,
            current_close=current_price,
            current_atr=current_atr,
            ema50=ema50,
            regime_bearish=regime_bearish
        )

        # Refresh metadata after update
        metadata = position_monitor.get_position_metadata(ticker)

        # Calculate P&L
        pnl_dollars = (current_price - entry_price) * broker_quantity
        pnl_pct = ((current_price - entry_price) / entry_price * 100)

        # Use realtime price for actual P&L (what we'll get when we sell)
        # pnl_dollars = (realtime_price - entry_price) * broker_quantity
        # pnl_pct = ((realtime_price - entry_price) / entry_price * 100)

        # Get position state
        R = metadata.get('R', entry_price * 0.05)
        current_stop = metadata.get('current_stop', 0)
        phase = metadata.get('phase', 'entry')
        partial_taken = metadata.get('partial_taken', False)
        bars_below_ema50 = metadata.get('bars_below_ema50', 0)
        entry_date = metadata.get('entry_date')

        exit_signal = None

        # =====================================================================
        # PRIORITY 1: HARD STOP (6% max loss)
        # =====================================================================
        exit_signal = check_hard_stop(entry_price, current_price)
        # exit_signal = check_hard_stop(entry_price, realtime_price)

        # =====================================================================
        # PRIORITY 2: TRAILING/STRUCTURE STOP
        # =====================================================================
        if not exit_signal:
            exit_signal = check_trailing_stop(current_stop, current_price, phase)
            # exit_signal = check_trailing_stop(current_stop, signal_price, phase)

        # =====================================================================
        # PRIORITY 3: KILL SWITCH (momentum fade after 3 days)
        # With strength override - requires +1R profit + strong trend signals
        # =====================================================================
        if not exit_signal:
            exit_signal = check_kill_switch(
                raw_df, data, entry_date, current_date,
                spy_df=spy_df,
                entry_price=entry_price,
                current_price=current_price,
                R=R
            )

        # =====================================================================
        # PRIORITY 4: DEAD MONEY FILTER
        # =====================================================================
        if not exit_signal:
            exit_signal = check_dead_money(bars_below_ema50, pnl_pct, R, entry_price, current_price)
            # signal_pnl_pct = ((signal_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
            # exit_signal = check_dead_money(bars_below_ema50, signal_pnl_pct, R, entry_price, signal_price)

        # =====================================================================
        # PRIORITY 5: PROFIT TAKE (2R)
        # =====================================================================
        if not exit_signal:
            exit_signal = check_profit_take(entry_price, current_price, R, partial_taken)
            # exit_signal = check_profit_take(entry_price, signal_price, R, partial_taken)

        # =====================================================================
        # PACKAGE EXIT ORDER
        # =====================================================================
        if exit_signal:
            exit_signal['ticker'] = ticker
            exit_signal['broker_quantity'] = broker_quantity
            exit_signal['broker_entry_price'] = broker_entry_price
            exit_signal['entry_price'] = entry_price
            exit_signal['current_price'] = current_price
            exit_signal['pnl_dollars'] = pnl_dollars
            exit_signal['pnl_pct'] = pnl_pct
            exit_signal['entry_signal'] = metadata.get('entry_signal', 'pre_existing')
            exit_signal['entry_score'] = metadata.get('entry_score', 0)
            exit_signal['phase'] = phase
            exit_signal['R'] = R
            exit_orders.append(exit_signal)

    return exit_orders


# =============================================================================
# EXIT ORDER EXECUTION
# =============================================================================

def execute_exit_orders(strategy, exit_orders, current_date, position_monitor, profit_tracker,
                        summary=None, recovery_manager=None):
    """
    Execute exit orders

    Args:
        strategy: Lumibot Strategy instance
        exit_orders: List of exit order dicts
        current_date: Current datetime
        position_monitor: PositionMonitor instance
        profit_tracker: ProfitTracker instance
        summary: DailySummary instance (optional)
        recovery_manager: RecoveryModeManager instance (optional)
    """
    for order in exit_orders:
        ticker = order['ticker']
        exit_type = order['type']
        sell_pct = order['sell_pct']
        reason = order['reason']

        broker_quantity = order['broker_quantity']
        entry_price = order['entry_price']
        current_price = order['current_price']
        entry_signal = order.get('entry_signal', 'pre_existing')
        entry_score = order.get('entry_score', 0)
        phase = order.get('phase', 'entry')

        # Calculate sell quantity
        if exit_type == 'profit_take':
            sell_quantity = int(broker_quantity * (sell_pct / 100))
        else:
            sell_quantity = broker_quantity

        if sell_quantity <= 0 or entry_price <= 0:
            continue

        # Calculate P&L for this exit
        pnl_per_share = current_price - entry_price
        total_pnl = pnl_per_share * sell_quantity
        pnl_pct = (pnl_per_share / entry_price * 100)

        # =====================================================================
        # PROFIT TAKE: Partial exit (50%)
        # =====================================================================
        if exit_type == 'profit_take':
            remaining_shares = broker_quantity - sell_quantity

            # Check if remaining position too small
            remnant_check = check_remnant_position(remaining_shares, current_price)
            if remnant_check:
                # Too small - exit everything instead
                sell_quantity = broker_quantity
                total_pnl = pnl_per_share * sell_quantity
                reason = f"{reason}+remnant"

                if summary:
                    summary.add_exit(ticker, sell_quantity, total_pnl, pnl_pct, reason)

                profit_tracker.record_trade(
                    ticker=ticker,
                    quantity_sold=sell_quantity,
                    entry_price=entry_price,
                    exit_price=current_price,
                    exit_date=current_date,
                    entry_signal=entry_signal,
                    exit_signal=order,
                    entry_score=entry_score
                )

                position_monitor.clean_position_metadata(ticker)

                sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
                strategy.submit_order(sell_order)
                # if Config.BACKTESTING:
                #     stock_position_sizing.update_backtest_cash_for_sell(sell_quantity * current_price)
                continue

            # Normal profit take
            if summary:
                summary.add_profit_take(ticker, 1, sell_quantity, total_pnl, pnl_pct)

            # Record partial taken
            position_monitor.record_partial_taken(ticker)

            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)
            # if Config.BACKTESTING:
            #     stock_position_sizing.update_backtest_cash_for_sell(sell_quantity * current_price)

        # =====================================================================
        # FULL EXIT: Close entire position
        # =====================================================================
        else:
            if summary:
                summary.add_exit(ticker, sell_quantity, total_pnl, pnl_pct, reason)

            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            position_monitor.clean_position_metadata(ticker)

            # Record stop loss to regime detector
            is_stop_loss = any(kw in reason for kw in
                               ['stop', 'hard_stop', 'chandelier', 'structure', 'breakeven', 'dead_money',
                                'kill_switch'])
            # if is_stop_loss and hasattr(strategy, 'regime_detector'):
            #     strategy.regime_detector.record_stop_loss(current_date, ticker, pnl_pct)

            # Trigger recovery mode re-lock on stop loss
            if is_stop_loss and recovery_manager is not None:
                recovery_manager.trigger_relock(current_date, f"stop_loss_{ticker}")

            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)
            # if Config.BACKTESTING:
            #     stock_position_sizing.update_backtest_cash_for_sell(sell_quantity * current_price)
