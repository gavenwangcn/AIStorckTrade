from datetime import datetime
from typing import Dict
import json

class TradingEngine:
    def __init__(self, model_id: int, db, market_fetcher, ai_trader, trade_fee_rate: float = 0.001):
        self.model_id = model_id
        self.db = db
        self.market_fetcher = market_fetcher
        self.ai_trader = ai_trader
        self.trade_fee_rate = trade_fee_rate  # 从配置中传入费率
        self.max_positions = 3

    def _get_tracked_symbols(self):
        return [stock['symbol'] for stock in self.db.get_stock_configs()]
    
    def execute_trading_cycle(self) -> Dict:
        try:
            if not self.market_fetcher.is_within_trading_window():
                return {
                    'success': False,
                    'error': '当前不在自动交易时间窗口，AI交易已暂停',
                    'skipped': True
                }

            market_state = self._get_market_state()
            
            current_prices = {symbol: market_state[symbol]['price'] for symbol in market_state}
            
            portfolio = self.db.get_portfolio(self.model_id, current_prices)
            
            account_info = self._build_account_info(portfolio)
            
            decision_payload = self.ai_trader.make_decision(
                market_state, portfolio, account_info
            )

            decisions = decision_payload.get('decisions') or {}
            if not isinstance(decisions, dict):
                decisions = {}

            prompt = decision_payload.get('prompt')
            if not prompt:
                prompt = self._format_prompt(market_state, portfolio, account_info)

            raw_response = decision_payload.get('raw_response')
            if not isinstance(raw_response, str):
                raw_response = json.dumps(decisions, ensure_ascii=False)
            cot_trace = decision_payload.get('cot_trace') or ''

            self.db.add_conversation(
                self.model_id,
                user_prompt=prompt,
                ai_response=raw_response,
                cot_trace=cot_trace
            )
            
            execution_results = self._execute_decisions(decisions, market_state, portfolio)
            
            updated_portfolio = self.db.get_portfolio(self.model_id, current_prices)
            self.db.record_account_value(
                self.model_id,
                updated_portfolio['total_value'],
                updated_portfolio['cash'],
                updated_portfolio['positions_value']
            )
            
            return {
                'success': True,
                'decisions': decisions,
                'executions': execution_results,
                'portfolio': updated_portfolio
            }
            
        except Exception as e:
            print(f"[ERROR] Trading cycle failed (Model {self.model_id}): {e}")
            import traceback
            print(traceback.format_exc())
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_market_state(self) -> Dict:
        market_state = {}
        symbols = self._get_tracked_symbols()
        prices = self.market_fetcher.get_prices(symbols)
        
        for symbol in symbols:
            price_info = prices.get(symbol)
            if price_info:
                market_state[symbol] = price_info.copy()
                indicators = self.market_fetcher.calculate_technical_indicators(symbol)
                market_state[symbol]['indicators'] = indicators

        return market_state
    
    def _build_account_info(self, portfolio: Dict) -> Dict:
        model = self.db.get_model(self.model_id)
        initial_capital = model['initial_capital']
        total_value = portfolio['total_value']
        total_return = ((total_value - initial_capital) / initial_capital) * 100
        
        return {
            'current_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_return': total_return,
            'initial_capital': initial_capital
        }
    
    def _format_prompt(self, market_state: Dict, portfolio: Dict, 
                      account_info: Dict) -> str:
        return f"Market State: {len(market_state)} stocks, Portfolio: {len(portfolio['positions'])} positions"
    
    def _execute_decisions(self, decisions: Dict, market_state: Dict, 
                          portfolio: Dict) -> list:
        results = []
        
        tracked = set(self._get_tracked_symbols())
        positions_map = {pos['coin']: pos for pos in portfolio.get('positions', [])}

        for symbol, decision in decisions.items():
            if symbol not in tracked:
                continue
            
            signal = decision.get('signal', '').lower()
            
            try:
                if signal == 'buy_to_enter':
                    result = self._execute_buy(symbol, decision, market_state, portfolio)
                elif signal == 'sell_to_enter':
                    result = {'coin': symbol, 'error': 'A股账户暂不支持做空'}
                elif signal == 'close_position':
                    if symbol not in positions_map:
                        result = {'coin': symbol, 'error': 'No position to close'}
                    else:
                        result = self._execute_close(symbol, decision, market_state, portfolio)
                elif signal == 'hold':
                    result = {'coin': symbol, 'signal': 'hold', 'message': '保持观望'}
                else:
                    result = {'coin': symbol, 'error': f'Unknown signal: {signal}'}
                
                results.append(result)
                
            except Exception as e:
                results.append({'coin': symbol, 'error': str(e)})
        
        return results
    
    def _execute_buy(self, symbol: str, decision: Dict, market_state: Dict, 
                    portfolio: Dict) -> Dict:
        quantity = decision.get('quantity', 0)
        leverage = int(decision.get('leverage', 1))
        price = market_state[symbol]['price']
        
        positions = portfolio.get('positions', [])
        existing_symbols = {pos['coin'] for pos in positions}
        if symbol not in existing_symbols and len(existing_symbols) >= self.max_positions:
            return {'coin': symbol, 'error': '达到最大持仓数量，无法继续开仓'}

        max_affordable_qty = int(portfolio['cash'] / (price * (1 + self.trade_fee_rate)))
        risk_pct = float(decision.get('risk_budget_pct', 3)) / 100
        risk_pct = min(max(risk_pct, 0.01), 0.05)
        risk_based_qty = int((portfolio['cash'] * risk_pct) / (price * (1 + self.trade_fee_rate)))

        quantity = int(quantity)
        if quantity <= 0 or quantity > max_affordable_qty:
            quantity = min(max_affordable_qty, risk_based_qty if risk_based_qty > 0 else max_affordable_qty)

        if quantity <= 0:
            return {'coin': symbol, 'error': '现金不足，无法买入'}
        
        trade_amount = quantity * price  # 交易额
        trade_fee = trade_amount * self.trade_fee_rate  # 交易费（0.1%）
        required_margin = (quantity * price) / leverage  # 保证金
        
        # 总需资金 = 保证金 + 交易费
        total_required = required_margin + trade_fee
        if total_required > portfolio['cash']:
            return {'coin': symbol, 'error': '可用资金不足（含手续费）'}
        
        # 更新持仓
        try:
            self.db.update_position(
                self.model_id, symbol, quantity, price, leverage, 'long'
            )
        except Exception as db_err:
            print(f"[TRADE][ERROR] Update position failed (BUY) model={self.model_id} coin={symbol}: {db_err}")
            raise
        
        # 记录交易（包含交易费）
        print(f"[TRADE][PENDING] Model {self.model_id} BUY {symbol} qty={quantity} price={price} fee={trade_fee}")
        try:
            self.db.add_trade(
                self.model_id, symbol, 'buy_to_enter', quantity, 
                price, leverage, 'long', pnl=0, fee=trade_fee  # 新增fee参数
            )
        except Exception as db_err:
            print(f"[TRADE][ERROR] Add trade failed (BUY) model={self.model_id} coin={symbol}: {db_err}")
            raise
        print(f"[TRADE][RECORDED] Model {self.model_id} BUY {symbol}")
        
        return {
            'coin': symbol,
            'signal': 'buy_to_enter',
            'quantity': quantity,
            'price': price,
            'leverage': leverage,
            'fee': trade_fee,  # 返回费用信息
            'message': f'买入 {symbol} {quantity} 股 @ ¥{price:.2f} (手续费: ¥{trade_fee:.2f})'
        }
    
    def _execute_close(self, symbol: str, decision: Dict, market_state: Dict, 
                    portfolio: Dict) -> Dict:
        position = None
        for pos in portfolio['positions']:
            if pos['coin'] == symbol:
                position = pos
                break
        
        if not position:
            return {'coin': symbol, 'error': 'Position not found'}
        
        current_price = market_state[symbol]['price']
        entry_price = position['avg_price']
        quantity = position['quantity']
        side = position['side']
        
        # 计算平仓利润（未扣费）
        if side == 'long':
            gross_pnl = (current_price - entry_price) * quantity
        else:  # short
            gross_pnl = (entry_price - current_price) * quantity
        
        # 计算平仓交易费（按平仓时的交易额）
        trade_amount = quantity * current_price
        trade_fee = trade_amount * self.trade_fee_rate
        net_pnl = gross_pnl - trade_fee  # 净利润 = 毛利润 - 交易费
        
        # 关闭持仓
        try:
            self.db.close_position(self.model_id, symbol, side)
        except Exception as db_err:
            print(f"[TRADE][ERROR] Close position failed model={self.model_id} coin={symbol}: {db_err}")
            raise
        
        # 记录平仓交易（包含费用和净利润）
        print(f"[TRADE][PENDING] Model {self.model_id} CLOSE {symbol} side={side} qty={quantity} price={current_price} fee={trade_fee} net_pnl={net_pnl}")
        try:
            self.db.add_trade(
                self.model_id, symbol, 'close_position', quantity,
                current_price, position['leverage'], side, pnl=net_pnl, fee=trade_fee  # 新增fee参数
            )
        except Exception as db_err:
            print(f"[TRADE][ERROR] Add trade failed (CLOSE) model={self.model_id} coin={symbol}: {db_err}")
            raise
        print(f"[TRADE][RECORDED] Model {self.model_id} CLOSE {symbol}")
        
        return {
            'coin': symbol,
            'signal': 'close_position',
            'quantity': quantity,
            'price': current_price,
            'pnl': net_pnl,
            'fee': trade_fee,
            'message': f'平仓 {symbol}, 毛收益 ¥{gross_pnl:.2f}, 手续费 ¥{trade_fee:.2f}, 净收益 ¥{net_pnl:.2f}'
        }
