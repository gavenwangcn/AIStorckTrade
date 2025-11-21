# Configuration Example

# Server
HOST = '0.0.0.0'
PORT = 5000
DEBUG = False

# Database
DATABASE_PATH = 'trading_bot.db'

# Trading
AUTO_TRADING = True
TRADING_INTERVAL = 180  # seconds

# JQData (A-share market data)
JQDATA_USERNAME = '15900543131'
JQDATA_PASSWORD = 'a19996479O'
JQDATA_API_URL = 'https://dataapi.joinquant.com'  # 可根据实际账号调整

# Initial Stock Universe (code, name, exchange, api_symbol)
INITIAL_STOCKS = [
    ('600519', '贵州茅台', 'XSHG', '600519.XSHG'),
    ('000001', '平安银行', 'XSHE', '000001.XSHE'),
    ('300750', '宁德时代', 'XSHE', '300750.XSHE'),
    ('601318', '中国平安', 'XSHG', '601318.XSHG'),
    ('002594', '比亚迪', 'XSHE', '002594.XSHE')
]

# Market Data
MARKET_API_CACHE = 5  # seconds
MARKET_API_URL = JQDATA_API_URL

# Refresh Rates (frontend)
MARKET_REFRESH = 5000  # ms
PORTFOLIO_REFRESH = 10000  # ms
TRADE_FEE_RATE = 0.001  # 交易费率：0.1%（双向收费）

