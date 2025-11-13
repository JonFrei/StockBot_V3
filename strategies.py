from lumibot.strategies import Strategy

from config import Config

import stock_data
import signals
import position_sizing
import profit_tracking
import position_monitoring
from ticker_cooldown import TickerCooldown
from stock_rotation import StockRotator

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())


class SwingTradeStrategy(Strategy):
    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    # Active trading signals (in priority order)
    ACTIVE_SIGNALS = [
        'consolidation_breakout',  # Consolidation breaks
        'swing_trade_1',  # EMA crossover + momentum
        'swing_trade_2',  # Pullback plays
        'golden_cross',
        'bollinger_buy'
    ]

    # Cooldown configuration
    COOLDOWN_DAYS = 2  # Days between re-purchases of same ticker

    # Fixed position sizing (no adaptive entry sizing)
    POSITION_SIZE_PCT = 15.0  # 14% of cash per trade

    MAX_ACTIVE_STOCKS = 12

    # =========================================================================

    def initialize(self, send_emails=True):
        """Initialize strategy with position tracking"""
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

        # PRIORITY 5: Stock rotation WITH profit_tracker for win rate tracking
        self.stock_rotator = StockRotator(
            max_active=self.MAX_ACTIVE_STOCKS,
            rotation_frequency='biweekly',
            profit_tracker=self.profit_tracker  # NEW: Pass profit tracker
        )

        # Track rotation timing
        self.last_rotation_week = None

        print(f"✅ Ticker Cooldown Enabled: {self.ticker_cooldown.cooldown_days} days between purchases")
        print(f"✅ Stock Rotation: Max {self.stock_rotator.max_active} active stocks ({self.stock_rotator.rotation_frequency})")
        print(f"✅ Win Rate Tracking: Enabled (Priority 5)")
        print(f"✅ Ticker Penalties: Enabled (Priority 3)")
        print(f"✅ Active Signals: {len(self.ACTIVE_SIGNALS)} signals configured")
        print(f"✅ Fixed Position Size: {self.POSITION_SIZE_PCT}% per trade")

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

        all_tickers = list(set(self.tickers + [p.symbol for p in self.get_positions()]))
        all_stock_data = stock_data.process_data(all_tickers, current_date)

        spy_data = all_stock_data.get('SPY', {}).get('indicators', None) if 'SPY' in all_stock_data else None

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
        # STEP 2: STOCK ROTATION - TRUE WEEKLY ROTATION
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
        # STEP 3: LOOK FOR NEW BUY SIGNALS (SIMPLIFIED - NO SCORING)
        # =====================================================================

        buy_orders = []

        # Track cash commitments to prevent over-purchasing
        pending_cash_commitment = 0

        for ticker in active_tickers:

            if ticker not in all_stock_data:
                self.log_message(f"No data for {ticker}, skipping")
                continue

            # Get stocks and indicators
            data = all_stock_data[ticker]['indicators']

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

            # === CHECK FOR ANY VALID BUY SIGNAL (SIMPLIFIED) ===
            buy_signal = signals.buy_signals(data, self.ACTIVE_SIGNALS, spy_data=spy_data)

            # Skip if no buy signal
            if not buy_signal or buy_signal.get('side') != 'buy':
                continue

            # === FIXED POSITION SIZE (NO ADAPTIVE ENTRY SIZING) ===
            buy_position = position_sizing.calculate_buy_size(
                self,
                data['close'],
                account_threshold=20000,
                max_position_pct=self.POSITION_SIZE_PCT,  # Fixed 14%
                pending_commitments=pending_cash_commitment,
                adaptive_params=None  # No adaptive entry sizing
            )

            # Check if we can trade
            if not buy_position['can_trade']:
                continue

            # Track position with entry signal (no score)
            self.position_monitor.track_position(
                ticker,
                current_date,
                buy_signal.get('signal_type', 'unknown'),
                entry_score=0  # No scoring system
            )

            # Create order
            order_sig = buy_signal.copy()
            order_sig['ticker'] = ticker
            order_sig['stop_loss'] = 0.90 * data['close']
            order_sig['quantity'] = buy_position['quantity']
            order_sig['position_value'] = buy_position['position_value']
            order_sig['condition'] = adaptive_params['condition_label']
            buy_orders.append(order_sig)

            # ADD COMMITMENT to prevent over-purchasing
            pending_cash_commitment += buy_position['position_value']

            # Display pending order
            print(
                f" * PENDING BUY: {ticker} x{buy_position['quantity']} {adaptive_params['condition_label']} | {buy_signal['signal_type']} = ${buy_position['position_value']:,.2f}")

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
                        f" * BUY: {order['ticker']} x{order['quantity']} {order['condition']} | {order['signal_type']}")
                    print(f"        Price: ${order['limit_price']:.2f} | Value: ${order['position_value']:,.2f}")

                    self.submit_order(submit_order)

                    # Record buy in cooldown tracker
                    self.ticker_cooldown.record_buy(order['ticker'], current_date)

    def on_strategy_end(self):
        self.profit_tracker.display_final_summary()

        # Display cooldown statistics
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

        # Display rotation statistics
        from stock_rotation import print_rotation_report
        print_rotation_report(self.stock_rotator)

        return 0