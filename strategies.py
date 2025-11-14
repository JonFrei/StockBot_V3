"""
SwingTradeStrategy - COMPLETE WITH ALL PRIORITY IMPROVEMENTS

Integrated Features:
- Priority 1: Optimized signals (consolidation + golden_cross loosened)
- Priority 2: Ticker blacklist (integrated in stock_rotation)
- Priority 3: Market regime detection (per-ticker + global)
- Priority 4: Multi-signal conviction sizing
- Priority 5: Momentum death exits
"""

from lumibot.strategies import Strategy
from config import Config

import stock_data
import signals
import position_sizing
import profit_tracking
import position_monitoring
from ticker_cooldown import TickerCooldown

# INTEGRATED IMPORTS (consolidated modules)
from stock_rotation import StockRotator  # Has integrated blacklist
import drawdown_protection  # Has integrated market regime

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())


class SwingTradeStrategy(Strategy):
    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    # Active trading signals (in priority order)
    ACTIVE_SIGNALS = [
        'consolidation_breakout',  # 75% win rate - LOOSENED
        'golden_cross',  # 77% win rate - LOOSENED
        'bollinger_buy'
        'swing_trade_1',  # EMA crossover + momentum
        'swing_trade_2',  # Pullback plays

    ]

    # Cooldown configuration
    COOLDOWN_DAYS = 3  # Days between re-purchases of same ticker

    # Base position sizing (modified by conviction + regime)
    BASE_POSITION_SIZE_PCT = 12.0  # Will be adjusted by multi-signal + regime

    MAX_ACTIVE_STOCKS = 10

    # =========================================================================

    def initialize(self, send_emails=True):
        """Initialize strategy with all integrated systems"""
        if Config.BACKTESTING:
            self.sleeptime = "1D"
        else:
            self.sleeptime = "10M"

        self.tickers = self.parameters.get("tickers", [])

        # SIMPLIFIED: Tracker just logs completed trades
        self.profit_tracker = profit_tracking.ProfitTracker(self)

        # Position monitoring (for exits + market condition caching)
        self.position_monitor = position_monitoring.PositionMonitor(self)

        # Ticker cooldown to prevent chasing
        self.ticker_cooldown = TickerCooldown(cooldown_days=self.COOLDOWN_DAYS)

        # PRIORITY 2 & 5: Stock rotation WITH integrated blacklist + profit tracker
        self.stock_rotator = StockRotator(
            max_active=self.MAX_ACTIVE_STOCKS,
            rotation_frequency='biweekly',
            profit_tracker=self.profit_tracker  # Blacklist automatic
        )

        # Track rotation timing
        self.last_rotation_week = None

        # Drawdown protection (has integrated market regime)
        self.drawdown_protection = drawdown_protection.create_default_protection(
            threshold_pct=-10.0,
            recovery_days=5
        )

        print(
            f"✅ Drawdown Protection: {self.drawdown_protection.threshold_pct:.1f}% threshold, {self.drawdown_protection.recovery_days}d recovery")
        print(f"✅ Ticker Cooldown: {self.ticker_cooldown.cooldown_days} days between purchases")
        print(
            f"✅ Stock Rotation: Max {self.stock_rotator.max_active} active stocks ({self.stock_rotator.rotation_frequency})")
        print(f"✅ Integrated Blacklist: Automatic (part of rotation)")
        print(f"✅ Market Regime Detection: Integrated (per-ticker + global)")
        print(f"✅ Multi-Signal Conviction: Enabled (12-18% position sizing)")
        print(f"✅ Active Signals: {len(self.ACTIVE_SIGNALS)} signals configured")

    def before_starting_trading(self):
        """
        Sync existing positions - SIMPLIFIED
        Just track metadata, broker has quantity/price
        """
        if Config.BACKTESTING:
            return

        try:
            broker_positions = self.get_positions()

            if len(broker_positions) > 0:
                for position in broker_positions:
                    ticker = position.symbol

                    if ticker in self.tickers:
                        # Just track metadata (no quantity/price needed)
                        self.position_monitor.track_position(
                            ticker,
                            self.get_datetime(),
                            'pre_existing',
                            entry_score=0
                        )

                print(f"[SYNC] Loaded {len(self.position_monitor.positions_metadata)} positions\n")

        except Exception as e:
            print(f"[ERROR] Failed to sync positions: {e}")

    def on_trading_iteration(self):
        if not broker.is_market_open() and Config.BACKTESTING == 'False':
            return

        current_date = self.get_datetime()
        current_date_str = current_date.strftime('%Y-%m-%d')

        print('\n')
        print(30 * '=' + ' Date: ' + str(current_date) + ' ' + 30 * '=')
        print('Portfolio Value:', self.portfolio_value)
        print('Cash Balance:', self.get_cash())

        # Display active cooldowns
        active_cooldowns = self.ticker_cooldown.get_all_cooldowns(current_date)
        if active_cooldowns:
            print(f"\n⏰ Active Cooldowns:")
            for ticker, days_left in active_cooldowns:
                print(f"   {ticker}: {days_left} day(s) remaining")

        print('\n')

        # =====================================================================
        # PORTFOLIO DRAWDOWN PROTECTION - HIGHEST PRIORITY
        # =====================================================================

        # Check if protection should trigger
        if self.drawdown_protection.should_trigger(self.portfolio_value):
            self.drawdown_protection.activate(
                strategy=self,
                current_date=current_date,
                position_monitor=self.position_monitor,
                ticker_cooldown=self.ticker_cooldown
            )
            return  # Skip rest of iteration

        # Check if in recovery period
        if self.drawdown_protection.is_in_recovery(current_date):
            self.drawdown_protection.print_status(self.portfolio_value, current_date)
            # Continue to exits but no new positions

        # =====================================================================
        # FETCH DATA FOR ALL TICKERS + SPY
        # =====================================================================

        all_tickers = list(set(self.tickers + ['SPY'] + [p.symbol for p in self.get_positions()]))
        all_stock_data = stock_data.process_data(all_tickers, current_date)
        spy_data = all_stock_data.get('SPY', {}).get('indicators', None) if 'SPY' in all_stock_data else None

        # =====================================================================
        # PRIORITY 3: GLOBAL MARKET REGIME DETECTION
        # =====================================================================

        regime_info = drawdown_protection.detect_market_regime(spy_data)
        print(drawdown_protection.format_regime_display(regime_info))

        # INTEGRATED: Clean expired blacklists
        if self.stock_rotator.blacklist:
            self.stock_rotator.blacklist.clean_expired_blacklists(current_date)

        # =====================================================================
        # STEP 1: CHECK ALL EXISTING POSITIONS FOR EXITS (HIGHEST PRIORITY)
        # =====================================================================

        # Check positions and get exit orders (uses adaptive parameters)
        exit_orders = position_monitoring.check_positions_for_exits(
            strategy=self,
            current_date=current_date,
            all_stock_data=all_stock_data,
            position_monitor=self.position_monitor
        )

        # Execute all exit orders
        position_monitoring.execute_exit_orders(
            strategy=self,
            exit_orders=exit_orders,
            current_date=current_date,
            position_monitor=self.position_monitor,
            profit_tracker=self.profit_tracker,
            ticker_cooldown=self.ticker_cooldown
        )

        # =====================================================================
        # SKIP NEW POSITIONS IF IN RECOVERY OR BEAR MARKET
        # =====================================================================

        if self.drawdown_protection.is_in_recovery(current_date):
            print(f"⚠️ In drawdown recovery - no new positions")
            return

        if not regime_info.get('allow_trading', True):
            print(f"\n⚠️ {regime_info['description']}")
            print(f"No new positions will be opened.\n")
            return

        # =====================================================================
        # STEP 2: STOCK ROTATION - BI-WEEKLY ROTATION
        # =====================================================================

        # Calculate bi-weekly period (2-week blocks)
        current_week = current_date.isocalendar()[1]  # ISO week number
        current_year = current_date.year
        biweekly_period = (current_year, current_week // 2)  # Groups weeks into 2-week periods

        # Check if this is a new bi-weekly period
        if self.last_rotation_week != biweekly_period:
            # Time to rotate - perform actual rotation
            active_tickers = self.stock_rotator.rotate_stocks(
                strategy=self,
                all_candidates=self.tickers,
                current_date=current_date,
                all_stock_data=all_stock_data
            )
            self.last_rotation_week = biweekly_period
        else:
            # NOT time to rotate - use existing active list
            active_tickers = self.stock_rotator.active_tickers

            # First iteration - initialize active list
            if not active_tickers:
                active_tickers = self.stock_rotator.rotate_stocks(
                    strategy=self,
                    all_candidates=self.tickers,
                    current_date=current_date,
                    all_stock_data=all_stock_data
                )
                self.last_rotation_week = biweekly_period

        # =====================================================================
        # STEP 3: LOOK FOR NEW BUY SIGNALS WITH MULTI-SIGNAL CONVICTION
        # =====================================================================

        buy_orders = []

        # Track cash commitments to prevent over-purchasing
        pending_cash_commitment = 0

        for ticker in active_tickers:

            if ticker not in all_stock_data:
                self.log_message(f"No data for {ticker}, skipping")
                continue

            # Get stock data and indicators
            data = all_stock_data[ticker]['indicators']

            # ===================================================================
            # PRIORITY 3: CHECK REGIME FOR THIS SPECIFIC TICKER
            # (includes 200 SMA check - moved from signals.py)
            # ===================================================================

            ticker_regime = drawdown_protection.detect_market_regime(spy_data, stock_data=data)

            # Skip if this ticker blocked by regime (e.g., below 200 SMA)
            if not ticker_regime.get('allow_trading', True):
                continue

            # === CHECK COOLDOWN BEFORE PROCESSING ===
            if not self.ticker_cooldown.can_buy(ticker, current_date):
                continue

            # Skip if we already have a position
            has_position = ticker in self.positions
            if has_position:
                continue

            # === GET ADAPTIVE PARAMETERS FOR EXITS (still used for exit strategy) ===
            adaptive_params = self.position_monitor.get_cached_market_conditions(
                ticker, current_date_str, data
            )

            # ===================================================================
            # CHECK FOR BUY SIGNAL (regime filter now in drawdown_protection)
            # ===================================================================

            buy_signal = signals.buy_signals(data, self.ACTIVE_SIGNALS, spy_data=spy_data)

            # Skip if no buy signal
            if not buy_signal or buy_signal.get('side') != 'buy':
                continue

            # ===================================================================
            # PRIORITY 4: MULTI-SIGNAL CONVICTION SIZING
            # Count ALL signals that trigger for this ticker
            # ===================================================================

            signal_count = 0
            for test_signal_name in self.ACTIVE_SIGNALS:
                test_signal_func = signals.BUY_STRATEGIES[test_signal_name]
                test_result = test_signal_func(data)
                if test_result and test_result.get('side') == 'buy':
                    signal_count += 1

            # Dynamic position sizing based on signal count
            if signal_count >= 3:
                signal_position_size = 18.0  # High conviction
                conviction_label = '🔥 HIGH'
            elif signal_count == 2:
                signal_position_size = 15.0  # Medium conviction
                conviction_label = '⚡ MEDIUM'
            else:
                signal_position_size = 12.0  # Single signal
                conviction_label = '• STANDARD'

            # ===================================================================
            # APPLY REGIME MULTIPLIER (from ticker-specific regime)
            # ===================================================================

            final_position_pct = signal_position_size * ticker_regime['position_size_multiplier']

            # === CALCULATE POSITION SIZE ===
            buy_position = position_sizing.calculate_buy_size(
                self,
                data['close'],
                account_threshold=20000,
                max_position_pct=final_position_pct,
                pending_commitments=pending_cash_commitment,
                adaptive_params=None
            )

            # Check if we can trade
            if not buy_position['can_trade']:
                continue

            # Track position with entry signal (no score)
            self.position_monitor.track_position(
                ticker,
                current_date,
                buy_signal.get('signal_type', 'unknown'),
                entry_score=0
            )

            # Create order
            order_sig = buy_signal.copy()
            order_sig['ticker'] = ticker
            order_sig['stop_loss'] = 0.90 * data['close']
            order_sig['quantity'] = buy_position['quantity']
            order_sig['position_value'] = buy_position['position_value']
            order_sig['condition'] = adaptive_params['condition_label']
            order_sig['conviction'] = conviction_label
            order_sig['signal_count'] = signal_count
            buy_orders.append(order_sig)

            # ADD COMMITMENT to prevent over-purchasing
            pending_cash_commitment += buy_position['position_value']

            # Display pending order with conviction
            print(
                f" * PENDING BUY: {ticker} x{buy_position['quantity']} {conviction_label} ({signal_count} signals) {adaptive_params['condition_label']} | {buy_signal['signal_type']} = ${buy_position['position_value']:,.2f}")

        # =====================================================================
        # CHECK REGIME-BASED POSITION LIMITS
        # =====================================================================

        current_positions = len(self.get_positions())
        max_positions_allowed = regime_info['max_positions']

        if current_positions >= max_positions_allowed:
            print(
                f"\n⚠️ Position limit reached ({current_positions}/{max_positions_allowed} due to {regime_info['regime']} market)")
            print(f"Skipping new entries.\n")
            return

        # Submit buy orders
        if len(buy_orders) > 0:
            print(f"\n{'=' * 70}")
            print(f"📊 BUY ORDERS SUMMARY - {len(buy_orders)} order(s)")
            print(f"{'=' * 70}")
            print(f"Total Cash Commitment: ${pending_cash_commitment:,.2f}")
            print(f"Cash After Orders: ${self.get_cash() - pending_cash_commitment:,.2f}")
            print(f"{'=' * 70}\n")

            for order in buy_orders:
                if order['side'] == 'buy':
                    submit_order = self.create_order(order['ticker'], order['quantity'], order['side'])

                    print(
                        f" * BUY: {order['ticker']} x{order['quantity']} {order['conviction']} ({order['signal_count']} signals) {order['condition']} | {order['signal_type']}")
                    print(f"        Price: ${order['limit_price']:.2f} | Value: ${order['position_value']:,.2f}")

                    self.submit_order(submit_order)

                    # Record buy in cooldown tracker
                    self.ticker_cooldown.record_buy(order['ticker'], current_date)

    def on_strategy_end(self):
        """Display final statistics"""

        # Profit tracking summary
        self.profit_tracker.display_final_summary()

        # Cooldown statistics
        cooldown_stats = self.ticker_cooldown.get_statistics()
        print(f"\n{'=' * 80}")
        print(f"⏰ TICKER COOLDOWN STATISTICS")
        print(f"{'=' * 80}")
        print(f"Cooldown Period: {cooldown_stats['cooldown_days']} days")
        print(f"Total Buys Recorded: {cooldown_stats['total_buys_recorded']}")
        print(f"\nBuy Count by Ticker:")
        for ticker, count in list(cooldown_stats['buy_count_by_ticker'].items())[:10]:
            print(f"   {ticker}: {count} purchases")
        print(f"{'=' * 80}\n")

        # Rotation statistics (includes integrated blacklist)
        from stock_rotation import print_rotation_report
        print_rotation_report(self.stock_rotator)

        # Drawdown protection summary
        drawdown_protection.print_protection_summary(self.drawdown_protection)

        return 0