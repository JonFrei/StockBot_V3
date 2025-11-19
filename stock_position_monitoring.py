"""
Adaptive Position Monitoring System - TIGHTENED EXIT STRATEGY

WITH OPTION 4: Progressive Growth Checkpoints (14d, 28d, 42d, 56d)
"""


# =============================================================================
# ADAPTIVE CONFIGURATION - TIGHTENED FOR BETTER PROTECTION
# =============================================================================

class AdaptiveExitConfig:
    """
        Dynamic exit parameters based on market conditions

    """

    # === STRONG CONDITIONS (Score 7-10) ===
    STRONG_EMERGENCY_STOP = -4.5
    STRONG_PROFIT_TARGET_1 = 15.0  # CHANGED from 12.0 (faster profit taking)
    STRONG_PROFIT_TARGET_1_SELL = 33.0  # CHANGED from 40.0 (lock in more gains)
    STRONG_PROFIT_TARGET_2 = 22.0  # CHANGED from 25.0 (faster)
    STRONG_PROFIT_TARGET_2_SELL = 33.0  # UNCHANGED
    STRONG_PROFIT_TARGET_3 = 30.0  # CHANGED from 40.0 (faster)
    STRONG_PROFIT_TARGET_3_SELL = 34.0  # UNCHANGED
    # Trailing Stop
    STRONG_TRAILING_STOP = 10.0  # CHANGED from 12.0 (tighter)
    STRONG_TRAILING_STOP_FINAL = 18.0  # CHANGED from 18.0 (tighter)

    # === NEUTRAL CONDITIONS (Score 4-6) ===
    NEUTRAL_EMERGENCY_STOP = -4.0
    NEUTRAL_PROFIT_TARGET_1 = 15.0  # CHANGED from 10.0 (faster)
    NEUTRAL_PROFIT_TARGET_1_SELL = 33.0  # CHANGED from 40.0 (lock in more)
    NEUTRAL_PROFIT_TARGET_2 = 20.0  # CHANGED from 20.0 (faster)
    NEUTRAL_PROFIT_TARGET_2_SELL = 33.0  # UNCHANGED
    NEUTRAL_PROFIT_TARGET_3 = 25.0  # CHANGED from 35.0 (faster)
    NEUTRAL_PROFIT_TARGET_3_SELL = 34.0  # UNCHANGED
    # Trailing Stop
    NEUTRAL_TRAILING_STOP = 10.0  # CHANGED from 10.0 (tighter)
    NEUTRAL_TRAILING_STOP_FINAL = 15.0  # CHANGED from 15.0 (tighter)

    # === WEAK CONDITIONS (Score 0-3) ===
    WEAK_EMERGENCY_STOP = -3.5
    WEAK_PROFIT_TARGET_1 = 10.0  # CHANGED from 8.0 (faster - get out quick)
    WEAK_PROFIT_TARGET_1_SELL = 33.0  # CHANGED from 40.0 (sell half immediately)
    WEAK_PROFIT_TARGET_2 = 12.0  # CHANGED from 18.0 (faster)
    WEAK_PROFIT_TARGET_2_SELL = 33.0  # UNCHANGED
    WEAK_PROFIT_TARGET_3 = 15.0  # CHANGED from 30.0 (faster)
    WEAK_PROFIT_TARGET_3_SELL = 34.0  # UNCHANGED
    # Trailing Stop
    WEAK_TRAILING_STOP = 7.0  # CHANGED from 6.0 (tighter)
    WEAK_TRAILING_STOP_FINAL = 12.0  # CHANGED from 12.0 (tighter)


# =============================================================================
# MARKET CONDITION SCORING
# =============================================================================

def calculate_market_condition_score(data):
    """
    Score market conditions from 0-10 based on multiple indicators

    Scoring Breakdown:
    - ADX (Trend Strength): 0-3 points
    - MACD (Momentum): 0-2.5 points
    - EMA Alignment (Structure): 0-2 points
    - Volume (Confirmation): 0-1.5 points
    - RSI (Not Overbought): 0-1 point

    Total: 0-10 points

    Args:
        data: Dictionary with technical indicators

    Returns:
        dict: {
            'score': float (0-10),
            'condition': str ('strong', 'neutral', 'weak'),
            'breakdown': dict (individual component scores)
        }
    """
    score = 0.0
    breakdown = {}

    # 1. ADX - Trend Strength (0-3 points)
    adx = data.get('adx', 0)
    if adx > 40:
        adx_score = 3.0
    elif adx > 30:
        adx_score = 2.0
    elif adx > 20:
        adx_score = 1.0
    else:
        adx_score = 0.0
    score += adx_score
    breakdown['adx'] = adx_score

    # 2. MACD - Momentum (0-2.5 points)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)

    if macd > macd_signal and macd_hist > 0:
        # Bullish and expanding
        macd_score = 2.5
    elif macd > macd_signal:
        # Bullish but not expanding
        macd_score = 1.5
    elif macd < macd_signal and macd_hist < 0:
        # Bearish crossover - penalize
        macd_score = 0.0
    else:
        macd_score = 0.5
    score += macd_score
    breakdown['macd'] = macd_score

    # 3. EMA Alignment (0-2 points)
    close = data.get('close', 0)
    ema8 = data.get('ema8', 0)
    ema12 = data.get('ema12', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)

    if close > ema8 > ema12 > ema20 > ema50:
        # Perfect bullish alignment
        ema_score = 2.0
    elif close > ema20 > ema50:
        # Decent structure
        ema_score = 1.0
    else:
        # Broken structure
        ema_score = 0.0
    score += ema_score
    breakdown['ema'] = ema_score

    # 4. Volume Confirmation (0-1.5 points)
    volume_ratio = data.get('volume_ratio', 0)
    if volume_ratio > 1.5:
        vol_score = 1.5
    elif volume_ratio > 1.0:
        vol_score = 0.75
    else:
        vol_score = 0.0
    score += vol_score
    breakdown['volume'] = vol_score

    # 5. RSI (0-1 point)
    rsi = data.get('rsi', 50)
    if 50 <= rsi <= 65:
        # Healthy bullish
        rsi_score = 1.0
    elif (40 <= rsi < 50) or (65 < rsi <= 75):
        # Acceptable
        rsi_score = 0.5
    else:
        # Extreme
        rsi_score = 0.0
    score += rsi_score
    breakdown['rsi'] = rsi_score

    # Determine condition
    if score >= 7.0:
        condition = 'strong'
    elif score >= 4.0:
        condition = 'neutral'
    else:
        condition = 'weak'

    return {
        'score': round(score, 2),
        'condition': condition,
        'breakdown': breakdown
    }


def get_adaptive_parameters(market_condition_score):
    """
    Get all adaptive parameters based on market condition score

    Returns exit parameters AND position sizing parameters

    Returns:
        dict with all adaptive parameters
    """
    condition = market_condition_score['condition']

    if condition == 'strong':
        return {
            # Exit parameters
            'emergency_stop_pct': AdaptiveExitConfig.STRONG_EMERGENCY_STOP,
            'profit_target_1_pct': AdaptiveExitConfig.STRONG_PROFIT_TARGET_1,
            'profit_target_1_sell': AdaptiveExitConfig.STRONG_PROFIT_TARGET_1_SELL,
            'profit_target_2_pct': AdaptiveExitConfig.STRONG_PROFIT_TARGET_2,
            'profit_target_2_sell': AdaptiveExitConfig.STRONG_PROFIT_TARGET_2_SELL,
            'profit_target_3_pct': AdaptiveExitConfig.STRONG_PROFIT_TARGET_3,
            'profit_target_3_sell': AdaptiveExitConfig.STRONG_PROFIT_TARGET_3_SELL,
            'trailing_stop_pct': AdaptiveExitConfig.STRONG_TRAILING_STOP,
            'trailing_stop_final_pct': AdaptiveExitConfig.STRONG_TRAILING_STOP_FINAL,
            # Position sizing
            'condition_label': '🟢 STRONG',
            'condition': 'strong'
        }
    elif condition == 'weak':
        return {
            # Exit parameters
            'emergency_stop_pct': AdaptiveExitConfig.WEAK_EMERGENCY_STOP,
            'profit_target_1_pct': AdaptiveExitConfig.WEAK_PROFIT_TARGET_1,
            'profit_target_1_sell': AdaptiveExitConfig.WEAK_PROFIT_TARGET_1_SELL,
            'profit_target_2_pct': AdaptiveExitConfig.WEAK_PROFIT_TARGET_2,
            'profit_target_2_sell': AdaptiveExitConfig.WEAK_PROFIT_TARGET_2_SELL,
            'profit_target_3_pct': AdaptiveExitConfig.WEAK_PROFIT_TARGET_3,
            'profit_target_3_sell': AdaptiveExitConfig.WEAK_PROFIT_TARGET_3_SELL,
            'trailing_stop_pct': AdaptiveExitConfig.WEAK_TRAILING_STOP,
            'trailing_stop_final_pct': AdaptiveExitConfig.WEAK_TRAILING_STOP_FINAL,
            # Position sizing
            'condition_label': '🔴 WEAK',
            'condition': 'weak'
        }
    else:  # neutral
        return {
            # Exit parameters
            'emergency_stop_pct': AdaptiveExitConfig.NEUTRAL_EMERGENCY_STOP,
            'profit_target_1_pct': AdaptiveExitConfig.NEUTRAL_PROFIT_TARGET_1,
            'profit_target_1_sell': AdaptiveExitConfig.NEUTRAL_PROFIT_TARGET_1_SELL,
            'profit_target_2_pct': AdaptiveExitConfig.NEUTRAL_PROFIT_TARGET_2,
            'profit_target_2_sell': AdaptiveExitConfig.NEUTRAL_PROFIT_TARGET_2_SELL,
            'profit_target_3_pct': AdaptiveExitConfig.NEUTRAL_PROFIT_TARGET_3,
            'profit_target_3_sell': AdaptiveExitConfig.NEUTRAL_PROFIT_TARGET_3_SELL,
            'trailing_stop_pct': AdaptiveExitConfig.NEUTRAL_TRAILING_STOP,
            'trailing_stop_final_pct': AdaptiveExitConfig.NEUTRAL_TRAILING_STOP_FINAL,
            # Position sizing
            'condition_label': '🟡 NEUTRAL',
            'condition': 'neutral'
        }


# =============================================================================
# POSITION METADATA TRACKER
# =============================================================================

class PositionMonitor:
    """Tracks position metadata and caches daily market conditions"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}  # {ticker: {...metadata...}}
        self.market_conditions_cache = {}  # {ticker: {date: str, score: dict, params: dict}}

    def track_position(self, ticker, entry_date, entry_signal='unknown', entry_score=0):
        """
        Record position metadata for monitoring

        SIMPLIFIED: No quantity or price tracking - get from broker
        ENHANCED: Now stores entry_score for analysis
        """
        if ticker not in self.positions_metadata:
            self.positions_metadata[ticker] = {
                'entry_date': entry_date,
                'entry_signal': entry_signal,
                'entry_score': entry_score,
                'highest_price': self._get_current_price(ticker),
                'profit_level_1_locked': False,
                'profit_level_2_locked': False,
                'profit_level_3_locked': False
            }
        else:
            # If adding to existing position, keep original entry signal and score
            # Update highest price to current
            self.positions_metadata[ticker]['highest_price'] = max(
                self.positions_metadata[ticker].get('highest_price', 0),
                self._get_current_price(ticker)
            )

    def update_highest_price(self, ticker, current_price):
        """Update highest price for trailing stop calculations"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['highest_price'] = max(
                self.positions_metadata[ticker]['highest_price'],
                current_price
            )

    def mark_profit_level_1_locked(self, ticker):
        """Mark that we took profit at level 1"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level_1_locked'] = True

    def mark_profit_level_2_locked(self, ticker):
        """Mark that we took profit at level 2"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level_2_locked'] = True

    def mark_profit_level_3_locked(self, ticker):
        """Mark that we took profit at level 3"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level_3_locked'] = True

    def clean_position_metadata(self, ticker):
        """Remove metadata when position is fully closed"""
        if ticker in self.positions_metadata:
            del self.positions_metadata[ticker]
        if ticker in self.market_conditions_cache:
            del self.market_conditions_cache[ticker]

    def get_position_metadata(self, ticker):
        """Get metadata for a ticker"""
        return self.positions_metadata.get(ticker, None)

    def _get_current_price(self, ticker):
        """Helper to get current price from broker"""
        try:
            return self.strategy.get_last_price(ticker)
        except:
            return 0

    def get_cached_market_conditions(self, ticker, current_date_str, data):
        """
        Get market conditions for ticker - cached daily

        Args:
            ticker: Stock symbol
            current_date_str: Current date as string (for cache key)
            data: Stock data dict (to calculate if not cached)

        Returns:
            dict: Adaptive parameters for this ticker
        """
        # Check cache
        if ticker in self.market_conditions_cache:
            cached = self.market_conditions_cache[ticker]
            if cached['date'] == current_date_str:
                return cached['params']

        # Not cached or old - calculate new
        market_score = calculate_market_condition_score(data)
        params = get_adaptive_parameters(market_score)

        # Cache it
        self.market_conditions_cache[ticker] = {
            'date': current_date_str,
            'score': market_score,
            'params': params
        }

        return params


# =============================================================================
# EXIT STRATEGY FUNCTIONS
# =============================================================================

def check_emergency_stop(pnl_pct, current_price, entry_price, stop_pct):
    """Adaptive emergency stop loss"""
    if pnl_pct <= stop_pct:
        return {
            'type': 'full_exit',
            'reason': 'emergency_stop',
            'sell_pct': 100.0,
            'message': f'🛑 Emergency Stop {stop_pct:.1f}%: ${current_price:.2f} (entry: ${entry_price:.2f})'
        }
    return None


def check_profit_taking_adaptive(pnl_pct, profit_target_1, profit_target_2, profit_target_3,
                                 sell_pct_1, sell_pct_2, sell_pct_3,
                                 profit_level_1_locked, profit_level_2_locked, profit_level_3_locked):
    """
    3-level adaptive profit taking with TIGHTENED targets
    """

    # Level 1
    if not profit_level_1_locked and pnl_pct >= profit_target_1:
        remaining_pct = 100.0 - sell_pct_1
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_1',
            'sell_pct': sell_pct_1,
            'profit_level': 1,
            'message': f'💰 Level 1 @ +{profit_target_1:.0f}%: Selling {sell_pct_1:.0f}%, keeping {remaining_pct:.0f}%'
        }

    # Level 2
    if profit_level_1_locked and not profit_level_2_locked and pnl_pct >= profit_target_2:
        remaining_pct = 100.0 - sell_pct_1 - sell_pct_2
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_2',
            'sell_pct': sell_pct_2,
            'profit_level': 2,
            'message': f'💰 Level 2 @ +{profit_target_2:.0f}%: Selling {sell_pct_2:.0f}%, keeping {remaining_pct:.0f}%'
        }

    # Level 3
    if profit_level_2_locked and not profit_level_3_locked and pnl_pct >= profit_target_3:
        remaining_pct = 100.0 - sell_pct_1 - sell_pct_2 - sell_pct_3
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_3',
            'sell_pct': sell_pct_3,
            'profit_level': 3,
            'message': f'🚀 Level 3 @ +{profit_target_3:.0f}%: Selling {sell_pct_3:.0f}%, trailing {remaining_pct:.0f}% (BIG WINNER!)'
        }

    return None


def check_trailing_stop(profit_level_2_locked, profit_level_3_locked, highest_price,
                        current_price, trail_pct, trail_pct_final, pnl_pct):
    """
    Adaptive trailing stop with wider stops after Level 3
    """
    if not profit_level_2_locked:
        return None

    # Use wider trailing stop after Level 3
    if profit_level_3_locked:
        active_trail_pct = trail_pct_final
        label = f"FINAL trail {trail_pct_final:.0f}%"
    else:
        active_trail_pct = trail_pct
        label = f"trail {trail_pct:.0f}%"

    drawdown_from_peak = ((current_price - highest_price) / highest_price * 100)

    if drawdown_from_peak <= -active_trail_pct:
        return {
            'type': 'full_exit',
            'reason': 'trailing_stop',
            'sell_pct': 100.0,
            'message': f'📉 Trail Stop ({label} from ${highest_price:.2f}): Exiting remaining position'
        }
    return None


def check_progressive_growth_milestones(position_monitor, ticker, current_date, data, pnl_pct):
    """
    OPTION 4: Progressive growth expectations at multiple checkpoints

    Exits positions that aren't meeting minimum growth thresholds + have weak momentum

    Checkpoints:
    - 14 days: Must be +4% or better (with weak momentum check)
    - 28 days: Must be +8% or better (with momentum check)
    - 42 days: Must be +12% or better (with momentum check)
    - 56 days: Must be +15% or better (stricter momentum check)

    Args:
        position_monitor: PositionMonitor instance
        ticker: Stock symbol
        current_date: Current date
        data: Stock technical data
        pnl_pct: Current P&L percentage

    Returns:
        dict with exit signal or None
    """
    metadata = position_monitor.get_position_metadata(ticker)
    if not metadata:
        return None

    entry_date = metadata['entry_date']
    days_held = (current_date - entry_date).days

    # Get technical indicators
    adx = data.get('adx', 0)
    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)

    # =========================================================================
    # CHECKPOINT 1: 14 Days - Early Underperformance Detection
    # =========================================================================
    if days_held >= 14 and days_held < 28:
        if pnl_pct < 4.0:  # Less than 4% after 2 weeks
            # Check if momentum is weak
            if adx < 20 or close < ema20:
                return {
                    'type': 'full_exit',
                    'reason': 'stagnation_14d',
                    'sell_pct': 100.0,
                    'message': f'⏰ 14d Checkpoint: +{pnl_pct:.1f}% (target: +4%) + Weak Momentum (ADX: {adx:.0f})'
                }

    # =========================================================================
    # CHECKPOINT 2: 28 Days - Mid-Term Growth Check
    # =========================================================================
    elif days_held >= 28 and days_held < 42:
        if pnl_pct < 8.0:  # Less than 8% after 4 weeks
            # Stricter momentum requirement
            if adx < 22 or macd <= macd_signal:
                return {
                    'type': 'full_exit',
                    'reason': 'stagnation_28d',
                    'sell_pct': 100.0,
                    'message': f'⏰ 28d Checkpoint: +{pnl_pct:.1f}% (target: +8%) + Weakening Momentum'
                }

    # =========================================================================
    # CHECKPOINT 3: 42 Days - Extended Hold Scrutiny
    # =========================================================================
    elif days_held >= 42 and days_held < 56:
        if pnl_pct < 12.0:  # Less than 12% after 6 weeks
            # Check for deteriorating trend
            if adx < 25 or close < ema20:
                return {
                    'type': 'full_exit',
                    'reason': 'stagnation_42d',
                    'sell_pct': 100.0,
                    'message': f'⏰ 42d Checkpoint: +{pnl_pct:.1f}% (target: +12%) + Deteriorating Trend'
                }

    # =========================================================================
    # CHECKPOINT 4: 56 Days - Final Pre-Max Check
    # =========================================================================
    elif days_held >= 56 and days_held < 60:
        if pnl_pct < 15.0:  # Less than 15% after 8 weeks
            # Strict momentum requirement at this stage
            if adx < 25 or macd <= macd_signal:
                return {
                    'type': 'full_exit',
                    'reason': 'stagnation_56d',
                    'sell_pct': 100.0,
                    'message': f'⏰ 56d Checkpoint: +{pnl_pct:.1f}% (target: +15%) + Insufficient Momentum'
                }

    return None


def check_max_holding_period(position_monitor, ticker, current_date, data, max_days=60):
    """
    Exit positions held longer than 60 days

    Still allows momentum exception:
    - If stock still has strong trend (ADX > 25, above EMAs, MACD bullish), let it ride
    - Otherwise exit to free up capital faster
    """
    metadata = position_monitor.get_position_metadata(ticker)
    if not metadata:
        return None

    entry_date = metadata['entry_date']
    days_held = (current_date - entry_date).days

    if days_held >= max_days:
        # Get momentum indicators
        adx = data.get('adx', 0)
        close = data.get('close', 0)
        ema20 = data.get('ema20', 0)
        ema50 = data.get('ema50', 0)
        macd = data.get('macd', 0)
        macd_signal = data.get('macd_signal', 0)

        # EXCEPTION: Strong trend = keep position (let trailing stop handle exit)
        if (close > ema20 > ema50 and
                adx > 25 and
                macd > macd_signal):
            return None  # Keep riding the trend

        # Weak/broken trend = exit
        return {
            'type': 'full_exit',
            'reason': 'max_holding_period',
            'sell_pct': 100.0,
            'message': f'⏰ Max Hold ({days_held}d) + Weakening Trend'
        }
    return None


# =============================================================================
# MAIN COORDINATOR FUNCTIONS
# =============================================================================

def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """
    TIGHTENED: Adaptive exit checking with faster profit targets and tighter stops

    WITH OPTION 4: Progressive growth checkpoints at 14d, 28d, 42d, 56d

    Exit Priority Order:
    1. Progressive growth checkpoints (14d, 28d, 42d, 56d) - NEW!
    2. Max holding period (60 days with momentum exception)
    3. Emergency stops (adaptive based on conditions)
    4. Profit taking level 1 (FASTER: 6-10%)
    5. Profit taking level 2 (FASTER: 15-22%)
    6. Profit taking level 3 (FASTER: 25-35%)
    7. Peak stop after Level 1 (NEW: -5% protection)
    8. Trailing stops (adaptive distance, wider after Level 3)
    """
    exit_orders = []

    positions = strategy.get_positions()
    if not positions:
        return exit_orders

    current_date_str = current_date.strftime('%Y-%m-%d')

    for position in positions:
        ticker = position.symbol

        # === GET DATA FROM BROKER (Source of Truth) ===
        broker_quantity = int(position.quantity)
        broker_entry_price = float(getattr(position, 'avg_entry_price', None) or
                                   getattr(position, 'avg_fill_price', 0))

        if ticker not in all_stock_data:
            continue

        data = all_stock_data[ticker]['indicators']
        current_price = data.get('close', 0)

        if current_price <= 0:
            continue

        # Ensure position is tracked
        metadata = position_monitor.get_position_metadata(ticker)
        if not metadata:
            position_monitor.track_position(ticker, current_date, 'pre_existing', entry_score=0)
            metadata = position_monitor.get_position_metadata(ticker)

        # Update highest price
        position_monitor.update_highest_price(ticker, current_price)

        # === GET ADAPTIVE PARAMETERS (Cached Daily) ===
        adaptive_params = position_monitor.get_cached_market_conditions(
            ticker, current_date_str, data
        )

        # === CALCULATE P&L USING BROKER DATA ===
        pnl_pct = ((current_price - broker_entry_price) / broker_entry_price * 100)
        pnl_dollars = (current_price - broker_entry_price) * broker_quantity

        # === CHECK EXIT CONDITIONS (Using Adaptive Parameters) ===
        exit_signal = None

        # 1. OPTION 4: Progressive growth checkpoints (14d, 28d, 42d, 56d) - NEW!
        exit_signal = check_progressive_growth_milestones(
            position_monitor=position_monitor,
            ticker=ticker,
            current_date=current_date,
            data=data,
            pnl_pct=pnl_pct
        )

        # 2. Max holding period (60 days with momentum exception)
        if not exit_signal:
            exit_signal = check_max_holding_period(
                position_monitor=position_monitor,
                ticker=ticker,
                current_date=current_date,
                data=data,
                max_days=60
            )

        # 3. Emergency stop (adaptive)
        if not exit_signal:
            exit_signal = check_emergency_stop(
                pnl_pct=pnl_pct,
                current_price=current_price,
                entry_price=broker_entry_price,
                stop_pct=adaptive_params['emergency_stop_pct']
            )

        # 4. Profit taking (3 LEVELS - TIGHTENED targets)
        if not exit_signal:
            exit_signal = check_profit_taking_adaptive(
                pnl_pct=pnl_pct,
                profit_target_1=adaptive_params['profit_target_1_pct'],
                profit_target_2=adaptive_params['profit_target_2_pct'],
                profit_target_3=adaptive_params['profit_target_3_pct'],
                sell_pct_1=adaptive_params['profit_target_1_sell'],
                sell_pct_2=adaptive_params['profit_target_2_sell'],
                sell_pct_3=adaptive_params['profit_target_3_sell'],
                profit_level_1_locked=metadata.get('profit_level_1_locked', False),
                profit_level_2_locked=metadata.get('profit_level_2_locked', False),
                profit_level_3_locked=metadata.get('profit_level_3_locked', False)
            )

        # 5. Trailing stop (adaptive distance, WIDER after Level 3)
        if not exit_signal:
            exit_signal = check_trailing_stop(
                profit_level_2_locked=metadata.get('profit_level_2_locked', False),
                profit_level_3_locked=metadata.get('profit_level_3_locked', False),
                highest_price=metadata.get('highest_price', broker_entry_price),
                current_price=current_price,
                trail_pct=adaptive_params['trailing_stop_pct'],
                trail_pct_final=adaptive_params['trailing_stop_final_pct'],
                pnl_pct=pnl_pct
            )

        # Add to exit orders
        if exit_signal:
            exit_signal['ticker'] = ticker
            exit_signal['broker_quantity'] = broker_quantity
            exit_signal['broker_entry_price'] = broker_entry_price
            exit_signal['current_price'] = current_price
            exit_signal['pnl_dollars'] = pnl_dollars
            exit_signal['pnl_pct'] = pnl_pct
            exit_signal['condition'] = adaptive_params['condition_label']
            exit_signal['entry_signal'] = metadata.get('entry_signal', 'pre_existing')
            exit_signal['entry_score'] = metadata.get('entry_score', 0)
            exit_orders.append(exit_signal)

    return exit_orders


def execute_exit_orders(strategy, exit_orders, current_date, position_monitor, profit_tracker, ticker_cooldown=None):
    """
    Execute exit orders using BROKER data for P&L calculation
    """

    for order in exit_orders:
        ticker = order['ticker']
        exit_type = order['type']
        sell_pct = order['sell_pct']
        reason = order['reason']
        message = order['message']
        condition = order.get('condition', 'N/A')

        # === GET FROM BROKER (Source of Truth) ===
        broker_quantity = order['broker_quantity']
        broker_entry_price = order['broker_entry_price']
        current_price = order['current_price']
        entry_signal = order.get('entry_signal', 'pre_existing')
        entry_score = order.get('entry_score', 0)

        # Calculate quantity to sell
        sell_quantity = int(broker_quantity * (sell_pct / 100))

        if sell_quantity <= 0:
            continue

        # === SIMPLE P&L CALCULATION ===
        pnl_per_share = current_price - broker_entry_price
        total_pnl = pnl_per_share * sell_quantity
        pnl_pct = (pnl_per_share / broker_entry_price * 100)

        # === PARTIAL EXIT ===
        if exit_type == 'partial_exit':
            profit_level = order.get('profit_level', 0)
            remaining = broker_quantity - sell_quantity

            print(f"\n{'=' * 70}")
            print(f"💰 PROFIT TAKING LEVEL {profit_level} - {ticker} {condition}")
            print(f"{'=' * 70}")
            print(f"Position: {broker_quantity} shares @ ${broker_entry_price:.2f}")
            print(f"Selling: {sell_quantity} shares ({sell_pct:.0f}%) @ ${current_price:.2f}")
            print(f"P&L: ${total_pnl:+,.2f} ({pnl_pct:+.1f}%)")
            print(f"Remaining: {remaining} shares")
            print(f"{'=' * 70}\n")

            # Mark profit level
            if profit_level == 1:
                position_monitor.mark_profit_level_1_locked(ticker)
            elif profit_level == 2:
                position_monitor.mark_profit_level_2_locked(ticker)
            elif profit_level == 3:
                position_monitor.mark_profit_level_3_locked(ticker)

            # === RECORD THE TRADE (with entry score) ===
            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=broker_entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            # Execute sell
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            print(f" * EXIT: {ticker} x{sell_quantity} | {message}")
            strategy.submit_order(sell_order)

        # === FULL EXIT ===
        elif exit_type == 'full_exit':
            print(f"\n{'=' * 70}")
            print(f"🚪 FULL EXIT - {ticker} {condition}")
            print(f"{'=' * 70}")
            print(f"Position: {broker_quantity} shares @ ${broker_entry_price:.2f}")
            print(f"Selling: {sell_quantity} shares @ ${current_price:.2f}")
            print(f"P&L: ${total_pnl:+,.2f} ({pnl_pct:+.1f}%)")
            print(f"Reason: {message}")
            print(f"{'=' * 70}\n")

            # === RECORD THE TRADE (with entry score) ===
            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=broker_entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            # Clean metadata
            position_monitor.clean_position_metadata(ticker)

            # Clear cooldown so ticker can be bought again
            if ticker_cooldown:
                ticker_cooldown.clear(ticker)
                print(f" * ⏰ COOLDOWN CLEARED: {ticker} (can buy again immediately if signal appears)")

            # Execute sell
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            print(f" * EXIT: {ticker} x{sell_quantity} | {message}")
            strategy.submit_order(sell_order)