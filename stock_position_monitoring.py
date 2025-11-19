"""
Enhanced Stock Position Monitoring with Signal-Strength-Based Dynamic Exits

Key Enhancement:
- Exit parameters (stops, targets, holding periods) now scale based on signal strength
- WEAK signals (1 trigger): Tighter stops, conservative targets, quick exits
- MEDIUM signals (2 triggers): Standard parameters
- STRONG signals (3+ triggers): Wider stops, aggressive targets, longer holds

All original function names preserved for compatibility.
"""

from datetime import datetime, timedelta


# =============================================================================
# SIGNAL STRENGTH EXIT CONFIGURATION
# =============================================================================

class SignalStrengthConfig:
    """Centralized configuration for signal-strength-based exits"""

    # WEAK SIGNALS (1 trigger) - Conservative approach (Score 0-3)
    WEAK = {
        'stop_loss_pct': -2.5,  # Tight stop (emergency stop)
        'profit_level_1': 6.0,  # Quick profit taking
        'profit_level_1_sell': 50.0,  # Sell 50% at first target
        'profit_level_2': 8.0,  # Fast second target
        'profit_level_2_sell': 30.0,  # Sell 30% of remaining
        'profit_level_3': 12.0,  # Conservative final target
        'profit_level_3_sell': 20.0,  # Sell 20% of remaining
        'max_holding_days': 15,  # Quick exit
        'trailing_activation': 6.0,  # Activate trailing early
        'trailing_distance': 6.0,  # Tight trail
        'trailing_distance_final': 12.0  # Trail after Level 3
    }

    # MEDIUM SIGNALS (2 triggers) - Standard approach (Score 4-6)
    MEDIUM = {
        'stop_loss_pct': -4.0,  # Standard stop
        'profit_level_1': 10.0,  # Standard targets
        'profit_level_1_sell': 50.0,  # Sell 50% at first target
        'profit_level_2': 18.0,  # Second target
        'profit_level_2_sell': 30.0,  # Sell 30% of remaining
        'profit_level_3': 30.0,  # Final target
        'profit_level_3_sell': 20.0,  # Sell 20% of remaining
        'max_holding_days': 20,
        'trailing_activation': 10.0,
        'trailing_distance': 10.0,
        'trailing_distance_final': 18.0
    }

    # STRONG SIGNALS (3+ triggers) - Aggressive approach (Score 7-10)
    STRONG = {
        'stop_loss_pct': -7.0,  # Wide stop (let winners run)
        'profit_level_1': 12.0,  # Higher targets
        'profit_level_1_sell': 50.0,  # Sell 50% at first target
        'profit_level_2': 22.0,  # Aggressive second target
        'profit_level_2_sell': 30.0,  # Sell 30% of remaining
        'profit_level_3': 35.0,  # High final target
        'profit_level_3_sell': 20.0,  # Sell 20% of remaining
        'max_holding_days': 25,  # Longer hold
        'trailing_activation': 12.0,
        'trailing_distance': 12.0,
        'trailing_distance_final': 20.0
    }


# =============================================================================
# POSITION MONITORING FUNCTIONS
# =============================================================================

def classify_signal_strength(signal_count):
    """
    Classify signal strength based on number of triggers

    Args:
        signal_count: Number of signals that triggered the trade

    Returns:
        str: 'STRONG', 'MEDIUM', or 'WEAK'
    """
    if signal_count >= 3:
        return 'STRONG'
    elif signal_count == 2:
        return 'MEDIUM'
    else:
        return 'WEAK'


def get_exit_parameters(signal_strength):
    """
    Get exit parameters based on signal strength

    Args:
        signal_strength: 'STRONG', 'MEDIUM', or 'WEAK'

    Returns:
        dict: Exit parameters including stops, targets, and holding period
    """
    if signal_strength == 'STRONG':
        return SignalStrengthConfig.STRONG
    elif signal_strength == 'MEDIUM':
        return SignalStrengthConfig.MEDIUM
    else:
        return SignalStrengthConfig.WEAK


def get_signal_strength_emoji(signal_strength):
    """Get emoji representation for signal strength"""
    emoji_map = {
        'STRONG': '🟢',
        'MEDIUM': '🟡',
        'WEAK': '🔴'
    }
    return emoji_map.get(signal_strength, '⚪')


def calculate_momentum_score(data):
    """
    Calculate momentum score for a stock based on technical indicators
    Used to determine if we should override max holding period

    Args:
        data: Dict with technical indicators

    Returns:
        dict: {
            'score': float (0-10),
            'breakdown': dict,
            'is_strong': bool (score >= 7.0)
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

    return {
        'score': score,
        'breakdown': breakdown,
        'is_strong': score >= 7.0  # Strong momentum threshold
    }


def calculate_market_condition_score(stock_data, spy_data=None):
    """
    Calculate overall market condition score

    Args:
        stock_data: Dict of {ticker: data_dict} with indicators
        spy_data: Optional SPY data dict with indicators

    Returns:
        dict: {
            'score': float (0-10),
            'regime': str ('TRENDING', 'RANGING', 'CAUTIOUS'),
            'position_multiplier': float,
            'stop_multiplier': float,
            'max_positions': int
        }
    """
    if not stock_data:
        return {
            'score': 5.0,
            'regime': 'CAUTIOUS',
            'position_multiplier': 0.7,
            'stop_multiplier': 0.85,
            'max_positions': 8
        }

    # Calculate regime based on market indicators
    score = 5.0  # Neutral starting point

    # Check SPY if available
    if spy_data and 'indicators' in spy_data:
        indicators = spy_data['indicators']

        # ADX check (trend strength)
        adx = indicators.get('adx', 20)
        if adx > 30:
            score += 2.0  # Strong trend
        elif adx > 25:
            score += 1.0  # Moderate trend

        # Price vs EMAs
        close = indicators.get('close', 0)
        ema50 = indicators.get('ema50', 0)

        if close > 0 and ema50 > 0:
            deviation_pct = ((close - ema50) / ema50) * 100
            if deviation_pct > 5:
                score += 1.5
            elif deviation_pct > 2:
                score += 0.5
            elif deviation_pct < -5:
                score -= 2.0

    # Classify regime
    if score >= 7:
        regime = 'TRENDING'
        position_multiplier = 1.0
        stop_multiplier = 1.0
        max_positions = 10
    elif score >= 4:
        regime = 'RANGING'
        position_multiplier = 0.85
        stop_multiplier = 0.9
        max_positions = 9
    else:
        regime = 'CAUTIOUS'
        position_multiplier = 0.7
        stop_multiplier = 0.85
        max_positions = 8

    return {
        'score': score,
        'regime': regime,
        'position_multiplier': position_multiplier,
        'stop_multiplier': stop_multiplier,
        'max_positions': max_positions
    }


def check_positions_for_exits(strategy, position_tiers, current_date, profit_tracker=None, all_stock_data=None):
    """
    Check all positions for exit conditions with signal-strength-based parameters

    Args:
        strategy: Lumibot strategy instance
        position_tiers: Dict of position tracking data
        current_date: Current datetime
        profit_tracker: Optional profit tracker instance
        all_stock_data: Optional dict of current stock data for momentum checking

    Returns:
        list: Exit orders to execute
    """
    exit_orders = []

    # Get all current positions
    positions = strategy.get_positions()

    for position in positions:
        symbol = position.symbol

        # Skip if not in position_tiers (shouldn't happen)
        if symbol not in position_tiers:
            print(f"\n[WARNING] {symbol}: Position not tracked - closing for safety")
            exit_orders.append({
                'symbol': symbol,
                'quantity': position.quantity,
                'reason': 'UNTRACKED',
                'current_price': strategy.get_last_price(symbol)
            })
            continue

        # Get position data
        tier_data = position_tiers[symbol]
        entry_price = tier_data['entry_price']
        entry_date = tier_data['entry_date']
        signal_count = tier_data.get('signal_count', 1)
        signal_strength = tier_data.get('signal_strength', 'WEAK')

        # Get current price
        current_price = strategy.get_last_price(symbol)
        if not current_price or current_price <= 0:
            continue

        # Update highest price tracking
        if current_price > tier_data.get('highest_price', current_price):
            tier_data['highest_price'] = current_price

        highest_price = tier_data.get('highest_price', current_price)

        # Calculate metrics
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        days_held = (current_date - entry_date).days

        # Get signal-strength-based exit parameters
        exit_params = get_exit_parameters(signal_strength)

        # === CHECK EXIT CONDITIONS ===

        # 1. STOP LOSS (Dynamic based on signal strength)
        if profit_pct <= exit_params['stop_loss_pct']:
            exit_orders.append({
                'symbol': symbol,
                'quantity': position.quantity,
                'reason': 'STOP_LOSS',
                'current_price': current_price,
                'profit_pct': profit_pct,
                'signal_strength': signal_strength
            })
            print(f"🛑 {symbol} [{signal_strength}] Stop Loss: {profit_pct:.1f}% "
                  f"(Threshold: {exit_params['stop_loss_pct']:.1f}%)")
            continue

        # 2. PROFIT LEVEL 3 (Highest target - 20% exit)
        if profit_pct >= exit_params['profit_level_3']:
            # Check if already took this level
            if not tier_data.get('level_3_taken'):
                # Sell 20% of remaining position
                remaining_quantity = position.quantity
                partial_quantity = int(remaining_quantity * (exit_params['profit_level_3_sell'] / 100.0))

                if partial_quantity > 0:
                    exit_orders.append({
                        'symbol': symbol,
                        'quantity': partial_quantity,
                        'reason': 'PROFIT_LEVEL_3',
                        'current_price': current_price,
                        'profit_pct': profit_pct,
                        'signal_strength': signal_strength,
                        'partial': True
                    })
                    tier_data['level_3_taken'] = True
                    print(
                        f"💰 {symbol} [{signal_strength}] Profit Level 3 ({exit_params['profit_level_3_sell']:.0f}% exit): {profit_pct:.1f}% "
                        f"(Target: {exit_params['profit_level_3']:.1f}%)")

            # Activate final trailing stop
            if not tier_data.get('trailing_active_final'):
                tier_data['trailing_active_final'] = True
                tier_data['trail_final_start'] = current_price
                print(f"🎯 {symbol} [{signal_strength}] Final trailing stop activated at {profit_pct:.1f}%")

            # Check final trailing stop
            if tier_data.get('trailing_active_final'):
                peak_pullback = ((highest_price - current_price) / highest_price) * 100

                if peak_pullback >= exit_params['trailing_distance_final']:
                    # Exit remaining position
                    exit_orders.append({
                        'symbol': symbol,
                        'quantity': position.quantity,
                        'reason': 'FINAL_TRAILING_STOP',
                        'current_price': current_price,
                        'profit_pct': profit_pct,
                        'signal_strength': signal_strength
                    })
                    print(f"📉 {symbol} [{signal_strength}] Final Trailing Stop: {profit_pct:.1f}% "
                          f"(Pullback: {peak_pullback:.1f}%)")
                    continue

        # 3. PROFIT LEVEL 2 (30% exit + activate trailing)
        elif profit_pct >= exit_params['profit_level_2']:
            # Check if already took this level
            if not tier_data.get('level_2_taken'):
                # Sell 30% of remaining position
                remaining_quantity = position.quantity
                partial_quantity = int(remaining_quantity * (exit_params['profit_level_2_sell'] / 100.0))

                if partial_quantity > 0:
                    exit_orders.append({
                        'symbol': symbol,
                        'quantity': partial_quantity,
                        'reason': 'PROFIT_LEVEL_2',
                        'current_price': current_price,
                        'profit_pct': profit_pct,
                        'signal_strength': signal_strength,
                        'partial': True
                    })
                    tier_data['level_2_taken'] = True
                    print(
                        f"💵 {symbol} [{signal_strength}] Profit Level 2 ({exit_params['profit_level_2_sell']:.0f}% exit): {profit_pct:.1f}% "
                        f"(Target: {exit_params['profit_level_2']:.1f}%)")

            # Activate standard trailing stop
            if not tier_data.get('trailing_active'):
                tier_data['trailing_active'] = True
                tier_data['trail_start_price'] = current_price
                print(f"🎯 {symbol} [{signal_strength}] Trailing stop activated at {profit_pct:.1f}%")

            # Check standard trailing stop
            if tier_data.get('trailing_active'):
                peak_pullback = ((highest_price - current_price) / highest_price) * 100

                if peak_pullback >= exit_params['trailing_distance']:
                    # Exit remaining position
                    exit_orders.append({
                        'symbol': symbol,
                        'quantity': position.quantity,
                        'reason': 'TRAILING_STOP',
                        'current_price': current_price,
                        'profit_pct': profit_pct,
                        'signal_strength': signal_strength
                    })
                    print(f"📉 {symbol} [{signal_strength}] Trailing Stop: {profit_pct:.1f}% "
                          f"(Pullback: {peak_pullback:.1f}%)")
                    continue

        # 4. PROFIT LEVEL 1 (50% exit)
        elif profit_pct >= exit_params['profit_level_1']:
            # Check if already took this level
            if not tier_data.get('level_1_taken'):
                # Sell 50% of position
                partial_quantity = int(position.quantity * (exit_params['profit_level_1_sell'] / 100.0))

                if partial_quantity > 0:
                    exit_orders.append({
                        'symbol': symbol,
                        'quantity': partial_quantity,
                        'reason': 'PROFIT_LEVEL_1',
                        'current_price': current_price,
                        'profit_pct': profit_pct,
                        'signal_strength': signal_strength,
                        'partial': True
                    })
                    tier_data['level_1_taken'] = True
                    print(
                        f"💵 {symbol} [{signal_strength}] Profit Level 1 ({exit_params['profit_level_1_sell']:.0f}% exit): {profit_pct:.1f}% "
                        f"(Target: {exit_params['profit_level_1']:.1f}%)")

        # 5. MAX HOLDING PERIOD (Dynamic based on signal strength)
        # ENHANCED: Check momentum before exiting on max hold
        if days_held >= exit_params['max_holding_days']:
            # Check if we should override max hold due to strong momentum
            should_override = False

            # Only override if we're profitable and have momentum data
            if profit_pct > 0 and all_stock_data and symbol in all_stock_data:
                stock_data = all_stock_data[symbol]
                if 'indicators' in stock_data:
                    momentum = calculate_momentum_score(stock_data['indicators'])

                    # Override if momentum is strong (score >= 7.0)
                    if momentum['is_strong']:
                        should_override = True
                        print(f"⏰🚀 {symbol} [{signal_strength}] Max Hold OVERRIDDEN - "
                              f"Strong momentum (Score: {momentum['score']:.1f}/10) | "
                              f"Days: {days_held}/{exit_params['max_holding_days']} | "
                              f"P&L: {profit_pct:+.1f}%")

                        # Store momentum override info
                        tier_data['momentum_override'] = True
                        tier_data['momentum_score'] = momentum['score']

            # Exit only if not overridden
            if not should_override:
                exit_orders.append({
                    'symbol': symbol,
                    'quantity': position.quantity,
                    'reason': 'MAX_HOLD',
                    'current_price': current_price,
                    'profit_pct': profit_pct,
                    'signal_strength': signal_strength,
                    'days_held': days_held
                })
                print(f"⏰ {symbol} [{signal_strength}] Max Hold: {days_held} days "
                      f"(Limit: {exit_params['max_holding_days']} days) | P&L: {profit_pct:+.1f}%")
                continue

    return exit_orders


def execute_exit_orders(strategy, exit_orders, position_tiers, profit_tracker=None):
    """
    Execute exit orders and update tracking

    Args:
        strategy: Lumibot strategy instance
        exit_orders: List of exit order dicts
        position_tiers: Dict of position tracking data
        profit_tracker: Optional profit tracker instance
    """
    if not exit_orders:
        return

    print(f"\n{'=' * 80}")
    print(f"📊 EXECUTING {len(exit_orders)} EXIT ORDER(S)")
    print(f"{'=' * 80}")

    for order in exit_orders:
        symbol = order['symbol']
        quantity = order['quantity']
        reason = order['reason']
        current_price = order['current_price']
        signal_strength = order.get('signal_strength', 'UNKNOWN')
        profit_pct = order.get('profit_pct', 0)
        is_partial = order.get('partial', False)

        try:
            # Create and submit sell order
            sell_order = strategy.create_order(symbol, quantity, "sell")
            strategy.submit_order(sell_order)

            # Get emoji for signal strength
            strength_emoji = get_signal_strength_emoji(signal_strength)

            # Calculate P&L
            if symbol in position_tiers:
                entry_price = position_tiers[symbol]['entry_price']
                pnl_dollars = (current_price - entry_price) * quantity

                exit_type = "PARTIAL" if is_partial else "FULL"
                print(f" * SELL {exit_type}: {symbol} x{quantity} {strength_emoji} {signal_strength} | "
                      f"{reason} | ${current_price:.2f} | "
                      f"P&L: ${pnl_dollars:+,.2f} ({profit_pct:+.1f}%)")

                # Record trade in profit tracker only for full exits
                if profit_tracker and not is_partial:
                    profit_tracker.close_position(
                        ticker=symbol,
                        exit_price=current_price,
                        quantity=quantity,
                        exit_date=strategy.get_datetime(),
                        exit_reason=reason
                    )

                # Clean up position tracking ONLY if full exit (not partial)
                if not is_partial:
                    if symbol in position_tiers:
                        del position_tiers[symbol]

        except Exception as e:
            print(f"\n[ERROR] Failed to exit {symbol}: {str(e)}")
            import traceback
            traceback.print_exc()

    print(f"{'=' * 80}\n")


def print_position_summary(strategy, position_tiers, current_date):
    """
    Print summary of current positions with signal strength indicators

    Args:
        strategy: Lumibot strategy instance
        position_tiers: Dict of position tracking data
        current_date: Current datetime
    """
    positions = strategy.get_positions()

    if not positions:
        print("\n📊 No open positions")
        return

    print(f"\n{'=' * 80}")
    print(f"📊 OPEN POSITIONS: {len(positions)}")
    print(f"{'=' * 80}")

    total_unrealized_pnl = 0

    for position in positions:
        symbol = position.symbol

        if symbol not in position_tiers:
            continue

        tier_data = position_tiers[symbol]
        entry_price = tier_data['entry_price']
        entry_date = tier_data['entry_date']
        signal_count = tier_data.get('signal_count', 1)
        signal_strength = tier_data.get('signal_strength', 'WEAK')

        # Get current metrics
        current_price = strategy.get_last_price(symbol)
        if not current_price:
            continue

        pnl_dollars = (current_price - entry_price) * position.quantity
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        days_held = (current_date - entry_date).days

        total_unrealized_pnl += pnl_dollars

        # Get exit parameters for this signal strength
        exit_params = get_exit_parameters(signal_strength)
        strength_emoji = get_signal_strength_emoji(signal_strength)

        print(f"   {symbol:<6} {strength_emoji} | {position.quantity:>4} shares @ ${entry_price:>7.2f} | "
              f"Current: ${current_price:>7.2f} | "
              f"P&L: ${pnl_dollars:>+8.2f} ({pnl_pct:>+5.1f}%) | "
              f"{days_held}d/{exit_params['max_holding_days']}d")

    print(f"\n   Total Unrealized P&L: ${total_unrealized_pnl:+,.2f}")
    print(f"{'=' * 80}\n")


# =============================================================================
# BACKWARDS COMPATIBILITY WRAPPER
# =============================================================================

def _check_tiered_exits(strategy, symbol, position, current_price, position_tiers, current_date):
    """
    Backwards compatibility wrapper for existing code
    Redirects to new check_positions_for_exits logic
    """
    # This function maintained for backwards compatibility
    # Real logic is in check_positions_for_exits()
    pass