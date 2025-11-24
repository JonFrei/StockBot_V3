"""
Optimal Position Sizing System - Independent Allocation

Key Features:
1. Each stock sized independently based on current opportunity quality
2. Historical performance (awards) applied as separate multiplier
3. Tiered scaling when budget constrained (protects high-quality setups)
4. Portfolio-level safeguards (concentration limits, cash reserves)

Quality Score: 0-100 points measuring CURRENT SETUP ONLY
Award Multiplier: 0.6x-1.3x based on HISTORICAL PERFORMANCE

Position Size = Base × Quality Tier × Conviction × Award × Volatility × Regime
"""


# =============================================================================
# CONFIGURATION
# =============================================================================

class OptimalPositionSizingConfig:
    """Position sizing configuration"""

    # Base position size (% of portfolio value)
    BASE_POSITION_PCT = 15.0  # Starting point for average opportunity

    # Quality-based tier multipliers
    QUALITY_MULTIPLIERS = {
        'exceptional': 1.3,  # 85-100 quality score
        'strong': 1.2,  # 70-84 quality score
        'good': 1.10,  # 55-69 quality score
        'average': 1.00,  # 40-54 quality score
        'weak': 0.9  # 0-39 quality score
    }

    # Conviction boost (based on signal count)
    # Multiple signals = higher conviction
    CONVICTION_BASE = 1.0
    CONVICTION_INCREMENT = 0.15  # +15% per additional signal

    # Position size bounds (% of portfolio value)
    MIN_POSITION_PCT = 3.0  # Below this = skip position
    MAX_POSITION_PCT = 20.0  # Single position concentration limit

    # Per-iteration limits
    MAX_POSITIONS_PER_ITERATION = 10
    MAX_CASH_DEPLOYMENT_PCT = 60.0  # % of available cash

    # Portfolio-level limits
    MAX_TOTAL_POSITIONS = 25
    MIN_CASH_RESERVE = 20000  # Minimum cash to keep in dollars

    # Tiered scaling thresholds (when budget tight)
    TIER1_QUALITY_THRESHOLD = 70  # Exceptional/Strong
    TIER2_QUALITY_THRESHOLD = 55  # Good
    # Below 55 = Tier 3 (Average/Weak)


# =============================================================================
# QUALITY SCORING - CURRENT SETUP ONLY (NO AWARDS)
# =============================================================================

def calculate_opportunity_quality(ticker, data, spy_data, signal_count):
    """
    Quality score: 0-100 points measuring CURRENT SETUP ONLY

    Historical performance NOT included (handled by award multiplier)

    Scoring:
    - Signal Strength: 0-30 points (multiple signals = higher quality)
    - Technical Setup: 0-30 points (ADX, MACD, EMA, volume)
    - Risk/Reward: 0-20 points (entry quality, volatility)
    - Market Alignment: 0-20 points (SPY trend, relative strength)

    Args:
        ticker: Stock symbol
        data: Stock technical indicators
        spy_data: SPY technical indicators
        signal_count: Number of triggered signals (1-4+)

    Returns:
        float: Quality score 0-100
    """
    score = 0.0

    # =================================================================
    # 2. TECHNICAL SETUP QUALITY (0-40 points)
    # =================================================================

    # ADX - Trend Strength (0-12 points)
    adx = data.get('adx', 0)
    if adx > 35:
        score += 12  # Very strong trend
    elif adx > 28:
        score += 10
    elif adx > 22:
        score += 8
    elif adx > 18:
        score += 6

    # MACD - Momentum (0-10 points)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)
    macd_hist_prev = data.get('macd_hist_prev', 0)

    if macd > macd_signal:
        if macd_hist > macd_hist_prev > 0:
            score += 10  # Bullish and accelerating
        elif macd_hist > 0:
            score += 8  # Bullish
        else:
            score += 6  # Recently turned bullish

    # EMA Alignment (0-10 points)
    close = data.get('close', 0)
    ema8 = data.get('ema8', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)

    if close > ema8 > ema20 > ema50:
        score += 10  # Perfect alignment
    elif close > ema20 > ema50:
        score += 8  # Good structure
    elif close > ema20:
        score += 6  # Basic structure

    # Volume Confirmation (0-8 points)
    volume_ratio = data.get('volume_ratio', 0)
    if volume_ratio > 2.0:
        score += 8  # Exceptional volume
    elif volume_ratio > 1.5:
        score += 6
    elif volume_ratio > 1.2:
        score += 4
    elif volume_ratio > 1.0:
        score += 2

    # =================================================================
    # 3. RISK/REWARD PROFILE (0-20 points)
    # =================================================================

    # Entry Quality - Not Overextended (0-10 points)
    ema20_distance = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100

    if ema20_distance < 2.0:
        score += 10  # Excellent entry near support
    elif ema20_distance < 3.5:
        score += 8
    elif ema20_distance < 5.0:
        score += 6
    elif ema20_distance < 7.0:
        score += 3
    # >7% extended = 0 points

    # Volatility Appropriate (0-10 points)
    vol_metrics = data.get('volatility_metrics', {})
    vol_score = vol_metrics.get('volatility_score', 5)

    if vol_score <= 2:
        score += 10  # Low volatility (ideal)
    elif vol_score <= 3:
        score += 8
    elif vol_score <= 4:
        score += 6
    elif vol_score <= 5:
        score += 4
    elif vol_score <= 6:
        score += 2
    # vol_score > 6 = 0 points

    # =================================================================
    # 4. MARKET ALIGNMENT (0-20 points)
    # =================================================================

    # SPY Trend Confirmation (0-10 points)
    if spy_data:
        spy_close = spy_data.get('close', 0)
        spy_ema20 = spy_data.get('ema20', 0)
        spy_ema50 = spy_data.get('ema50', 0)
        spy_adx = spy_data.get('adx', 0)

        if spy_close > spy_ema20 > spy_ema50 and spy_adx > 25:
            score += 10  # SPY in strong uptrend
        elif spy_close > spy_ema20 and spy_adx > 20:
            score += 7
        elif spy_close > spy_ema20:
            score += 4
        # SPY bearish = 0 points

    # Stock Relative Strength (0-10 points)
    sma200 = data.get('sma200', 0)
    distance_from_200 = ((close - sma200) / sma200 * 100) if sma200 > 0 else -100

    if distance_from_200 > 10.0:
        score += 10  # Strong relative strength
    elif distance_from_200 > 5.0:
        score += 8
    elif distance_from_200 > 2.0:
        score += 6
    elif distance_from_200 > 0:
        score += 3
    # Below 200 SMA = 0 points

    return min(100.0, score)


def get_quality_tier(quality_score):
    """Convert quality score to tier name"""
    if quality_score >= 85:
        return 'exceptional'
    elif quality_score >= 70:
        return 'strong'
    elif quality_score >= 55:
        return 'good'
    elif quality_score >= 40:
        return 'average'
    else:
        return 'weak'


def get_quality_tier_multiplier(quality_score):
    """Convert quality score to multiplier"""
    tier = get_quality_tier(quality_score)
    return OptimalPositionSizingConfig.QUALITY_MULTIPLIERS[tier]


# =============================================================================
# CONVICTION BOOST CALCULATION
# =============================================================================

def calculate_conviction_multiplier(signal_count):
    """
    Calculate conviction boost based on number of triggered signals

    1 signal: 1.0x (base)
    2 signals: 1.15x
    3 signals: 1.30x
    4+ signals: 1.45x

    Args:
        signal_count: Number of triggered buy signals (1-4+)

    Returns:
        float: Conviction multiplier
    """
    if signal_count <= 1:
        return OptimalPositionSizingConfig.CONVICTION_BASE

    # Cap at 4 signals
    effective_count = min(signal_count, 4)

    multiplier = OptimalPositionSizingConfig.CONVICTION_BASE + \
                 (effective_count - 1) * OptimalPositionSizingConfig.CONVICTION_INCREMENT

    return multiplier


# =============================================================================
# INDEPENDENT POSITION SIZING - MAIN ALGORITHM
# =============================================================================

def calculate_independent_position_sizes(opportunities, portfolio_context):
    """
    Calculate optimal position sizes independently for each opportunity

    Each position sized based on:
    1. Quality of current setup (quality score)
    2. Conviction (number of signals)
    3. Historical performance (award multiplier)
    4. Risk characteristics (volatility multiplier)
    5. Market regime (regime multiplier)

    When total exceeds budget: Tiered scaling (protect high-quality setups)

    Args:
        opportunities: List of dicts with opportunity data
        portfolio_context: Dict with portfolio state

    Returns:
        List of final position allocations with quantities
    """

    if not opportunities:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']
    max_deployment = deployable_cash * (OptimalPositionSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)

    print(f"\n{'=' * 90}")
    print(f"💰 INDEPENDENT POSITION SIZING - PHASE 1: CALCULATE IDEAL SIZES")
    print(f"{'=' * 90}")
    print(f"Portfolio Value: ${portfolio_value:,.0f}")
    print(f"Deployable Cash: ${deployable_cash:,.0f}")
    print(f"Max This Iteration: ${max_deployment:,.0f} ({OptimalPositionSizingConfig.MAX_CASH_DEPLOYMENT_PCT:.0f}%)")
    print(f"Opportunities: {len(opportunities)}")
    print(f"{'=' * 90}\n")

    # =================================================================
    # STEP 1: Calculate ideal size for each opportunity (unconstrained)
    # =================================================================

    position_targets = []

    for opp in opportunities:
        ticker = opp['ticker']
        quality_score = opp['quality_score']
        signal_count = opp['signal_count']

        # Base position size (% of portfolio)
        base_size_dollars = portfolio_value * (OptimalPositionSizingConfig.BASE_POSITION_PCT / 100)

        # Calculate all multipliers
        quality_multiplier = get_quality_tier_multiplier(quality_score)
        conviction_multiplier = calculate_conviction_multiplier(signal_count)
        award_multiplier = opp['award_multiplier']
        volatility_multiplier = opp['volatility_multiplier']
        regime_multiplier = opp['regime_multiplier']

        # Calculate ideal size
        ideal_size = base_size_dollars * \
                     quality_multiplier * \
                     conviction_multiplier * \
                     award_multiplier * \
                     volatility_multiplier * \
                     regime_multiplier

        # Apply single-position bounds
        max_position_dollars = portfolio_value * (OptimalPositionSizingConfig.MAX_POSITION_PCT / 100)
        min_position_dollars = portfolio_value * (OptimalPositionSizingConfig.MIN_POSITION_PCT / 100)

        bounded_size = max(min_position_dollars, min(ideal_size, max_position_dollars))

        # Calculate total multiplier for display
        total_multiplier = quality_multiplier * conviction_multiplier * award_multiplier * \
                           volatility_multiplier * regime_multiplier

        position_targets.append({
            'ticker': ticker,
            'ideal_size': ideal_size,
            'bounded_size': bounded_size,
            'quality_score': quality_score,
            'quality_tier': get_quality_tier(quality_score),
            'signal_count': signal_count,
            'quality_multiplier': quality_multiplier,
            'conviction_multiplier': conviction_multiplier,
            'award_multiplier': award_multiplier,
            'award': opp['award'],
            'volatility_multiplier': volatility_multiplier,
            'regime_multiplier': regime_multiplier,
            'total_multiplier': total_multiplier,
            'data': opp['data']
        })

    # Display ideal sizes
    print(f"{'Ticker':<8} {'Quality':<10} {'Tier':<12} {'Signals':<8} {'Award':<10} "
          f"{'Ideal $':<12} {'Bounded $':<12} {'Mult'}")
    print(f"{'-' * 95}")

    for pt in position_targets:
        quality_str = f"{pt['quality_score']:.0f}"
        award_emoji = {'premium': '🥇', 'standard': '🥈', 'trial': '🔬', 'none': '⚪', 'frozen': '❄️'}.get(pt['award'], '❓')

        print(f"{pt['ticker']:<8} {quality_str:<10} {pt['quality_tier']:<12} "
              f"{pt['signal_count']:<8} {award_emoji} {pt['award']:<8} "
              f"${pt['ideal_size']:>10,.0f} ${pt['bounded_size']:>10,.0f} {pt['total_multiplier']:.2f}x")

    print(f"{'-' * 95}\n")

    # =================================================================
    # STEP 2: Check if total exceeds iteration limit
    # =================================================================

    total_requested = sum(pt['bounded_size'] for pt in position_targets)

    print(f"Total Requested: ${total_requested:,.0f}")
    print(f"Budget Limit: ${max_deployment:,.0f}")

    if total_requested <= max_deployment:
        print(f"✅ Within budget - no scaling needed\n")
        return finalize_allocations(position_targets, portfolio_context, scale_factor=1.0)

    # =================================================================
    # STEP 3: Budget exceeded - apply tiered scaling
    # =================================================================

    print(f"⚠️  Over budget by ${total_requested - max_deployment:,.0f} - applying tiered scaling\n")

    return apply_priority_scaling(position_targets, max_deployment, portfolio_context)


# =============================================================================
# TIERED SCALING (When Budget Constrained)
# =============================================================================

def apply_priority_scaling(position_targets, max_deployment, portfolio_context):
    """
    Scale down positions to fit budget using tiered approach

    Strategy:
    - Tier 1 (Exceptional/Strong): Preserve as much as possible
    - Tier 2 (Good): Moderate scaling
    - Tier 3 (Average/Weak): Heavy scaling or cut

    Args:
        position_targets: List of position target dicts
        max_deployment: Maximum dollars to deploy
        portfolio_context: Portfolio state dict

    Returns:
        List of final allocations
    """

    # Sort by quality (best first)
    position_targets.sort(key=lambda x: x['quality_score'], reverse=True)

    # Separate into tiers based on quality
    tier1 = [pt for pt in position_targets if
             pt['quality_score'] >= OptimalPositionSizingConfig.TIER1_QUALITY_THRESHOLD]
    tier2 = [pt for pt in position_targets if OptimalPositionSizingConfig.TIER2_QUALITY_THRESHOLD <= pt[
        'quality_score'] < OptimalPositionSizingConfig.TIER1_QUALITY_THRESHOLD]
    tier3 = [pt for pt in position_targets if pt['quality_score'] < OptimalPositionSizingConfig.TIER2_QUALITY_THRESHOLD]

    # Calculate tier budgets
    tier1_budget = sum(pt['bounded_size'] for pt in tier1)
    tier2_budget = sum(pt['bounded_size'] for pt in tier2)
    tier3_budget = sum(pt['bounded_size'] for pt in tier3)
    total_budget = tier1_budget + tier2_budget + tier3_budget

    print(f"{'=' * 90}")
    print(f"🎯 TIERED SCALING STRATEGY")
    print(f"{'=' * 90}")
    print(
        f"Tier 1 (Quality ≥{OptimalPositionSizingConfig.TIER1_QUALITY_THRESHOLD}): {len(tier1)} positions, ${tier1_budget:,.0f}")
    print(
        f"Tier 2 (Quality {OptimalPositionSizingConfig.TIER2_QUALITY_THRESHOLD}-{OptimalPositionSizingConfig.TIER1_QUALITY_THRESHOLD - 1}): {len(tier2)} positions, ${tier2_budget:,.0f}")
    print(
        f"Tier 3 (Quality <{OptimalPositionSizingConfig.TIER2_QUALITY_THRESHOLD}): {len(tier3)} positions, ${tier3_budget:,.0f}")
    print(f"Total Requested: ${total_budget:,.0f}")
    print(f"Budget Limit: ${max_deployment:,.0f}")
    print(f"{'=' * 90}\n")

    final_allocations = []

    # =================================================================
    # STRATEGY 1: Preserve Tier 1 if possible
    # =================================================================

    if tier1_budget <= max_deployment * 0.75:  # Tier 1 uses ≤75% of budget
        print(f"✅ Strategy: Preserve Tier 1 fully, scale Tier 2/3\n")

        remaining_budget = max_deployment - tier1_budget

        # Allocate Tier 1 (no scaling)
        for pt in tier1:
            final_allocations.append({
                **pt,
                'final_size': pt['bounded_size'],
                'scale_factor': 1.0,
                'tier': 1
            })

        # Scale Tier 2
        if tier2 and remaining_budget > 0:
            if tier2_budget <= remaining_budget:
                # Tier 2 fits fully
                for pt in tier2:
                    final_allocations.append({
                        **pt,
                        'final_size': pt['bounded_size'],
                        'scale_factor': 1.0,
                        'tier': 2
                    })
                remaining_budget -= tier2_budget

                # Scale Tier 3 to fit remaining
                if tier3 and remaining_budget > 0:
                    tier3_scale = min(1.0, remaining_budget / tier3_budget)

                    min_size = portfolio_context['portfolio_value'] * (
                                OptimalPositionSizingConfig.MIN_POSITION_PCT / 100)

                    for pt in tier3:
                        scaled_size = pt['bounded_size'] * tier3_scale

                        if scaled_size >= min_size:
                            final_allocations.append({
                                **pt,
                                'final_size': scaled_size,
                                'scale_factor': tier3_scale,
                                'tier': 3
                            })
                else:
                    print(f"ℹ️  No budget remaining for Tier 3")
            else:
                # Tier 2 needs scaling
                tier2_scale = remaining_budget / tier2_budget

                for pt in tier2:
                    final_allocations.append({
                        **pt,
                        'final_size': pt['bounded_size'] * tier2_scale,
                        'scale_factor': tier2_scale,
                        'tier': 2
                    })

                print(f"⚠️  No budget remaining for Tier 3")
        else:
            print(f"ℹ️  No Tier 2/3 positions or no budget remaining")

    # =================================================================
    # STRATEGY 2: Tier 1 too large - proportional scaling
    # =================================================================
    else:
        print(f"⚠️  Strategy: Tier 1 uses >{max_deployment * 0.75:,.0f} - proportional scaling all tiers\n")

        global_scale = max_deployment / total_budget

        for pt in position_targets:
            if pt['quality_score'] >= OptimalPositionSizingConfig.TIER1_QUALITY_THRESHOLD:
                tier = 1
            elif pt['quality_score'] >= OptimalPositionSizingConfig.TIER2_QUALITY_THRESHOLD:
                tier = 2
            else:
                tier = 3

            final_allocations.append({
                **pt,
                'final_size': pt['bounded_size'] * global_scale,
                'scale_factor': global_scale,
                'tier': tier
            })

    print(f"{'=' * 90}\n")

    return finalize_allocations(final_allocations, portfolio_context)


# =============================================================================
# FINALIZATION - Convert to Share Quantities
# =============================================================================

def finalize_allocations(allocations, portfolio_context, scale_factor=None):
    """
    Convert dollar allocations to share quantities with real prices
    Apply final affordability checks

    Args:
        allocations: List of allocation dicts with 'final_size' or 'bounded_size'
        portfolio_context: Portfolio state dict
        scale_factor: Optional global scale factor to apply

    Returns:
        List of final position dicts with quantities
    """

    final_positions = []
    total_cost = 0
    min_size = portfolio_context['portfolio_value'] * (OptimalPositionSizingConfig.MIN_POSITION_PCT / 100)

    for alloc in allocations:
        ticker = alloc['ticker']
        target_dollars = alloc.get('final_size', alloc['bounded_size'])

        if scale_factor:
            target_dollars *= scale_factor

        # Skip if below minimum
        if target_dollars < min_size:
            continue

        current_price = alloc['data']['close']

        # Calculate quantity
        quantity = int(target_dollars / current_price)
        actual_cost = quantity * current_price

        # Skip if quantity is 0
        if quantity == 0:
            continue

        # Final affordability check
        if total_cost + actual_cost > portfolio_context['deployable_cash']:
            # Try to fit with reduced quantity
            remaining = portfolio_context['deployable_cash'] - total_cost
            quantity = int(remaining / current_price)
            actual_cost = quantity * current_price

            if quantity == 0 or actual_cost < min_size:
                continue

        final_positions.append({
            'ticker': ticker,
            'quantity': quantity,
            'cost': actual_cost,
            'price': current_price,
            'pct_portfolio': (actual_cost / portfolio_context['portfolio_value'] * 100),
            'quality_score': alloc['quality_score'],
            'quality_tier': alloc['quality_tier'],
            'signal_count': alloc['signal_count'],
            'award': alloc['award'],
            'tier': alloc.get('tier', 0),
            'scale_factor': alloc.get('scale_factor', 1.0),
            'target_dollars': target_dollars,
            'total_multiplier': alloc['total_multiplier'],
            'quality_multiplier': alloc['quality_multiplier'],
            'conviction_multiplier': alloc['conviction_multiplier'],
            'award_multiplier': alloc['award_multiplier'],
            'volatility_multiplier': alloc['volatility_multiplier'],
            'regime_multiplier': alloc['regime_multiplier']
        })

        total_cost += actual_cost

    # Display final allocation table
    display_final_allocations(final_positions, portfolio_context, total_cost)

    return final_positions


def display_final_allocations(positions, portfolio_context, total_cost):
    """Display comprehensive final allocation table"""

    if not positions:
        print(f"\n⚠️  No positions after finalization (all below minimum size)\n")
        return

    print(f"\n{'=' * 110}")
    print(f"📊 FINAL POSITION SIZING - INDEPENDENT ALLOCATION")
    print(f"{'=' * 110}")
    print(f"Portfolio Value: ${portfolio_context['portfolio_value']:,.0f}")
    print(f"Available Cash: ${portfolio_context['deployable_cash']:,.0f}")
    print(
        f"Total Allocated: ${total_cost:,.0f} ({total_cost / portfolio_context['deployable_cash'] * 100:.1f}% deployment)")
    print(f"Remaining Cash: ${portfolio_context['deployable_cash'] - total_cost:,.0f}")
    print(f"Position Count: {len(positions)}")
    print(f"{'=' * 110}\n")

    # Sort by cost (largest first)
    positions.sort(key=lambda x: x['cost'], reverse=True)

    print(f"{'Ticker':<8} {'Qual':<6} {'Tier':<8} {'Sig':<5} {'Award':<8} {'Scale':<7} "
          f"{'Cost':<12} {'%Port':<7} {'Qty':<6} {'Mult':<6}")
    print(f"{'-' * 110}")

    for pos in positions:
        quality_str = f"{pos['quality_score']:.0f}"
        tier_label = ['?', '🥇T1', '🥈T2', '🥉T3'][pos.get('tier', 0)]
        award_emoji = {'premium': '🥇', 'standard': '🥈', 'trial': '🔬', 'none': '⚪', 'frozen': '❄️'}.get(pos['award'],
                                                                                                       '❓')
        scale_str = f"{pos['scale_factor']:.2f}x" if pos['scale_factor'] < 1.0 else "FULL"

        print(f"{pos['ticker']:<8} {quality_str:<6} {tier_label:<8} {pos['signal_count']:<5} "
              f"{award_emoji} {pos['award']:<6} {scale_str:<7} ${pos['cost']:>10,.0f} "
              f"{pos['pct_portfolio']:>5.1f}%  {pos['quantity']:>5}  {pos['total_multiplier']:.2f}x")

    print(f"{'-' * 110}\n")

    # Multiplier breakdown for top 3
    print(f"MULTIPLIER BREAKDOWN (Top 3):")
    for i, pos in enumerate(positions[:3], 1):
        print(f"\n  {i}. {pos['ticker']} - Total: {pos['total_multiplier']:.2f}x")
        print(f"     Quality: {pos['quality_multiplier']:.2f}x (score: {pos['quality_score']:.0f})")
        print(f"     Conviction: {pos['conviction_multiplier']:.2f}x ({pos['signal_count']} signals)")
        print(f"     Award: {pos['award_multiplier']:.2f}x ({pos['award']})")
        print(f"     Volatility: {pos['volatility_multiplier']:.2f}x")
        print(f"     Regime: {pos['regime_multiplier']:.2f}x")

    # Tier summary
    tier_summary = {}
    for pos in positions:
        tier = pos.get('tier', 0)
        if tier not in tier_summary:
            tier_summary[tier] = {'count': 0, 'total_cost': 0}
        tier_summary[tier]['count'] += 1
        tier_summary[tier]['total_cost'] += pos['cost']

    print(f"\n\nTIER BREAKDOWN:")
    tier_labels = {1: '🥇 Tier 1 (Exceptional/Strong)', 2: '🥈 Tier 2 (Good)', 3: '🥉 Tier 3 (Average/Weak)'}
    for tier in sorted(tier_summary.keys()):
        if tier == 0:
            continue
        summary = tier_summary[tier]
        label = tier_labels.get(tier, f'Tier {tier}')
        print(f"  {label}: {summary['count']} positions, ${summary['total_cost']:,.0f} "
              f"({summary['total_cost'] / total_cost * 100:.1f}% of total)")

    print(f"\n{'=' * 110}\n")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def count_triggered_signals(ticker, data, active_signals, spy_data=None):
    """
    Count how many signals are triggered for this ticker

    Args:
        ticker: Stock symbol
        data: Stock technical data
        active_signals: List of active signal names
        spy_data: SPY data (optional)

    Returns:
        int: Number of triggered signals
    """
    import stock_signals

    count = 0
    for signal_name in active_signals:
        if signal_name in stock_signals.BUY_STRATEGIES:
            signal_func = stock_signals.BUY_STRATEGIES[signal_name]
            result = signal_func(data)

            if result and result.get('side') == 'buy':
                count += 1

    return count


def create_portfolio_context(strategy):
    """
    Create portfolio context dict from strategy

    Args:
        strategy: Lumibot Strategy instance

    Returns:
        dict: Portfolio context
    """
    cash_balance = strategy.get_cash()
    portfolio_value = strategy.portfolio_value
    existing_positions = len(strategy.get_positions())

    deployable_cash = cash_balance - OptimalPositionSizingConfig.MIN_CASH_RESERVE

    # Ensure deployable cash is positive
    deployable_cash = max(0, deployable_cash)

    return {
        'total_cash': cash_balance,
        'portfolio_value': portfolio_value,
        'existing_positions_count': existing_positions,
        'available_slots': OptimalPositionSizingConfig.MAX_TOTAL_POSITIONS - existing_positions,
        'reserved_cash': OptimalPositionSizingConfig.MIN_CASH_RESERVE,
        'deployable_cash': deployable_cash
    }