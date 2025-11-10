def get_portfolio_data(strategy):
    """
    Returns portfolio data from Alpaca API or Lumibot backtest.

    Args:
        strategy: Lumibot Strategy instance

    Returns:
        dict: Portfolio data including cash, positions, and portfolio value
    """
    if strategy.is_backtesting:
        # Backtesting mode - use Lumibot's built-in methods
        return {
            'cash': strategy.get_cash(),
            'portfolio_value': strategy.get_portfolio_value(),
            'positions': strategy.get_positions()
        }
    else:
        # Live trading mode - get data from Alpaca API
        account = strategy.broker.get_account()
        positions = strategy.broker.get_positions()

        return {
            'cash': float(account.cash),
            'portfolio_value': float(account.portfolio_value),
            'positions': positions
        }