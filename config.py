"""
Minimal configuration loader for environment variables
Usage: from config import Config
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # API Keys
    TWELVE_DATA_API_KEY = os.getenv('TWELVE_DATA_API_KEY')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')
    POLYGON_API_KEY = os.getenv('POLYGON_API_KEY')

    # Alpaca
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
    ALPACA_API_SECRET = os.getenv('ALPACA_API_SECRET')
    ALPACA_PAPER = os.getenv('ALPACA_PAPER', 'True').lower() == 'true'


    # Email
    EMAIL_SENDER = os.getenv('EMAIL_SENDER')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
    EMAIL_RECIPIENT = os.getenv('EMAIL_RECIPIENT')

    # Backtesting
    BACKTESTING = os.getenv('BACKTESTING', 'False').lower() == 'true'

    @classmethod
    def get_alpaca_config(cls):
        return {
            "API_KEY": cls.ALPACA_API_KEY,
            "API_SECRET": cls.ALPACA_API_SECRET,
            "PAPER": cls.ALPACA_PAPER
        }