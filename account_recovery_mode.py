"""
Recovery Mode System - Bear Market Rally Trading
"""

from datetime import timedelta


class RecoveryModeConfig:
    MIN_RECOVERY_SIGNALS = 3
    MIN_LOCK_DAYS_BEFORE_RECOVERY = 5
    RECOVERY_POSITION_MULTIPLIER = 0.35
    RECOVERY_MAX_POSITIONS = 5
    RELOCK_ON_SPY_DOWN_DAYS = 2
    RECOVERY_MODE_MAX_DAYS = 10
    RECOVERY_PROFIT_TARGET = 7.0
    BREADTH_UNLOCK_THRESHOLD = 30.0
    BREADTH_LOCK_THRESHOLD = 20.0


class RecoveryModeManager:
    def __init__(self):
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None
        self.lock_start_date = None
        self.activation_count = 0
        self.spy_ema10 = 0
        self.spy_ema21 = 0
        self.spy_close = 0
        self.spy_prev_close = 0
        self.spy_consecutive_down_days = 0
        self.spy_price_history = []
        self.internal_breadth = {'pct_above_20ema': 0, 'pct_above_50sma': 0, 'pct_green_today': 0}
        self.recent_accum_days = 0
        self.recent_dist_days = 0

    def update_spy_data(self, date, spy_close, spy_prev_close=None):
        self.spy_close = spy_close
        if spy_prev_close:
            self.spy_prev_close = spy_prev_close
            if spy_close < spy_prev_close:
                self.spy_consecutive_down_days += 1
            else:
                self.spy_consecutive_down_days = 0
        if self.spy_ema10 == 0:
            self.spy_ema10 = spy_close
            self.spy_ema21 = spy_close
        else:
            self.spy_ema10 = spy_close * (2 / 11) + self.spy_ema10 * (9 / 11)
            self.spy_ema21 = spy_close * (2 / 22) + self.spy_ema21 * (20 / 22)
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)
        self.spy_price_history.append({'date': date, 'close': spy_close})
        self.spy_price_history = self.spy_price_history[-30:]

    def update_breadth(self, all_stock_data):
        above_20ema = above_50sma = green_today = total = 0
        for ticker, data in all_stock_data.items():
            if ticker == 'SPY':
                continue
            ind = data.get('indicators', {})
            if not ind:
                continue
            total += 1
            close = ind.get('close', 0)
            if close > ind.get('ema20', 0):
                above_20ema += 1
            if close > ind.get('sma50', 0):
                above_50sma += 1
            if close > ind.get('prev_close', 0):
                green_today += 1
        if total > 0:
            self.internal_breadth = {
                'pct_above_20ema': round(above_20ema / total * 100, 1),
                'pct_above_50sma': round(above_50sma / total * 100, 1),
                'pct_green_today': round(green_today / total * 100, 1),
            }

    def update_accum_dist(self, accum_days, dist_days):
        self.recent_accum_days = accum_days
        self.recent_dist_days = dist_days

    def count_recovery_signals(self):
        signals = {'breadth_improving': False, 'spy_above_ema10': False, 'spy_above_ema21': False,
                   'ema10_above_ema21': False, 'accumulation_dominant': False, 'higher_low_forming': False}
        if self.internal_breadth.get('pct_above_20ema', 0) > RecoveryModeConfig.BREADTH_UNLOCK_THRESHOLD:
            signals['breadth_improving'] = True
        if self.spy_close > self.spy_ema10:
            signals['spy_above_ema10'] = True
        if self.spy_close > self.spy_ema21:
            signals['spy_above_ema21'] = True
        if self.spy_ema10 > self.spy_ema21:
            signals['ema10_above_ema21'] = True
        ad_ratio = (self.recent_accum_days / self.recent_dist_days) if self.recent_dist_days > 0 else (10.0 if self.recent_accum_days > 0 else 1.0)
        if ad_ratio > 1.0:
            signals['accumulation_dominant'] = True
        if self._check_higher_low():
            signals['higher_low_forming'] = True
        signals['total'] = sum(1 for k, v in signals.items() if k != 'total' and v is True)
        return signals

    def _check_higher_low(self):
        if len(self.spy_price_history) < 15:
            return False
        prices = [p['close'] for p in self.spy_price_history[-15:]]
        lows = []
        for i in range(2, len(prices) - 2):
            if prices[i] < prices[i-1] and prices[i] < prices[i-2] and prices[i] < prices[i+1] and prices[i] < prices[i+2]:
                lows.append(prices[i])
        return len(lows) >= 2 and lows[-1] > lows[-2]

    def start_lock(self, current_date):
        if not self.lock_start_date:
            self.lock_start_date = current_date
            print(f"🔒 LOCK STARTED: SPY below 200 SMA")

    def clear_lock(self):
        if self.lock_start_date or self.recovery_mode_active:
            print(f"🔓 LOCK CLEARED: SPY above 200 SMA")
        self.lock_start_date = None
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None

    def check_recovery_mode_entry(self, current_date):
        if not self.lock_start_date or self.recovery_mode_active:
            return False
        days_locked = (current_date - self.lock_start_date).days
        if days_locked < RecoveryModeConfig.MIN_LOCK_DAYS_BEFORE_RECOVERY:
            return False
        return self.count_recovery_signals()['total'] >= RecoveryModeConfig.MIN_RECOVERY_SIGNALS

    def enter_recovery_mode(self, current_date):
        self.activation_count += 1
        self.recovery_mode_active = True
        self.recovery_mode_start_date = current_date
        signals = self.count_recovery_signals()
        print(f"\n{'=' * 60}")
        print(f"🔓 RECOVERY MODE ACTIVATED (#{self.activation_count})")
        print(f"   Signals: {signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS} | Size: {RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER*100:.0f}% | Max: {RecoveryModeConfig.RECOVERY_MAX_POSITIONS}")
        print(f"{'=' * 60}\n")

    def check_recovery_mode_exit(self, current_date):
        if not self.recovery_mode_active:
            return False, None
        days = (current_date - self.recovery_mode_start_date).days
        if days > RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS:
            return True, f"Max duration ({RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS}d)"
        if self.spy_consecutive_down_days >= RecoveryModeConfig.RELOCK_ON_SPY_DOWN_DAYS:
            return True, f"SPY down {self.spy_consecutive_down_days}d"
        signals = self.count_recovery_signals()
        if signals['total'] < RecoveryModeConfig.MIN_RECOVERY_SIGNALS:
            return True, f"Signals weak ({signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS})"
        if self.internal_breadth.get('pct_above_20ema', 0) < RecoveryModeConfig.BREADTH_LOCK_THRESHOLD:
            return True, f"Breadth collapsed"
        return False, None

    def exit_recovery_mode(self, reason):
        if self.recovery_mode_active:
            self.recovery_mode_active = False
            self.recovery_mode_start_date = None
            print(f"🔒 RECOVERY MODE TERMINATED: {reason}")
            return True
        return False

    def trigger_relock(self, current_date, reason):
        return self.exit_recovery_mode(reason)

    def evaluate(self, current_date, spy_below_200):
        if not spy_below_200:
            self.clear_lock()
            return {'recovery_mode_active': False, 'position_multiplier': 1.0, 'max_positions': 25,
                    'allow_entries': True, 'profit_target': 10.0, 'signals': {}, 'reason': 'Normal'}
        self.start_lock(current_date)
        if self.recovery_mode_active:
            should_exit, exit_reason = self.check_recovery_mode_exit(current_date)
            if should_exit:
                self.exit_recovery_mode(exit_reason)
        if not self.recovery_mode_active and self.check_recovery_mode_entry(current_date):
            self.enter_recovery_mode(current_date)
        signals = self.count_recovery_signals()
        if self.recovery_mode_active:
            return {'recovery_mode_active': True, 'position_multiplier': RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER,
                    'max_positions': RecoveryModeConfig.RECOVERY_MAX_POSITIONS, 'allow_entries': True,
                    'profit_target': RecoveryModeConfig.RECOVERY_PROFIT_TARGET, 'signals': signals,
                    'reason': f"Recovery: {signals['total']} signals"}
        days_locked = (current_date - self.lock_start_date).days if self.lock_start_date else 0
        return {'recovery_mode_active': False, 'position_multiplier': 0.0, 'max_positions': 0,
                'allow_entries': False, 'profit_target': 10.0, 'signals': signals,
                'reason': f"Locked: {signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS} signals, day {days_locked}"}

    def get_statistics(self):
        return {
            'recovery_mode_active': self.recovery_mode_active,
            'activation_count': self.activation_count,
            'lock_start_date': self.lock_start_date,
            'spy_ema10': round(self.spy_ema10, 2),
            'spy_ema21': round(self.spy_ema21, 2),
            'internal_breadth': self.internal_breadth,
            'recovery_signals': self.count_recovery_signals(),
        }