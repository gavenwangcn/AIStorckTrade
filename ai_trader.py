import json
from typing import Dict, Optional, Tuple
from openai import OpenAI, APIConnectionError, APIError

class AITrader:
    def __init__(self, provider_type: str, api_key: str, api_url: str, model_name: str):
        self.provider_type = provider_type.lower()
        self.api_key = api_key
        self.api_url = api_url
        self.model_name = model_name
    
    def make_decision(self, market_state: Dict, portfolio: Dict, 
                     account_info: Dict) -> Dict:
        prompt = self._build_prompt(market_state, portfolio, account_info)
        
        response = self._call_llm(prompt)
        
        decisions, cot_trace = self._parse_response(response)
        
        return {
            'decisions': decisions,
            'prompt': prompt,
            'raw_response': response,
            'cot_trace': cot_trace
        }
    
    def _build_prompt(self, market_state: Dict, portfolio: Dict, 
                     account_info: Dict) -> str:
        prompt = """你是一名专业的A股量化交易员，负责在合规前提下为账户制定交易计划。

市场行情 (价格单位：人民币)：
"""
        for symbol, data in market_state.items():
            price = data.get('price', 0)
            info = f"{symbol}: {price:.2f}元"
            change_5d = data.get('indicators', {}).get('change_5d') if data.get('indicators') else None
            change_20d = data.get('indicators', {}).get('change_20d') if data.get('indicators') else None
            if change_5d is not None:
                info += f" | 5日涨跌: {change_5d:+.2f}%"
            if change_20d is not None:
                info += f" | 20日涨跌: {change_20d:+.2f}%"
            prompt += info + "\n"
            indicators = data.get('indicators')
            if indicators:
                prompt += (
                    f"  SMA5: {indicators.get('sma_5', 0):.2f}, SMA20: {indicators.get('sma_20', 0):.2f}, "
                    f"RSI14: {indicators.get('rsi_14', 0):.1f}\n"
                )
        
        prompt += f"""
账户状态:
- 初始资金: ¥{account_info['initial_capital']:.2f}
- 账户总值: ¥{portfolio['total_value']:.2f}
- 可用现金: ¥{portfolio['cash']:.2f}
- 总收益率: {account_info['total_return']:.2f}%

当前持仓:
"""
        if portfolio['positions']:
            for pos in portfolio['positions']:
                prompt += f"- {pos['coin']} {pos['side']} {pos['quantity']:.2f} 股 @ ¥{pos['avg_price']:.2f}\n"
        else:
            prompt += "None\n"
        
        prompt += """
交易约束:
1. 仅允许 buy_to_enter (买入开仓)、close_position (卖出平仓)、hold (观望)。暂不支持融券做空。
2. 保持持仓数量≤3，只在具备明显优势时开新仓。
3. 单笔投入资金≤可用现金的5%，以整数股下单；若模型给出的数量超出可承受范围，需要下调到最大可买数量。
4. 设置止盈/止损与理由，综合价格动量(SMA)、RSI、基本趋势等因素。
5. 优先考虑高流动性标的，避免日内频繁换手；默认T+1规则，平仓意图需说明。

仅输出以下 JSON 结构，不要添加额外文本:
```
{
  "cot_trace": [
    "步骤1：……",
    "步骤2：……"
  ],
  "decisions": {
    "600519": {
      "signal": "buy_to_enter|close_position|hold",
      "quantity": 100,
      "confidence": 0.75,
      "risk_budget_pct": 3,
      "profit_target": 2100.0,
      "stop_loss": 1950.0,
      "justification": "理由"
    }
  }
}
```

说明:
- `cot_trace` 用于记录3-5步推理过程，可为字符串数组。
- `decisions` 字段同上，只列出需要动作的股票。
"""
        
        return prompt
    
    def _call_llm(self, prompt: str) -> str:
        """Call LLM API based on provider type"""
        # OpenAI-compatible providers (same format)
        if self.provider_type in ['openai', 'azure_openai', 'deepseek']:
            return self._call_openai_api(prompt)
        elif self.provider_type == 'anthropic':
            return self._call_anthropic_api(prompt)
        elif self.provider_type == 'gemini':
            return self._call_gemini_api(prompt)
        else:
            # Default to OpenAI-compatible API
            return self._call_openai_api(prompt)
    
    def _call_openai_api(self, prompt: str) -> str:
        """Call OpenAI-compatible API"""
        try:
            base_url = self.api_url.rstrip('/')
            if not base_url.endswith('/v1'):
                if '/v1' in base_url:
                    base_url = base_url.split('/v1')[0] + '/v1'
                else:
                    base_url = base_url + '/v1'
            
            client = OpenAI(
                api_key=self.api_key,
                base_url=base_url
            )
            
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional Chinese A-share equity trader. Output JSON format only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=2000
            )
            
            return response.choices[0].message.content
            
        except APIConnectionError as e:
            error_msg = f"API connection failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            raise Exception(error_msg)
        except APIError as e:
            error_msg = f"API error ({e.status_code}): {e.message}"
            print(f"[ERROR] {error_msg}")
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"OpenAI API call failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            import traceback
            print(traceback.format_exc())
            raise Exception(error_msg)
    
    def _call_anthropic_api(self, prompt: str) -> str:
        """Call Anthropic Claude API"""
        try:
            import requests
            
            base_url = self.api_url.rstrip('/')
            if not base_url.endswith('/v1'):
                base_url = base_url + '/v1'
            
            url = f"{base_url}/messages"
            headers = {
                'Content-Type': 'application/json',
                'x-api-key': self.api_key,
                'anthropic-version': '2023-06-01'
            }
            
            data = {
                "model": self.model_name,
                "max_tokens": 2000,
                "system": "You are a professional Chinese A-share equity trader. Output JSON format only.",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            return result['content'][0]['text']
            
        except Exception as e:
            error_msg = f"Anthropic API call failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            import traceback
            print(traceback.format_exc())
            raise Exception(error_msg)
    
    def _call_gemini_api(self, prompt: str) -> str:
        """Call Google Gemini API"""
        try:
            import requests
            
            base_url = self.api_url.rstrip('/')
            if not base_url.endswith('/v1'):
                base_url = base_url + '/v1'
            
            url = f"{base_url}/{self.model_name}:generateContent"
            headers = {
                'Content-Type': 'application/json'
            }
            params = {'key': self.api_key}
            
            data = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"You are a professional Chinese A-share equity trader. Output JSON format only.\n\n{prompt}"
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 2000
                }
            }
            
            response = requests.post(url, headers=headers, params=params, json=data, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            return result['candidates'][0]['content']['parts'][0]['text']
            
        except Exception as e:
            error_msg = f"Gemini API call failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            import traceback
            print(traceback.format_exc())
            raise Exception(error_msg)
    
    
    def _parse_response(self, response: str) -> Tuple[Dict, Optional[str]]:
        response = response.strip()
        
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        
        cot_trace = None
        decisions: Dict = {}
        try:
            parsed = json.loads(response.strip())
            if isinstance(parsed, dict) and 'decisions' in parsed:
                cot_trace = parsed.get('cot_trace')
                decisions = parsed.get('decisions') or {}
            elif isinstance(parsed, dict):
                decisions = parsed
            else:
                decisions = {}
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parse failed: {e}")
            print(f"[DATA] Response:\n{response}")
            decisions = {}
        
        if not isinstance(decisions, dict):
            decisions = {}
        
        return decisions, self._stringify_cot_trace(cot_trace)

    def _stringify_cot_trace(self, cot_trace) -> Optional[str]:
        if cot_trace is None:
            return None
        if isinstance(cot_trace, str):
            return cot_trace.strip() or None
        if isinstance(cot_trace, (list, tuple)):
            cleaned = []
            for item in cot_trace:
                if isinstance(item, str):
                    step = item.strip()
                    if step:
                        cleaned.append(step)
                else:
                    cleaned.append(json.dumps(item, ensure_ascii=False))
            return '\n'.join(cleaned) or None
        try:
            return json.dumps(cot_trace, ensure_ascii=False)
        except TypeError:
            return str(cot_trace)
