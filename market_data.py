"""
Market data module - integrates Sina Finance for configurable A-share stocks.
Original JQData implementation remains commented for future re-enable when needed.
"""
import os
import time
import json
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional

import requests

# from jqdatasdk import auth, get_price  # 聚宽接口（保留，后续可恢复）

try:
    import config as app_config
except ImportError:  # pragma: no cover
    import config_example as app_config


class MarketDataFetcher:
    """Fetch real-time market data from Sina Finance for configured stocks"""

    def __init__(self, db, jq_username: str = None, jq_password: str = None):
        self.db = db
        self._cache = {}
        self._cache_time = {}
        self._cache_duration = getattr(app_config, 'MARKET_API_CACHE', 5)
        self.session = requests.Session()
        self.session.headers.update({'Referer': 'https://finance.sina.com.cn'})
        self._last_market_open_state: bool = False
        self._last_live_prices: Dict[str, Dict] = {}
        self._last_live_date: Optional[datetime.date] = None

        # 聚宽账号信息（保留，便于未来切换）
        # self.jq_username = jq_username or getattr(app_config, 'JQDATA_USERNAME', None) or os.getenv('JQDATA_USERNAME')
        # self.jq_password = jq_password or getattr(app_config, 'JQDATA_PASSWORD', None) or os.getenv('JQDATA_PASSWORD')
        # if self.jq_username and self.jq_password:
        #     try:
        #         auth(self.jq_username, self.jq_password)
        #         print('[INFO] JQData auth success')
        #     except Exception as e:
        #         print(f'[ERROR] JQData auth failed: {e}')
        # else:
        #     print('[WARN] JQData credentials not provided. Set JQDATA_USERNAME and JQDATA_PASSWORD.')

    def _get_configured_stocks(self) -> List[Dict]:
        stocks = self.db.get_stock_configs()
        if not stocks:
            print('[WARN] No stocks configured. Please add stocks via configuration UI.')
        return stocks

    def _parse_time_setting(self, value: str) -> dt_time:
        try:
            parts = [int(p) for p in value.split(':')]
            while len(parts) < 3:
                parts.append(0)
            return dt_time(parts[0], parts[1], parts[2])
        except Exception:
            return dt_time(0, 0, 0)

    def _get_trading_window_bounds(self) -> (dt_time, dt_time):
        settings = self.db.get_settings()
        start_str = settings.get('auto_trading_start', '09:30:00')
        end_str = settings.get('auto_trading_end', '15:00:00')
        return self._parse_time_setting(start_str), self._parse_time_setting(end_str)

    def is_within_trading_window(self, current_dt: Optional[datetime] = None) -> bool:
        now = current_dt or datetime.now()
        now_time = now.time()
        start_time, end_time = self._get_trading_window_bounds()
        if start_time <= end_time:
            return start_time <= now_time <= end_time
        return now_time >= start_time or now_time <= end_time

    def _format_stored_prices(self, stored_prices: Dict[str, Dict], symbols: Optional[List[str]] = None) -> Dict[str, Dict]:
        stock_map = {stock['symbol']: stock for stock in self._get_configured_stocks()}
        target_symbols = symbols or list(stock_map.keys()) or list(stored_prices.keys())
        formatted: Dict[str, Dict] = {}

        for symbol in target_symbols:
            stored = stored_prices.get(symbol)
            stock = stock_map.get(symbol, {})
            if not stored:
                continue

            formatted[symbol] = {
                'price': stored.get('price', 0),
                'name': stock.get('name', symbol),
                'exchange': stock.get('exchange', ''),
                'change_24h': 0,
                'price_date': stored.get('price_date'),
                'source': 'closing'
            }

        return formatted

    def _persist_closing_prices(self):
        if not self._last_live_prices or not self._last_live_date:
            return

        price_date = self._last_live_date.strftime('%Y-%m-%d')
        for symbol, payload in self._last_live_prices.items():
            price = payload.get('price')
            if price is None:
                continue
            try:
                self.db.upsert_daily_price(symbol, float(price), price_date)
            except Exception as err:
                print(f'[WARN] Failed to persist closing price for {symbol}: {err}')

    def get_prices(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict]:
        """Return prices respecting configured trading hours"""
        now = datetime.now()
        market_open = self.is_within_trading_window(now)

        if not market_open and self._last_market_open_state:
            self._persist_closing_prices()

        self._last_market_open_state = market_open

        if market_open:
            live_prices = self.get_current_prices(symbols)
            if live_prices:
                for payload in live_prices.values():
                    payload['source'] = 'live'
                    payload['price_date'] = now.strftime('%Y-%m-%d')
                self._last_live_prices = live_prices
                self._last_live_date = now.date()
            return live_prices

        stored_prices = self.db.get_latest_daily_prices(symbols)
        formatted = self._format_stored_prices(stored_prices, symbols)

        target_symbols = symbols or [stock['symbol'] for stock in self._get_configured_stocks()]
        missing_symbols = [sym for sym in target_symbols if sym not in formatted]

        if missing_symbols:
            live_prices = self.get_current_prices(missing_symbols)
            if live_prices:
                price_date = now.strftime('%Y-%m-%d')
                if not self._last_live_prices:
                    self._last_live_prices = {}
                for symbol, payload in live_prices.items():
                    payload['source'] = 'live_fallback'
                    payload['price_date'] = price_date
                    formatted[symbol] = payload
                    self._last_live_prices[symbol] = payload.copy()
                    try:
                        self.db.upsert_daily_price(symbol, float(payload.get('price', 0)), price_date)
                    except Exception as err:
                        print(f'[WARN] Failed to persist fallback price for {symbol}: {err}')
                self._last_live_date = now.date()

        # Fallback to most recent live snapshot if still no data
        if not formatted and self._last_live_prices:
            fallback: Dict[str, Dict] = {}
            for symbol, payload in self._last_live_prices.items():
                if symbols and symbol not in symbols:
                    continue
                fallback[symbol] = {
                    **payload,
                    'source': payload.get('source', 'previous_live'),
                    'price_date': payload.get('price_date') or (self._last_live_date.strftime('%Y-%m-%d') if self._last_live_date else None)
                }
            return fallback

        return formatted

    def _format_sina_symbol(self, stock: Dict) -> str:
        exchange = stock.get('exchange', '').lower()
        if exchange in ('xshg', 'sh', 'sse'):
            prefix = 'sh'
        elif exchange in ('xshe', 'sz', 'szse'):
            prefix = 'sz'
        else:
            prefix = 'sh' if stock['symbol'].startswith('6') else 'sz'
        return f"{prefix}{stock['symbol']}"

    def get_current_prices(self, symbols: List[str] = None) -> Dict[str, Dict]:
        """Get current prices for configured stocks via Sina API"""
        stocks = self._get_configured_stocks()
        if not stocks:
            return {}

        if symbols:
            stocks = [s for s in stocks if s['symbol'] in symbols]

        if not stocks:
            return {}

        cache_key = 'prices_' + '_'.join(sorted([s['symbol'] for s in stocks]))
        if cache_key in self._cache:
            if time.time() - self._cache_time[cache_key] < self._cache_duration:
                return self._cache[cache_key]

        sina_symbols = [self._format_sina_symbol(stock) for stock in stocks]
        prices = {}

        try:
            url = 'https://hq.sinajs.cn/list=' + ','.join(sina_symbols)
            resp = self.session.get(url, timeout=5)
            resp.encoding = 'gbk'
            lines = resp.text.strip().split('\n')
            for line, stock in zip(lines, stocks):
                parts = line.split('=')
                if len(parts) != 2 or not parts[1].strip().strip(';').strip('"'):
                    continue
                data_str = parts[1].strip().strip(';')
                data_str = data_str.strip('"')
                fields = data_str.split(',')
                if len(fields) < 4:
                    continue
                try:
                    price = float(fields[3])
                    prev_close = float(fields[2]) if fields[2] else 0
                except ValueError:
                    price = 0
                    prev_close = 0
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
                prices[stock['symbol']] = {
                    'price': price,
                    'name': fields[0] or stock['name'],
                    'exchange': stock['exchange'],
                    'change_24h': change_pct
                }

            self._cache[cache_key] = prices
            self._cache_time[cache_key] = time.time()
            return prices
        except Exception as e:
            print(f'[ERROR] Sina price fetch failed: {e}')
            return {stock['symbol']: {'price': 0, 'name': stock['name'], 'exchange': stock['exchange']} for stock in stocks}

        # ====== JQData 实现保留 ======
        # try:
        #     price_data = get_price(api_symbols, count=1, frequency='1m', fields=['close'], fq='none')
        # except Exception as e:
        #     print(f'[ERROR] JQData price fetch failed: {e}')

    def get_market_data(self, symbol: str) -> Dict:
        stocks = {stock['symbol']: stock for stock in self._get_configured_stocks()}
        if symbol not in stocks:
            return {}
        api_symbol = stocks[symbol]['api_symbol']

        try:
            prices = self.get_prices([symbol])
            if symbol not in prices:
                return {}
            price_info = prices[symbol]
            return {
                'current_price': price_info.get('price', 0),
                'high': price_info.get('price', 0),
                'low': price_info.get('price', 0)
            }
        except Exception as e:
            print(f'[ERROR] Failed to get market data for {symbol}: {e}')
            return {}

    def get_historical_prices(self, symbol: str, count: int = 60) -> List[Dict]:
        stocks = {stock['symbol']: stock for stock in self._get_configured_stocks()}
        if symbol not in stocks:
            return []
        api_symbol = stocks[symbol]['api_symbol']

        try:
            sina_symbol = self._format_sina_symbol({'symbol': symbol, 'exchange': stocks[symbol]['exchange']})
            url = (
                'https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData'
                f'?symbol={sina_symbol}&scale=240&ma=no&datalen={count}'
            )
            resp = self.session.get(url, timeout=5)
            text = resp.text.strip()

            # Sina JSONP responses sometimes have "var=" and trailing semicolons or comments
            if text.endswith(';'):
                text = text[:-1]
            while text.startswith('/*'):
                end_comment = text.find('*/')
                if end_comment == -1:
                    break
                text = text[end_comment + 2:].lstrip()
            if '=' in text:
                text = text.split('=', 1)[1].strip()
            if text.startswith('(') and text.endswith(')'):
                text = text[1:-1].strip()

            if not text or text in ('null', '[]'):  # invalid/empty payload
                raise ValueError('Empty historical data payload')

            data = json.loads(text)
            return [
                {'timestamp': item['day'], 'price': float(item['close'])}
                for item in data if 'close' in item and item.get('day')
            ]
        except json.JSONDecodeError as e:
            print(f'[ERROR] Failed to parse historical prices for {symbol}: {e} | payload={resp.text[:120]}')
            return []
        except Exception as e:
            print(f'[ERROR] Failed to get historical prices for {symbol}: {e}')
            return []

    def calculate_technical_indicators(self, symbol: str) -> Dict:
        history = self.get_historical_prices(symbol, count=60)
        if not history:
            return {}

        prices = [item['price'] for item in history]
        if len(prices) < 14:
            return {}

        sma_5 = sum(prices[-5:]) / 5
        sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else sum(prices) / len(prices)

        # RSI 14
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [change if change > 0 else 0 for change in changes]
        losses = [-change if change < 0 else 0 for change in changes]
        avg_gain = sum(gains[-14:]) / 14
        avg_loss = sum(losses[-14:]) / 14
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        pct_change_5 = ((prices[-1] - prices[-5]) / prices[-5]) * 100 if prices[-5] else 0
        pct_change_20 = ((prices[-1] - prices[-20]) / prices[-20]) * 100 if len(prices) >= 20 and prices[-20] else 0

        return {
            'sma_5': sma_5,
            'sma_20': sma_20,
            'rsi_14': rsi,
            'change_5d': pct_change_5,
            'change_20d': pct_change_20,
            'current_price': prices[-1]
        }

