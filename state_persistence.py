"""
Minimal State Persistence for Crash Recovery

Saves critical state to disk, restores on restart.
Uses simple JSON files in /app/data volume.
"""

import json
import os
from datetime import datetime
from pathlib import Path


class StatePersistence:
    """Minimal persistence - only what's needed for crash recovery"""

    def __init__(self, data_dir='/app/data'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.state_file = self.data_dir / 'bot_state.json'
        self.backup_file = self.data_dir / 'bot_state_backup.json'

    def save_state(self, strategy):
        """
        Save critical state that can't be recovered from broker

        What we save:
        1. Position metadata (entry dates, signals, profit levels, highest prices)
        2. Cooldown timers
        3. Stock rotation state (awards, last rotation date)
        4. Drawdown protection state
        5. Last update timestamp
        """

        state = {
            'last_updated': datetime.now().isoformat(),
            'portfolio_peak': strategy.drawdown_protection.portfolio_peak,
            'drawdown_protection_active': strategy.drawdown_protection.protection_active,
            'drawdown_protection_end_date': strategy.drawdown_protection.protection_end_date.isoformat()
            if strategy.drawdown_protection.protection_end_date else None,

            # Position metadata - CRITICAL for exits
            'positions_metadata': {
                ticker: {
                    'entry_date': meta['entry_date'].isoformat(),
                    'entry_signal': meta['entry_signal'],
                    'entry_score': meta.get('entry_score', 0),
                    'highest_price': meta['highest_price'],
                    'profit_level_1_locked': meta.get('profit_level_1_locked', False),
                    'profit_level_2_locked': meta.get('profit_level_2_locked', False),
                    'profit_level_3_locked': meta.get('profit_level_3_locked', False)
                }
                for ticker, meta in strategy.position_monitor.positions_metadata.items()
            },

            # Cooldowns - prevents immediate rebuys
            'cooldowns': {
                ticker: date.isoformat()
                for ticker, date in strategy.ticker_cooldown.last_buy_dates.items()
            },

            # Stock rotation - awards determine position sizing
            'stock_rotation': {
                'ticker_awards': strategy.stock_rotator.ticker_awards,
                'last_rotation_date': strategy.stock_rotator.last_rotation_date.isoformat()
                if strategy.stock_rotator.last_rotation_date else None,
                'last_rotation_week': strategy.last_rotation_week
            },

            # Blacklist state
            'blacklist': {
                'consecutive_losses': strategy.stock_rotator.blacklist.consecutive_losses,
                'temporary_blacklist': {
                    ticker: date.isoformat()
                    for ticker, date in strategy.stock_rotator.blacklist.temporary_blacklist.items()
                },
                'permanent_blacklist': list(strategy.stock_rotator.blacklist.permanent_blacklist)
            } if strategy.stock_rotator.blacklist else {}
        }

        # Backup existing state before overwriting
        if self.state_file.exists():
            self.state_file.rename(self.backup_file)

        # Write new state
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def load_state(self, strategy):
        """
        Restore state from disk
        Returns True if state was restored, False if starting fresh
        """

        if not self.state_file.exists():
            print("\n[RECOVERY] No saved state found - starting fresh")
            return False

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)

            print(f"\n{'=' * 80}")
            print(f"🔄 RESTORING STATE FROM DISK")
            print(f"{'=' * 80}")
            print(f"Last saved: {state['last_updated']}")

            # Restore drawdown protection
            if state.get('portfolio_peak'):
                strategy.drawdown_protection.portfolio_peak = state['portfolio_peak']
                strategy.drawdown_protection.protection_active = state.get('drawdown_protection_active', False)

                if state.get('drawdown_protection_end_date'):
                    strategy.drawdown_protection.protection_end_date = datetime.fromisoformat(
                        state['drawdown_protection_end_date']
                    )

                print(f"✅ Drawdown Protection: Peak ${state['portfolio_peak']:,.2f}")

            # Restore position metadata
            for ticker, meta in state.get('positions_metadata', {}).items():
                strategy.position_monitor.positions_metadata[ticker] = {
                    'entry_date': datetime.fromisoformat(meta['entry_date']),
                    'entry_signal': meta['entry_signal'],
                    'entry_score': meta.get('entry_score', 0),
                    'highest_price': meta['highest_price'],
                    'profit_level_1_locked': meta.get('profit_level_1_locked', False),
                    'profit_level_2_locked': meta.get('profit_level_2_locked', False),
                    'profit_level_3_locked': meta.get('profit_level_3_locked', False)
                }

            print(f"✅ Position Metadata: {len(state.get('positions_metadata', {}))} position(s)")

            # Restore cooldowns
            for ticker, date_str in state.get('cooldowns', {}).items():
                strategy.ticker_cooldown.last_buy_dates[ticker] = datetime.fromisoformat(date_str)

            print(f"✅ Cooldowns: {len(state.get('cooldowns', {}))} ticker(s)")

            # Restore stock rotation
            rotation = state.get('stock_rotation', {})
            if rotation:
                strategy.stock_rotator.ticker_awards = rotation.get('ticker_awards', {})

                if rotation.get('last_rotation_date'):
                    strategy.stock_rotator.last_rotation_date = datetime.fromisoformat(
                        rotation['last_rotation_date']
                    )

                strategy.last_rotation_week = rotation.get('last_rotation_week')

                print(f"✅ Stock Rotation: {len(rotation.get('ticker_awards', {}))} awards restored")

            # Restore blacklist
            blacklist_data = state.get('blacklist', {})
            if blacklist_data and strategy.stock_rotator.blacklist:
                strategy.stock_rotator.blacklist.consecutive_losses = blacklist_data.get('consecutive_losses', {})

                for ticker, date_str in blacklist_data.get('temporary_blacklist', {}).items():
                    strategy.stock_rotator.blacklist.temporary_blacklist[ticker] = datetime.fromisoformat(date_str)

                strategy.stock_rotator.blacklist.permanent_blacklist = set(
                    blacklist_data.get('permanent_blacklist', [])
                )

                print(f"✅ Blacklist: {len(blacklist_data.get('permanent_blacklist', []))} permanent, "
                      f"{len(blacklist_data.get('temporary_blacklist', {}))} temporary")

            print(f"{'=' * 80}\n")

            # Validate with broker
            self._validate_with_broker(strategy)

            return True

        except Exception as e:
            print(f"\n⚠️ [RECOVERY] Failed to load state: {e}")
            print("Starting fresh...")
            return False

    def _validate_with_broker(self, strategy):
        """
        Cross-check saved state with broker positions
        Warn about mismatches but don't crash
        """

        try:
            broker_positions = strategy.get_positions()
            broker_tickers = {p.symbol for p in broker_positions}
            state_tickers = set(strategy.position_monitor.positions_metadata.keys())

            # Positions in broker but not in state
            missing_metadata = broker_tickers - state_tickers
            if missing_metadata:
                print(f"\n⚠️ [VALIDATION] Broker has positions without metadata: {missing_metadata}")
                print("These will be treated as pre-existing positions")

                for ticker in missing_metadata:
                    strategy.position_monitor.track_position(
                        ticker,
                        strategy.get_datetime(),
                        'recovered_unknown',
                        entry_score=0
                    )

            # Positions in state but not in broker
            extra_metadata = state_tickers - broker_tickers
            if extra_metadata:
                print(f"\n⚠️ [VALIDATION] State has metadata for closed positions: {extra_metadata}")
                print("Cleaning up...")

                for ticker in extra_metadata:
                    strategy.position_monitor.clean_position_metadata(ticker)

            if not missing_metadata and not extra_metadata:
                print(f"✅ [VALIDATION] State matches broker ({len(broker_tickers)} position(s))")

        except Exception as e:
            print(f"⚠️ [VALIDATION] Could not validate with broker: {e}")


def save_state_safe(strategy):
    """
    Wrapper that handles errors gracefully
    Bot continues even if save fails
    """
    try:
        persistence = StatePersistence()
        persistence.save_state(strategy)
    except Exception as e:
        print(f"⚠️ Failed to save state: {e}")
        print("Continuing anyway...")


def load_state_safe(strategy):
    """
    Wrapper that handles errors gracefully
    Returns False if load fails (start fresh)
    """
    try:
        persistence = StatePersistence()
        return persistence.load_state(strategy)
    except Exception as e:
        print(f"⚠️ Failed to load state: {e}")
        print("Starting fresh...")
        return False