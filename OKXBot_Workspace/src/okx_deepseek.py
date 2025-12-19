import os
import time
import schedule
from openai import OpenAI
import ccxt
import pandas as pd
from datetime import datetime
import json
import emoji
import logging
import requests
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

import sys
from logging.handlers import RotatingFileHandler

"""
🤖 CryptoOracle: AI-Powered Quantitative Trading System
=====================================================

This system integrates DeepSeek-V3 LLM with CCXT to perform intelligent crypto trading.

Key Components:
1. **DeepSeekTrader**: Manages individual symbol trading logic, indicators (RSI, MACD, ADX), and AI analysis.
2. **RiskManager**: Global risk controller that monitors total equity and enforces take-profit/stop-loss.
3. **Execution Engine**: Handles order placement, smart routing (Spot/Swap), and anti-slippage checks.

Features:
- Adaptive AI Persona (Trend/Grid/Defensive)
- Triple-Layer Risk Control (Config/AI/Balance)
- Smart PnL Baseline (Auto-calibration)
- Omni-Channel Notifications (Webhook)

Author: Riemann
License: CC-BY-NC-SA-4.0 (Attribution-NonCommercial-ShareAlike 4.0 International)
"""

# 配置日志
# [新增] 确保 log 文件夹存在 (在项目根目录下)
# 向上跳两级目录，从 src/okx_deepseek.py 跳到项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log_dir = os.path.join(project_root, "log")

if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_filename = os.path.join(log_dir, f"trading_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            # 使用 RotatingFileHandler 替代 FileHandler
            # maxBytes=10*1024*1024 (10MB), backupCount=5 (保留5个备份)
            RotatingFileHandler(log_filename, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'),
            # 添加 StreamHandler 以便在控制台显示日志，不再需要单独的 print
            logging.StreamHandler()
        ]
    )

    # 过滤 httpx 的 INFO 日志
logging.getLogger("httpx").setLevel(logging.WARNING)
# [已通过 plot_pnl 修复字体配置，此处无需强行过滤]
# logging.getLogger("matplotlib").setLevel(logging.ERROR)

class RiskManager:
    """全局风控管理器"""
    def __init__(self, exchange, risk_config, traders):
        self.exchange = exchange
        self.config = risk_config
        self.traders = traders
        self.initial_balance = risk_config.get('initial_balance_usdt', 0)
        
        # 支持绝对金额 和 百分比 两种配置
        self.max_profit = risk_config.get('max_profit_usdt')
        self.max_loss = risk_config.get('max_loss_usdt')
        
        # [新增] 百分比风控配置 (优先级低于绝对金额)
        self.max_profit_pct = risk_config.get('max_profit_rate') # 例如 0.2 代表 20%
        self.max_loss_pct = risk_config.get('max_loss_rate')     # 例如 0.1 代表 10%
        
        # 智能基准余额
        self.smart_baseline = None
        self.state_file = "bot_state.json"
        
        # 尝试加载历史状态 (防止重启后 PnL 重置)
        self.load_state()
        
        # 通知配置 (复用第一个 trader 的配置)
        self.notification_config = {}
        if traders and hasattr(traders[0], 'notification_config'):
             self.notification_config = traders[0].notification_config

        # [新增] PnL 图表路径配置 (启动时生成唯一文件名，防止覆盖)
        # 确保 png 文件夹在项目根目录下
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.chart_dir = os.path.join(project_root, "png")
        
        if not os.path.exists(self.chart_dir):
            os.makedirs(self.chart_dir)
        # 使用时间戳生成唯一文件名
        self.chart_path = os.path.join(self.chart_dir, f"pnl_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        
        # [新增] 控制战绩显示的频率
        self.last_chart_display_time = 0

    def load_state(self):
        """加载持久化状态"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.smart_baseline = state.get('smart_baseline')
                    if self.smart_baseline:
                        print(f"🔄 已恢复历史基准资金: {self.smart_baseline:.2f} U")
            except Exception as e:
                print(f"⚠️ 加载状态失败: {e}")

    def save_state(self):
        """保存持久化状态"""
        try:
            state = {'smart_baseline': self.smart_baseline}
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"⚠️ 保存状态失败: {e}")

    def _log(self, msg, level='info'):
        # 移除手动 print，统一使用 logging 模块输出到文件和控制台
        # current_time = datetime.now().strftime('%H:%M:%S')
        # formatted_msg = f"[{current_time}] [RISK_MGR] {msg}"
        
        if level == 'info':
            logging.info(f"[RISK_MGR] {msg}")
        elif level == 'error':
            logging.error(f"[RISK_MGR] {msg}")

    def send_notification(self, message):
        """发送通知"""
        if not self.notification_config.get('enabled', False):
            return
        webhook_url = self.notification_config.get('webhook_url')
        if not webhook_url or "YOUR_WEBHOOK" in webhook_url:
            return
        try:
            payload = {
                "msg_type": "text",
                "content": {"text": f"🛡️ CryptoOracle 风控通知\n--------------------\n{message}"},
                "text": f"🛡️ CryptoOracle 风控通知\n{message}" 
            }
            response = requests.post(webhook_url, json=payload, timeout=5)
            # 简单的错误检查
            if response.status_code != 200:
                self._log(f"发送通知失败 HTTP {response.status_code}: {response.text}", 'error')
        except Exception as e:
             self._log(f"发送通知异常: {e}", 'error')

    def record_pnl_to_csv(self, total_equity, current_pnl, pnl_percent):
        """记录盈亏数据到CSV文件"""
        csv_file = "pnl_history.csv"
        file_exists = os.path.isfile(csv_file)
        try:
            with open(csv_file, 'a', encoding='utf-8') as f:
                if not file_exists:
                    f.write("timestamp,total_equity,pnl_usdt,pnl_percent\n")
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp},{total_equity:.2f},{current_pnl:.2f},{pnl_percent:.2f}\n")
            
            # [新增] 每次记录后尝试更新图表
            try:
                import plot_pnl
                # 实时生成但不打印提示
                # [修改] 传入 self.chart_path 确保生成到 png 文件夹且不覆盖
                plot_pnl.generate_pnl_chart(csv_path=csv_file, output_path=self.chart_path, verbose=False)
                # 日志确认 (plot_pnl 已经打印了✅，这里只记录到 log 文件)
                logging.info(f"盈亏折线图已更新: {self.chart_path} (Timestamp: {timestamp})")
            except Exception as e:
                self._log(f"生成折线图失败: {e}", 'warning')

        except Exception as e:
            self._log(f"写入CSV失败: {e}", 'error')

    def close_all_traders(self):
        """强制平仓所有交易对"""
        self._log("🛑 正在执行全局清仓...")
        for trader in self.traders:
            try:
                trader.close_all_positions()
            except Exception as e:
                self._log(f"平仓 {trader.symbol} 失败: {e}", 'error')

    def display_pnl_history(self):
        """显示最近的盈亏趋势 (ASCII图表)"""
        csv_file = "pnl_history.csv"
        
        # [新增] 如果本地没有历史文件，尝试扫描 logs 目录下的历史日志来恢复（高级功能，暂留接口）
        if not os.path.isfile(csv_file):
            msg = "📜 暂无历史战绩 (pnl_history.csv 不存在)"
            print(msg)
            logging.info(msg)
            return
            
        try:
            df = pd.read_csv(csv_file)
            if df.empty:
                msg = "📜 暂无历史战绩 (记录为空)"
                print(msg)
                logging.info(msg)
                return
            
            # [新增] 打印表头
            header = "\n" + "="*40 + f"\n📜 历史战绩回顾 (共 {len(df)} 条记录)\n" + "="*40
            print(header)
            logging.info(header)
            
            # [新增] 动态计算缩放比例
            recent = df.tail(10) # 显示最近 10 条
            max_pnl = recent['pnl_usdt'].abs().max()
            scale_factor = 1.0
            
            # 基础比例：1U = 1格
            if max_pnl > 0:
                if max_pnl < 1.5:
                    scale_factor = 10.0 # 0.1U = 1格
                elif max_pnl < 5:
                    scale_factor = 2.0  # 0.5U = 1格
                elif max_pnl > 20:
                    scale_factor = 0.5  # 2U = 1格
            
            unit_val = 1.0 / scale_factor
            chart_header = f"📈 最近 {len(recent)} 次盈亏记录 (当前比例: 1格 ≈ {unit_val:.1f} U)\n" + "="*30
            print(chart_header)
            logging.info(chart_header)
            
            for _, row in recent.iterrows():
                timestamp = row['timestamp'][5:-3] # 只显示 MM-DD HH:MM
                pnl = row['pnl_usdt']
                bar = ""
                
                # 计算应显示的格数 (浮点数)
                num_blocks = abs(pnl) * scale_factor
                full_blocks = int(num_blocks)
                
                if pnl > 0:
                    if full_blocks == 0 and num_blocks > 0.1: # 微利 (>0.1格)
                        bar = "▫️" 
                    else:
                        bar = "🟩" * min(full_blocks, 20)
                elif pnl < 0:
                    if full_blocks == 0 and num_blocks > 0.1: # 微亏 (>0.1格)
                        bar = "▪️"
                    else:
                        bar = "🟥" * min(full_blocks, 20)
                else:
                    bar = "➖"
                
                line = f"{timestamp} | {pnl:>6.2f} U | {bar}"
                print(line)
                logging.info(line)
            
            footer = "="*30 + "\n"
            print(footer)
            logging.info(footer)
        except Exception:
            pass

    def check(self):
        """执行风控检查"""
        try:
            # 1. 获取账户权益 (精准锚定 USDT，隔离编外资产波动)
            balance = self.exchange.fetch_balance()
            total_equity = 0
            found_usdt = False

            # A. 针对 OKX 统一账户，遍历 details 寻找 USDT 专属权益
            if 'info' in balance and 'data' in balance['info']:
                for asset in balance['info']['data'][0]['details']:
                    if asset['ccy'] == 'USDT':
                        # eq = 币种总权益 (余额 + 未实现盈亏)
                        total_equity = float(asset['eq'])
                        found_usdt = True
                        break
            
            # B. 针对普通账户或作为降级方案
            if not found_usdt:
                if 'USDT' in balance and 'equity' in balance['USDT']:
                    total_equity = float(balance['USDT']['equity'])
                elif 'USDT' in balance and 'total' in balance['USDT']:
                     # 只有现货余额的情况
                     total_equity = float(balance['USDT']['total'])
            
            if total_equity <= 0:
                return

            # [智能基准] 初始化 (仅一次，如果尚未初始化)
            if self.smart_baseline is None:
                self.initialize_baseline(total_equity)
            
            # 修正后续计算用的 total_equity (必须包含持仓市值)
            current_total_value = total_equity
            
            # [优化] 批量获取价格，减少API调用
            symbols_to_fetch = [t.symbol for t in self.traders if t.trade_mode == 'cash']
            prices = {}
            if symbols_to_fetch:
                try:
                    tickers = self.exchange.fetch_tickers(symbols_to_fetch)
                    for s, t in tickers.items():
                        prices[s] = t['last']
                except:
                    pass

            for trader in self.traders:
                if trader.trade_mode == 'cash':
                        spot_bal = trader.get_spot_balance()
                        if spot_bal > 0:
                            price = prices.get(trader.symbol, 0)
                            # 如果批量获取失败，回退到单个获取
                            if price == 0:
                                try:
                                    ticker = self.exchange.fetch_ticker(trader.symbol)
                                    price = ticker['last']
                                except:
                                    pass
                            current_total_value += spot_bal * price

            # 2. 计算盈亏
            if not self.smart_baseline or self.smart_baseline <= 0:
                return

            current_pnl = current_total_value - self.smart_baseline
            pnl_percent = (current_pnl / self.smart_baseline) * 100

            self._log(f"💰 账户监控: 基准 {self.smart_baseline:.2f} U | 当前总值 {current_total_value:.2f} U | 盈亏 {current_pnl:+.2f} U ({pnl_percent:+.2f}%)")
            self.record_pnl_to_csv(current_total_value, current_pnl, pnl_percent)
            
            # [新增] 每隔 1 小时 (3600秒) 自动打印一次详细战绩表，防止刷屏
            if time.time() - self.last_chart_display_time > 3600:
                self.display_pnl_history()
                self.last_chart_display_time = time.time()
            
            # --- 止盈逻辑 ---
            should_take_profit = False
            tp_trigger_msg = ""
            
            # 1. 绝对金额止盈
            if self.max_profit and current_pnl >= self.max_profit:
                should_take_profit = True
                tp_trigger_msg = f"盈利金额达标 (+{current_pnl:.2f} U >= {self.max_profit} U)"
            # 2. 百分比止盈 (如果未触发绝对金额)
            elif self.max_profit_pct and pnl_percent >= (self.max_profit_pct * 100):
                should_take_profit = True
                tp_trigger_msg = f"盈利比例达标 (+{pnl_percent:.2f}% >= {self.max_profit_pct*100}%)"

            if should_take_profit:
                self._log(f"🎉🎉🎉 {tp_trigger_msg}")
                self.close_all_traders()
                self.send_notification(f"🎉 止盈退出\n{tp_trigger_msg}\n当前权益: {total_equity:.2f} U")
                print(emoji.emojize(":money_bag: 恭喜发财！机器人已止盈退出。"))
                sys.exit(0)

            # --- 止损逻辑 ---
            should_stop_loss = False
            sl_trigger_msg = ""
            
            # 1. 绝对金额止损
            if self.max_loss and current_pnl <= -self.max_loss:
                should_stop_loss = True
                sl_trigger_msg = f"亏损金额触线 ({current_pnl:.2f} U <= -{self.max_loss} U)"
            # 2. 百分比止损
            elif self.max_loss_pct and pnl_percent <= -(self.max_loss_pct * 100):
                should_stop_loss = True
                sl_trigger_msg = f"亏损比例触线 ({pnl_percent:.2f}% <= -{self.max_loss_pct*100}%)"

            if should_stop_loss:
                self._log(f"😭😭😭 {sl_trigger_msg}")
                self.close_all_traders()
                self.send_notification(f"🚑 止损退出\n{sl_trigger_msg}\n当前权益: {total_equity:.2f} U")
                print(emoji.emojize(":ambulance: 触发风控熔断！机器人已止损退出。"))
                sys.exit(0)

        except Exception as e:
            self._log(f"检查全局盈亏失败: {e}", 'error')

    def initialize_baseline(self, current_usdt_equity):
        """初始化基准资金并打印资产报表"""
        # [修改] 使用 logging.info 确保写入文件，同时格式化为表格
        sep_line = "-" * 100
        header = f"\n{sep_line}\n📊 资产初始化盘点 (Asset Initialization)\n{sep_line}"
        table_header = f"{'交易对':<18} | {'分配比例':<8} | {'理论配额(U)':<12} | {'持仓数量':<10} | {'持仓市值(U)':<12} | {'占用%':<6} | {'成本':<10} | {'估算盈亏'}"
        
        # 先打印头部
        print(header)
        print(table_header)
        print(sep_line)
        logging.info(header)
        logging.info(table_header)
        logging.info(sep_line)
        
        total_position_value = 0.0
        
        # 批量获取价格
        symbols = [t.symbol for t in self.traders]
        prices = {}
        try:
            tickers = self.exchange.fetch_tickers(symbols)
            for s, t in tickers.items():
                prices[s] = t['last']
        except:
            pass

        # 遍历所有 trader 计算持仓市值
        for trader in self.traders:
            # 1. 计算理论分配额度
            quota = 0.0
            allocation_str = "N/A"
            
            if trader.initial_balance and trader.initial_balance > 0:
                if trader.allocation <= 1.0:
                    quota = trader.initial_balance * trader.allocation
                    allocation_str = f"{trader.allocation*100:.0f}%"
                else:
                    quota = trader.allocation
                    allocation_str = "Fixed"
            
            # 2. 计算当前持仓和市值
            holding_amount = 0.0
            position_val = 0.0
            
            current_price = prices.get(trader.symbol, 0)
            if current_price == 0:
                try:
                    # 回退到 K 线获取
                    ohlcv = trader.get_ohlcv()
                    if ohlcv:
                        current_price = ohlcv['price']
                except:
                    pass
                
            if trader.trade_mode == 'cash':
                holding_amount = trader.get_spot_balance()
                if holding_amount > 0 and current_price > 0:
                    position_val = holding_amount * current_price
                    # 累加到总持仓市值 (仅现货模式需要加回 USDT 余额)
                    total_position_value += position_val
                    
            else:
                # 合约模式
                pos = trader.get_current_position()
                if pos:
                    holding_amount = pos['size']
                    # 合约模式下不累加到 total_position_value (通常 USDT 余额已包含权益)
                    pass

            # 3. 计算占用比例
            usage_pct = 0.0
            if quota > 0:
                usage_pct = (position_val / quota) * 100
            
            # 获取持仓均价
            entry_price = trader.get_avg_entry_price()
            entry_price_str = f"{entry_price:.4f}" if entry_price > 0 else "N/A"
            
            # 计算单币种估算盈亏 (仅供参考)
            pnl_est_str = "-"
            if entry_price > 0 and holding_amount > 0 and current_price > 0:
                raw_pnl = (current_price - entry_price) * holding_amount
                pnl_est_str = f"{raw_pnl:+.2f} U"

            # [修改] 打印每一行
            row_str = f"{trader.symbol:<18} | {allocation_str:<8} | {quota:<12.2f} | {holding_amount:<10.4f} | {position_val:<12.2f} | {usage_pct:>5.1f}% | {entry_price_str:<10} | {pnl_est_str}"
            print(row_str)
            logging.info(row_str)

        print(sep_line)
        logging.info(sep_line)
        
        real_total_equity = current_usdt_equity + total_position_value
        
        # 如果没有历史状态，才进行初始化逻辑
        # (如果已经从 load_state 恢复了 smart_baseline，这里可以跳过重置，除非差异巨大)
        if self.initial_balance and self.initial_balance > 0:
            gap_percent = abs(real_total_equity - self.initial_balance) / self.initial_balance * 100
            # 如果偏差太大 (>10%)，说明可能亏损了或者充值了，重置基准
            if gap_percent > 10.0:
                self.smart_baseline = real_total_equity
                self._log(f"⚠️ 初始本金校准: 配置 {self.initial_balance} vs 实际总值 {real_total_equity:.2f} (含持仓)")
                self._log(f"   (差异 > 10%: 检测到资金变动或币种配置更换)")
                self._log(f"🔄 已校准盈亏计算基准为: {self.smart_baseline:.2f} U (交易配额仍保持: {self.initial_balance:.2f} U)")
            else:
                # 偏差不大，说明只是微小波动，沿用配置的本金，保证统计连续性
                # 如果之前没有保存过 baseline，才使用配置值
                if not self.smart_baseline:
                    self.smart_baseline = self.initial_balance
                    self._log(f"✅ 初始本金校准通过: {self.smart_baseline:.2f} U (含持仓)")
                else:
                     # 即使有 baseline，也打印一下确认
                     self._log(f"✅ 延续历史基准: {self.smart_baseline:.2f} U (当前总值 {real_total_equity:.2f} U)")
        else:
            if not self.smart_baseline:
                self.smart_baseline = real_total_equity
        
        # 保存状态
        self.save_state()



class DeepSeekTrader:
    def __init__(self, symbol_config, common_config, exchange, deepseek_client):
        self.symbol = symbol_config['symbol']
        
        # [新增] 支持自动计算 amount (如果配置为 "auto" 或 0)
        # config_amount 用于保存原始配置，amount 用于运行时计算
        self.config_amount = symbol_config.get('amount', 'auto') 
        self.amount = 0 # 将在运行时动态计算，初始为0
        
        self.allocation = symbol_config.get('allocation', 1.0) # 默认为 1.0 (100%)
        self.leverage = symbol_config['leverage']
        
        # 优先读取币种独立的配置，如果没有则使用全局配置
        self.trade_mode = symbol_config.get('trade_mode', common_config.get('trade_mode', 'cross'))
        self.margin_mode = symbol_config.get('margin_mode', common_config.get('margin_mode', 'cross'))
        
        self.timeframe = common_config['timeframe']
        self.test_mode = common_config['test_mode']  #交易模式：cross(全仓) | isolated(逐仓) | cash(现货)
        
        # [新增] 读取高级配置
        self.max_slippage = common_config.get('max_slippage_percent', 1.0)
        self.min_confidence = common_config.get('min_confidence', 'MEDIUM')
        
        # [新增] 读取策略配置 (用于控制 AI 上下文长度)
        strategy_config = common_config.get('strategy', {})
        self.history_limit = strategy_config.get('history_limit', 20) # 发送给AI的最近K线数量
        self.signal_limit = strategy_config.get('signal_limit', 30)   # 保留的历史信号数量
        
        # [新增] 动态止盈止损配置
        self.use_dynamic_tp = strategy_config.get('dynamic_tp', True) 

        # [新增] 动态费率管理 (Auto-detect Fee Rate)
        self.taker_fee_rate = 0.001 # 默认现货 Taker 0.1% (Lv1)
        self.maker_fee_rate = 0.0008 # 默认现货 Maker 0.08%
        self.is_swap = ':' in self.symbol
        
        # 根据默认模式预设初始费率 (作为 fallback)
        if self.is_swap:
            self.taker_fee_rate = 0.0005 # 合约默认 0.05%
            self.maker_fee_rate = 0.0002 # 合约默认 0.02%

        # 全局风控配置 (仅用于计算资金分配，止盈止损已移交给 RiskManager)
        self.risk_control = common_config.get('risk_control', {})
        self.initial_balance = self.risk_control.get('initial_balance_usdt', 0)
        
        # 通知配置
        self.notification_config = common_config.get('notification', {})

        self.exchange = exchange
        self.deepseek_client = deepseek_client
        
        # 独立的交易状态
        self.price_history = []
        self.signal_history = []
        self.position = None
        
        self.setup_leverage()

    def _log(self, msg, level='info'):
        # 移除手动 print，统一使用 logging 模块输出到文件和控制台
        
        if level == 'info':
            logging.info(f"[{self.symbol}] {msg}")
        elif level == 'error':
            logging.error(f"[{self.symbol}] {msg}")

    def send_notification(self, message):
        """发送实时通知 (Webhook)"""
        if not self.notification_config.get('enabled', False):
            return

        webhook_url = self.notification_config.get('webhook_url')
        if not webhook_url or "YOUR_WEBHOOK" in webhook_url:
            return

        try:
            # 适配常见的 JSON Webhook (如飞书, 钉钉自定义机器人, Slack)
            # 飞书/钉钉通常需要 {"msg_type": "text", "content": {"text": "..."}}
            # 但简单的 {"text": "..."} 或 {"content": "..."} 往往也能被很多平台识别
            # 这里采用最通用的结构，针对飞书/钉钉做适配
            
            payload = {
                "msg_type": "text",
                "content": {
                    "text": f"🤖 CryptoOracle 通知 [{self.symbol}]\n--------------------\n{message}"
                },
                # 兼容 Slack/Discord 等
                "text": f"🤖 CryptoOracle 通知 [{self.symbol}]\n{message}" 
            }
            
            requests.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            self._log(f"发送通知失败: {e}", 'error')

    def _to_float(self, value):
        try:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                v = value.strip().replace(',', '')
                if v.lower() in ('n/a', 'na', 'none', ''):
                    return None
                return float(v)
        except Exception:
            return None
        return None

    def _update_amount_auto(self, current_price):
        """[新增] 自动计算合理的 amount"""
        # 如果不是 auto 模式，且配置了有效的数字，直接使用配置值
        if self.config_amount != 'auto' and isinstance(self.config_amount, (int, float)) and self.config_amount > 0:
            self.amount = self.config_amount
            return

        try:
            # 策略：默认单笔使用总配额的 10% ~ 20%，或者至少满足最小交易额
            # 1. 获取该币种的总配额
            quota = 0
            if self.initial_balance > 0:
                if self.allocation <= 1.0:
                    quota = self.initial_balance * self.allocation
                else:
                    quota = self.allocation
            
            if quota <= 0:
                # 如果没有配额信息，默认尝试 10 USDT
                target_usdt = 10.0
            else:
                # 默认单笔为总配额的 10%，分10次建仓
                target_usdt = quota * 0.1
            
            # 2. 获取交易所最小下单金额限制
            market = self.exchange.market(self.symbol)
            min_cost = market.get('limits', {}).get('cost', {}).get('min')
            if min_cost:
                # 确保不低于最小限制 (加 50% 缓冲)
                target_usdt = max(target_usdt, min_cost * 1.5)
            else:
                # 如果获取不到，使用保守值 5 USDT (大多数交易所限制)
                target_usdt = max(target_usdt, 5.0)

            # 3. 换算成币的数量
            raw_amount = target_usdt / current_price
            
            # 4. 精度处理
            precise_amount_str = self.exchange.amount_to_precision(self.symbol, raw_amount)
            self.amount = float(precise_amount_str)
            
            # 5. 打印一次日志 (仅当 amount 变化较大时)
            # self._log(f"🔄 自动计算下单数量: {self.amount} (≈ {target_usdt:.2f} U, 基于配额 {quota:.2f} U)")
            
        except Exception as e:
            self._log(f"自动计算 amount 失败: {e}", 'error')
            self.amount = 0 # 失败则置0，后续逻辑会处理

    def _update_fee_rate(self):
        """[新增] 从交易所 API 自动获取当前 VIP 等级对应的真实费率"""
        try:
            # OKX 支持 fetch_trading_fee 接口
            # 返回结构示例: {'info': ..., 'maker': 0.0008, 'taker': 0.001, ...}
            # 增加对不同 symbol 的容错，防止 API 返回空
            fees = self.exchange.fetch_trading_fee(self.symbol)
            
            if fees:
                # 优先使用 taker/maker 字段，如果没有则保持默认
                new_taker = float(fees.get('taker', self.taker_fee_rate))
                new_maker = float(fees.get('maker', self.maker_fee_rate))
                
                # 检查是否真的获取到了有效值 (防止 None)
                if new_taker is not None and new_maker is not None:
                    # 仅当费率发生实质变化时才打印日志
                    if new_taker != self.taker_fee_rate or new_maker != self.maker_fee_rate:
                        self._log(f"💳 费率自动校准成功: Taker {self.taker_fee_rate*100:.4f}% -> {new_taker*100:.4f}% | Maker {self.maker_fee_rate*100:.4f}% -> {new_maker*100:.4f}%")
                        self.taker_fee_rate = new_taker
                        self.maker_fee_rate = new_maker
        except Exception as e:
            # 获取失败是正常的 (可能权限不足或接口限制)，静默失败使用默认保守值即可
            self._log(f"⚠️ 费率获取失败 (将使用默认保守值): {e}", 'warning')

    def _fmt_price(self, value):
        v = self._to_float(value)
        return f"${v:,.2f}" if v is not None else "N/A"

    def setup_leverage(self):
        """设置交易所杠杆"""
        try:
            # 现货交易不需要设置杠杆
            if self.trade_mode == 'cash':
                return

            self.exchange.set_leverage(
                self.leverage,
                self.symbol,
                {'mgnMode': self.margin_mode}
            )
            self._log(emoji.emojize(f":gear: 设置杠杆倍数: {self.leverage}x ({self.margin_mode})"))
        except Exception as e:
            self._log(emoji.emojize(f":no_entry: 杠杆设置失败: {e}"), 'error')

    def calculate_indicators(self, df):
        """计算技术指标 (RSI, MACD, Bollinger Bands, ADX)"""
        try:
            # 确保数据足够
            if len(df) < 30:
                return df

            # RSI (14)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            # MACD (12, 26, 9)
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = exp1 - exp2
            df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
            df['macd_hist'] = df['macd'] - df['signal_line']

            # Bollinger Bands (20, 2)
            df['sma_20'] = df['close'].rolling(window=20).mean()
            df['std_20'] = df['close'].rolling(window=20).std()
            df['upper_band'] = df['sma_20'] + (df['std_20'] * 2)
            df['lower_band'] = df['sma_20'] - (df['std_20'] * 2)
            
            # ADX (14) - 简化计算
            # 1. True Range
            df['tr0'] = abs(df['high'] - df['low'])
            df['tr1'] = abs(df['high'] - df['close'].shift())
            df['tr2'] = abs(df['low'] - df['close'].shift())
            df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
            
            # 2. Directional Movement
            df['up_move'] = df['high'] - df['high'].shift()
            df['down_move'] = df['low'].shift() - df['low']
            
            df['plus_dm'] = 0.0
            df['minus_dm'] = 0.0
            
            df.loc[(df['up_move'] > df['down_move']) & (df['up_move'] > 0), 'plus_dm'] = df['up_move']
            df.loc[(df['down_move'] > df['up_move']) & (df['down_move'] > 0), 'minus_dm'] = df['down_move']
            
            # 3. Smoothed TR and DM (Wilder's Smoothing)
            # 使用简单的 rolling mean 代替 Wilder's smoothing 以保持代码简洁，效果近似
            window = 14
            df['tr_smooth'] = df['tr'].rolling(window=window).mean()
            df['plus_di'] = 100 * (df['plus_dm'].rolling(window=window).mean() / df['tr_smooth'])
            df['minus_di'] = 100 * (df['minus_dm'].rolling(window=window).mean() / df['tr_smooth'])
            
            # 4. DX and ADX
            df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
            df['adx'] = df['dx'].rolling(window=window).mean()
            
            return df
        except Exception as e:
            self._log(f"计算技术指标失败: {e}", 'error')
            return df

    def get_ohlcv(self):
        """获取K线数据"""
        try:
            # 获取更多K线以计算指标 (至少100根)
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            # [新增] 数据预热: 如果历史记录为空，使用获取到的K线填充
            if not self.price_history and len(df) > self.history_limit:
                self._log(f"🔥 正在预热历史数据 (加载 {len(df)} 条K线)...")
                # 将 DataFrame 转为 price_history 所需的字典格式
                # 我们只需要最近的 N 条来填充
                recent_data = df.tail(self.history_limit).to_dict('records')
                for row in recent_data:
                    # 构造简化的 price_data 结构用于 calculate_indicators 或其他逻辑的上下文
                    # 注意：这里我们无法完全还原当时的所有指标，但至少可以还原价格序列用于计算 SMA 等
                    simple_data = {
                        'price': row['close'],
                        'timestamp': row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                        'kline_data': [], # 历史数据中这个字段可以为空，主要为了 SMA 计算
                        'indicators': {} 
                    }
                    self.price_history.append(simple_data)
                self._log("✅ 历史数据预热完成")

            # 计算技术指标
            df = self.calculate_indicators(df)

            current_data = df.iloc[-1]
            previous_data = df.iloc[-2] if len(df) > 1 else current_data

            # 提取指标数据 (处理可能为NaN的情况)
            indicators = {
                'rsi': float(current_data['rsi']) if pd.notna(current_data.get('rsi')) else None,
                'macd': float(current_data['macd']) if pd.notna(current_data.get('macd')) else None,
                'macd_signal': float(current_data['signal_line']) if pd.notna(current_data.get('signal_line')) else None,
                'macd_hist': float(current_data['macd_hist']) if pd.notna(current_data.get('macd_hist')) else None,
                'bb_upper': float(current_data['upper_band']) if pd.notna(current_data.get('upper_band')) else None,
                'bb_lower': float(current_data['lower_band']) if pd.notna(current_data.get('lower_band')) else None,
                'bb_middle': float(current_data['sma_20']) if pd.notna(current_data.get('sma_20')) else None,
            }

            return {
                'price': current_data['close'],
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'high': current_data['high'],
                'low': current_data['low'],
                'volume': current_data['volume'],
                'timeframe': self.timeframe,
                'price_change': ((current_data['close'] - previous_data['close']) / previous_data['close']) * 100,
                'kline_data': df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail(5).to_dict('records'),
                'indicators': indicators
            }
        except Exception as e:
            self._log(f"获取K线数据失败: {e}", 'error')
            return None

    def get_current_position(self):
        """获取当前持仓情况"""
        try:
            positions = self.exchange.fetch_positions([self.symbol])
            for pos in positions:
                if pos['symbol'] == self.symbol:
                    contracts = float(pos['contracts']) if pos['contracts'] else 0
                    if contracts > 0:
                        return {
                            'side': pos['side'],
                            'size': contracts,
                            'entry_price': float(pos['entryPrice']) if pos['entryPrice'] else 0,
                            'unrealized_pnl': float(pos['unrealizedPnl']) if pos['unrealizedPnl'] else 0,
                            'leverage': float(pos['leverage']) if pos['leverage'] else self.leverage,
                            'symbol': pos['symbol']
                        }
            return None
        except Exception as e:
            self._log(f"获取持仓失败: {e}", 'error')
            return None

    def get_market_volatility(self, kline_data, adx_value=None):
        """计算市场波动率 (结合ATR和ADX)"""
        try:
            if len(kline_data) < 5:
                return "NORMAL"
            
            # 1. 计算价格波动幅度 (类似ATR)
            ranges = []
            for k in kline_data:
                high = k['high']
                low = k['low']
                if low > 0:
                    ranges.append((high - low) / low * 100)
            
            avg_volatility = sum(ranges) / len(ranges)
            
            # 2. 结合 ADX 判断趋势强度
            is_trending = False
            if adx_value is not None and adx_value > 25:
                is_trending = True

            # 综合判断
            if avg_volatility > 0.5: # 剧烈波动
                if is_trending:
                    return "HIGH_TREND" # 单边暴涨/暴跌
                else:
                    return "HIGH_CHOPPY" # 剧烈震荡
            elif avg_volatility < 0.1: 
                return "LOW"
            else:
                return "NORMAL"
        except Exception:
            return "NORMAL"

    def get_avg_entry_price(self):
        """获取平均持仓成本 (尝试通过历史成交计算)"""
        try:
            # 1. 优先尝试从 exchange 获取 (OKX 合约通常有 entryPrice)
            pos = self.get_current_position()
            if pos and pos.get('entry_price', 0) > 0:
                return pos['entry_price']
                
            # 2. 如果是现货，尝试查询最近的成交记录
            # [优化] 增加 limit 到 100 以追溯更早的买入
            trades = self.exchange.fetch_my_trades(self.symbol, limit=100)
            if not trades:
                return 0.0
                
            # 简单的 FIFO/加权平均逻辑比较复杂，这里简化逻辑：
            # 找到最近一次 'buy' 的价格作为参考
            for trade in reversed(trades):
                if trade['side'] == 'buy':
                    return float(trade['price'])
            
            return 0.0
        except Exception:
            return 0.0

    def get_spot_balance(self):
        """获取现货持仓余额"""
        try:
            base_currency = self.symbol.split('/')[0]
            balance = self.exchange.fetch_balance()
            
            # 兼容统一账户和普通账户结构
            if base_currency in balance:
                return float(balance[base_currency]['free'])
            elif 'info' in balance and 'data' in balance['info']:
                for asset in balance['info']['data'][0]['details']:
                    if asset['ccy'] == base_currency:
                        return float(asset['availBal'])
            return 0.0
        except Exception:
            return 0.0

    def analyze_with_deepseek(self, price_data):
        """使用DeepSeek分析"""
        self.price_history.append(price_data)
        if len(self.price_history) > self.history_limit:
            self.price_history.pop(0)
            
        # 获取 ADX 值
        ind = price_data.get('indicators', {})
        adx_val = ind.get('adx')

        # [修改] 计算市场波动状态 (传入ADX)
        volatility_status = self.get_market_volatility(price_data['kline_data'], adx_val)
        
        # 动态调整 Prompt 人设
        role_prompt = ""
        if volatility_status == "HIGH_TREND":
            role_prompt = "你是一位激进的趋势跟踪交易员。当前市场处于【单边剧烈波动】，ADX显示趋势极强。请紧咬趋势，果断追涨杀跌，不要轻易猜顶猜底。"
        elif volatility_status == "HIGH_CHOPPY":
            role_prompt = "你是一位冷静的避险交易员。当前市场处于【剧烈震荡】，波动大但无明显方向。请极度谨慎，优先选择观望，或在布林带极端位置做超短线反转。"
        elif volatility_status == "LOW":
            role_prompt = "你是一位耐心的网格交易员。当前市场横盘震荡，请寻找区间低买高卖的机会，切勿追涨杀跌。"
        else:
            role_prompt = "你是一位稳健的波段交易员。当前市场波动正常，请平衡风险与收益，寻找确定性高的形态信号。"

        # 构建K线数据文本
        kline_text = f"【最近5根{self.timeframe}K线数据】\n"
        for i, kline in enumerate(price_data['kline_data']):
            trend = "阳线" if kline['close'] > kline['open'] else "阴线"
            change = ((kline['close'] - kline['open']) / kline['open']) * 100
            kline_text += f"K线{i + 1}: {trend} 开盘:{kline['open']:.2f} 收盘:{kline['close']:.2f} 涨跌:{change:+.2f}%\n"

        # 构建技术指标文本
        ind = price_data.get('indicators', {})
        
        rsi_str = f"{ind['rsi']:.2f}" if ind.get('rsi') is not None else "N/A"
        macd_str = f"MACD: {ind['macd']:.4f}, Signal: {ind['macd_signal']:.4f}, Hist: {ind['macd_hist']:.4f}" if ind.get('macd') is not None else "MACD: N/A"
        bb_str = f"Upper: {ind['bb_upper']:.2f}, Middle: {ind['bb_middle']:.2f}, Lower: {ind['bb_lower']:.2f}" if ind.get('bb_upper') is not None else "Bollinger: N/A"
        adx_str = f"{ind['adx']:.2f}" if ind.get('adx') is not None else "N/A"
        
        indicator_text = f"""【技术指标】
RSI (14): {rsi_str}
MACD (12,26,9): {macd_str}
Bollinger Bands (20,2): {bb_str}
ADX (14): {adx_str} (趋势强度)
"""
        
        # 补充均线数据 (保留原有逻辑作为参考)
        if len(self.price_history) >= 5:
            closes = [data['price'] for data in self.price_history[-5:]]
            sma_5 = sum(closes) / len(closes)
            price_vs_sma = ((price_data['price'] - sma_5) / sma_5) * 100
            indicator_text += f"5周期均价: {sma_5:.2f}\n当前价格相对于SMA5: {price_vs_sma:+.2f}%"

        # 添加上次交易信号
        signal_text = ""
        if self.signal_history:
            last_signal = self.signal_history[-1]
            signal_text = f"\n【上次交易信号】\n信号: {last_signal.get('signal', 'N/A')}\n信心: {last_signal.get('confidence', 'N/A')}"

        # 添加当前持仓信息
        current_pos = self.get_current_position()
        position_text = ""
        holding_pnl_text = "" # 新增盈亏描述
        
        if self.trade_mode == 'cash':
            # 现货模式：显示持有的币种数量
            spot_bal = self.get_spot_balance()
            if spot_bal > 0:
                avg_price = self.get_avg_entry_price()
                pnl_pct_str = "N/A"
                if avg_price > 0:
                    pnl_pct = ((price_data['price'] - avg_price) / avg_price) * 100
                    pnl_pct_str = f"{pnl_pct:+.2f}%"
                    holding_pnl_text = f"当前持仓盈亏: {pnl_pct_str} (成本: {avg_price:.4f})"
                
                position_text = f"现货持仓: {spot_bal:.4f} (可卖出)"
            else:
                position_text = "无持仓 (仅可买入)"
        else:
            # 合约模式：显示合约持仓
            if current_pos:
                pnl_pct = 0
                if current_pos['entry_price'] > 0:
                     if current_pos['side'] == 'long':
                         pnl_pct = ((price_data['price'] - current_pos['entry_price']) / current_pos['entry_price']) * 100
                     else:
                         pnl_pct = ((current_pos['entry_price'] - price_data['price']) / current_pos['entry_price']) * 100
                
                position_text = f"{current_pos['side']}仓, 数量: {current_pos['size']}, 盈亏: {current_pos['unrealized_pnl']:.2f}USDT"
                holding_pnl_text = f"当前持仓盈亏: {pnl_pct:+.2f}% (未实现)"
            else:
                position_text = "无持仓"
        
        # 获取账户余额 (新增)
        balance = self.get_account_balance()
        balance_text = f"{balance:.2f} USDT"
        
        # 计算最大可买数量 (简单估算，未考虑手续费)
        max_buy_amount = 0
        if price_data['price'] > 0:
            if self.trade_mode == 'cash':
                max_buy_amount = balance / price_data['price']
            else:
                # 合约模式：余额 * 杠杆 / 价格
                max_buy_amount = (balance * self.leverage) / price_data['price']
        
        # 保留4位小数
        max_buy_amount = float(f"{max_buy_amount:.4f}")

        prompt = f"""
        # 角色设定
        {role_prompt}

        # 市场数据
        交易对: {self.symbol}
        周期: {self.timeframe}
        当前价格: ${price_data['price']:,.2f}
        K线时间: {price_data['timestamp']}
        阶段涨跌: {price_data['price_change']:+.2f}%
        
        # 账户状态
        当前持仓: {position_text}
        {holding_pnl_text}
        可用余额: {balance_text}
        理论最大可买数量: {max_buy_amount} (仅供参考)
        配置默认交易数量: {self.amount} (如果为 auto 模式，此值为自动计算建议值)
        
        # 技术指标输入
        {kline_text}
        {indicator_text}
        {signal_text}

        # 分析任务
        请综合上述数据进行激进的短线决策：
        1. **趋势研判与反手逻辑**：
           - 密切关注 ADX 和均线系统。如果当前持仓方向与市场主趋势严重背离（例如持有空单但价格沿着布林上轨单边上涨），**承认错误是最高级的智慧**。
           - **反手建议**：如果你认为当前趋势极强且不可逆转，请在建议 SELL (平仓) 的同时，在 reason 中明确表达“建议反手开多/开空”。虽然你只能返回一个信号，但请通过将 confidence 设为 HIGH 并建议较大的 amount 来暗示强烈的方向转换意愿。
        2. **止损优先于形态**：
           - **严禁死扛**：如果当前浮亏 > 3% 且趋势未变，**不要等待完美的K线反转形态**。直接建议 SELL 止损。活着才有下一次机会。
           - 记住：在单边行情中，RSI 超买/超卖可以持续很久（钝化）。不要仅因为 RSI > 80 就盲目看空，除非有明确的阴线吞没。
        3. **忽略小额限制**：即使余额较少，只要够买入最小单位，就不要因为资金少而拒绝交易。
        4. **信号决策**：
           - **卖出逻辑 (关键)**：
             - **费率与模式识别**：当前交易模式的 Taker 费率为 **{self.taker_fee_rate*100:.3f}%** (单向)。
             - **最小止盈线**：**严禁**建议卖出浮盈 < **{(self.taker_fee_rate*2 + 0.0005)*100:.2f}%** 的仓位（双向手续费+滑点），否则就是给交易所打工。
             - **推荐止盈线**：建议浮盈达到费率的 **3倍以上** (约 > **{(self.taker_fee_rate*6)*100:.2f}%**) 再考虑分批止盈。
             - **智能最大获利**：请分析当前上涨动能是否衰竭（结合 MACD 柱线缩短、RSI 背离或上影线）。如果没有衰竭迹象，**请选择 HOLD 继续持有**，让利润奔跑，直到出现明确的顶部反转信号。不要仅仅因为“赚了”就卖。
             - **止损保护**：如果亏损触及止损线或形态崩坏，请忽略手续费果断 SELL，保命第一。
           - **买入逻辑**：只要盈亏比 > 1.2，且有一定把握，就发出 BUY 信号。如果信心非常足（如完美底部形态或强劲突破），请标记 confidence 为 HIGH。
           - 只有在完全看不懂或极度危险时才选择 HOLD。
        5. **资金管理**：
            - 如果【理论最大可买数量】 < 【配置默认交易数量】，请直接建议买入【理论最大可买数量】(All-in)。
            - 允许适当承担风险以博取收益。

        # 输出要求
        请严格返回如下JSON格式，不要包含任何Markdown标记：
        {{
            "signal": "BUY" | "SELL" | "HOLD",
            "reason": "简练的核心逻辑（100字以内），包含关键点位和形态判断",
            "stop_loss": 止损价格(数字，必须设置),
            "take_profit": 止盈价格(数字，建议R/R > 1.1),
            "confidence": "HIGH" | "MEDIUM" | "LOW",
            "amount": 建议交易数量(数字)
        }}
        """

        try:
            self._log("⏳ 正在请求 DeepSeek 分析，请耐心等待...", 'info')
            response = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": role_prompt},
                    {"role": "user", "content": prompt}
                ],
                stream=False,
                timeout=60  # 设置60秒超时
            )

            result = response.choices[0].message.content
            # 简单清理json markdown标记
            result = result.replace('```json', '').replace('```', '').strip()
            
            start_idx = result.find('{')
            end_idx = result.rfind('}') + 1
            if start_idx != -1 and end_idx != 0:
                json_str = result[start_idx:end_idx]
                signal_data = json.loads(json_str)
            else:
                self._log(f"无法解析JSON: {result}", 'error')
                return None

            # 格式化数据
            signal_data['signal'] = str(signal_data.get('signal', '')).upper()
            
            # 美化信心显示
            raw_confidence = str(signal_data.get('confidence', '')).upper()
            confidence_emoji = {
                'HIGH': '⭐⭐⭐ (高)',
                'MEDIUM': '⭐⭐ (中)',
                'LOW': '⭐ (低)'
            }
            # 不直接修改 signal_data['confidence']，防止历史记录里存入带emoji的字符串影响后续逻辑
            # 我们只在打印时做转换，或者存一个新的字段
            display_confidence = confidence_emoji.get(raw_confidence, raw_confidence)
            signal_data['display_confidence'] = display_confidence
            
            signal_data['stop_loss'] = self._to_float(signal_data.get('stop_loss'))
            signal_data['take_profit'] = self._to_float(signal_data.get('take_profit'))

            # 解析AI建议的数量，如果AI没给，就用默认配置
            ai_amount = self._to_float(signal_data.get('amount'))
            if ai_amount is not None and ai_amount > 0:
                signal_data['amount'] = ai_amount
            else:
                signal_data['amount'] = self.amount

            signal_data['timestamp'] = price_data['timestamp']

            self.signal_history.append(signal_data)
            if len(self.signal_history) > self.signal_limit:
                self.signal_history.pop(0)

            return signal_data

        except Exception as e:
            self._log(f"DeepSeek分析失败(可能是超时或网络问题): {e}", 'error')
            return None

    def execute_trade(self, signal_data):
        """执行交易"""
        current_position = self.get_current_position()
        
        # [新增] 动态计算 config_amount (如果是 auto 模式)
        config_amount = 0
        if self.config_amount == 'auto':
            # 使用自动计算出的 self.amount
            config_amount = self.amount
        else:
            config_amount = self.amount
            
        # 使用 display_confidence 进行打印，如果没有则回退到 confidence
        conf_str = signal_data.get('display_confidence', signal_data['confidence'])
        
        # [新增] 计算预估金额，方便用户理解
        current_price = self.get_ohlcv()['price']
        est_usdt_value = signal_data['amount'] * current_price
        
        self._log(f"🧠 分析结果: {signal_data['signal']} | 🎯 信心指数: {conf_str}")
        self._log(f"理由: {signal_data['reason']}")
        self._log(f"建议数量: {signal_data['amount']} (≈ ${est_usdt_value:.2f})")
        self._log(f"止损: {self._fmt_price(signal_data.get('stop_loss'))}")
        self._log(f"止盈: {self._fmt_price(signal_data.get('take_profit'))}")

        # [新增] 信心门槛过滤 (Confidence Filter)
        confidence_levels = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}
        current_conf_val = confidence_levels.get(signal_data.get('confidence', 'LOW').upper(), 1)
        min_conf_val = confidence_levels.get(self.min_confidence.upper(), 2) # 默认为 MEDIUM
        
        if current_conf_val < min_conf_val:
            self._log(f"✋ 信号信心不足: {signal_data.get('confidence')} < {self.min_confidence} (过滤阈值)")
            self._log("   -> 强制转为 HOLD (保持观望)")
            signal_data['signal'] = 'HOLD'
            signal_data['reason'] += f" [信心过滤: {signal_data.get('confidence')} < {self.min_confidence}]"

        if signal_data['signal'] == 'HOLD':
            self._log("☕ 决策结果: 保持观望 (HOLD)")
            return

        # [新增] 卖出信号的二次风控检查
        if signal_data['signal'] == 'SELL':
            # 检查是否为微利平仓
            if current_position:
                pnl_pct = 0
                if current_position['entry_price'] > 0:
                    if current_position['side'] == 'long':
                        pnl_pct = (current_price - current_position['entry_price']) / current_position['entry_price']
                    else:
                        pnl_pct = (current_position['entry_price'] - current_price) / current_position['entry_price']
                
                # OKX Taker 费率 (自动适配 VIP 等级)
                # 使用 API 获取到的 taker_fee_rate (单向)
                one_way_fee = self.taker_fee_rate
                round_trip_fee = one_way_fee * 2
                
                # 最小盈利门槛 = 双向手续费 + 0.05% 滑点保护
                min_profit_threshold = round_trip_fee + 0.0005 

                # 设定硬性拦截线
                
                if 0 <= pnl_pct < min_profit_threshold: 
                    self._log(f"🛑 拦截微利平仓: 当前浮盈 {pnl_pct*100:.3f}% < {min_profit_threshold*100:.3f}% (手续费覆盖线)", 'warning')
                    self._log(f"   原因: 扣除 Taker 费率 (约{round_trip_fee*100:.3f}%) 后几无利润，建议继续持有", 'warning')
                    # 强制将 SELL 转为 HOLD
                    signal_data['signal'] = 'HOLD'
                    signal_data['reason'] = f"[风控拦截] 浮盈 {pnl_pct*100:.2f}% 不足以覆盖双向手续费({round_trip_fee*100:.3f}%)"
                
                # 如果是盈利单，但盈利较薄，则发出警告
                elif min_profit_threshold <= pnl_pct < (min_profit_threshold + 0.003):
                    self._log(f"⚠️ 警告: AI 建议微利平仓 (+{pnl_pct*100:.2f}%)，利润空间较小！", 'warning')
                    # 这里可以选择强制拦截，但为了防止 AI 是因为看到暴跌信号而逃命，我们暂时只警告，不拦截。
                    # 提示用户关注 Prompt 调整的效果。

        if self.test_mode:
            self._log("🧪 测试模式 - 仅模拟交易，不执行下单")
            return

        # === [新增] 价格时效性检查 (防止滑点和延迟) ===
        try:
            # 获取最新Ticker价格
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_realtime_price = ticker['last']
            analysis_price = self.get_ohlcv()['price'] # 这里获取的是K线收盘价，可能稍有延迟，但用于计算偏差足够
            
            # 如果分析时的价格(signal_data里带的或者ohlcv的)与当前最新价格偏差超过一定阈值(如0.5%)
            # 说明在分析过程中市场发生了剧烈波动，或者数据滞后
            price_gap_percent = abs(current_realtime_price - analysis_price) / analysis_price * 100
            
            if price_gap_percent > self.max_slippage: 
                self._log(f"⚠️ 价格波动剧烈或数据延迟: 分析价 {analysis_price} vs 最新价 {current_realtime_price} (偏差 {price_gap_percent:.2f}% > {self.max_slippage}%)", 'warning')
                self._log("🚫 为防止滑点，取消本次交易")
                self.send_notification(f"⚠️ 交易取消\n原因: 价格波动过大 ({price_gap_percent:.2f}%)")
                return
        except Exception as e:
            self._log(f"价格检查失败: {e}", 'warning')
            # 检查失败不一定要终止，可以继续，视风险偏好而定。这里选择继续。

        # === 资金风控：三方取最小 (Triple Check) ===
        # 1. 配置文件设定的基准数量
        config_amount = self.amount
        
        # 2. AI 建议的数量
        ai_suggest_amount = signal_data['amount']
        
        # 3. 钱包余额允许的最大数量 (预留1%手续费)
        current_price = self.get_ohlcv()['price']
        real_balance = self.get_account_balance()
        
        # === [修改] 资金分配与隔离逻辑 ===
        effective_balance = real_balance
        allocated_quota = real_balance # 默认无限制

        if self.initial_balance and self.initial_balance > 0:
            # 计算该币种的分配额度
            if self.allocation <= 1.0:
                # 百分比模式：总资金 * 比例
                allocated_quota = self.initial_balance * self.allocation
                self._log(f"💰 资金分配: 总额 {self.initial_balance} x 比例 {self.allocation*100}% = {allocated_quota:.2f} U")
            else:
                # 固定金额模式
                allocated_quota = self.allocation
                self._log(f"💰 资金分配: 固定额度 {allocated_quota:.2f} U")
            
            # [新增] 扣除已占用资金 (已买入的持仓价值)
            # 这回答了您的问题：如果配置100U，已经买入了40U的ETH，那么剩下只能买60U
            used_capital = 0.0
            if self.trade_mode == 'cash':
                spot_bal = self.get_spot_balance()
                used_capital = spot_bal * current_price
                if used_capital > 1.0: # 忽略微小尘埃
                    self._log(f"📉 已占用资金: 持有 {spot_bal:.4f} {self.symbol.split('/')[0]} ≈ {used_capital:.2f} U")
            else:
                # 合约模式：估算已用保证金
                # 注意：这里粗略用 持仓价值/杠杆 估算
                pos = self.get_current_position()
                if pos:
                    # 获取合约面值通常需要更多API信息，这里暂时用 size (张数) * 价格 * 合约乘数(假设为1，实际上不同币种不同)
                    # 为了安全起见，如果持有合约仓位，且没有更精确的保证金数据，
                    # 我们暂时不扣除 used_capital，或者需要 fetch_position 里的 margin
                    # 但对于 OKX，我们可以尝试获取 unreleasedPnl 之外的 margin
                    pass

            remaining_quota = max(0, allocated_quota - used_capital)
            self._log(f"🧮 剩余可用额度: {allocated_quota:.2f} - {used_capital:.2f} = {remaining_quota:.2f} U")

            # 资金隔离：严格限制使用资金不超过 (分配额度 - 已用额度)
            # 这里的 effective_balance 是“本币种当前这一单允许动用的最大资金”
            if remaining_quota < real_balance:
                self._log(f"🛡️ 额度限制生效: 余额 {real_balance:.2f} > 剩余额度 {remaining_quota:.2f} -> 锁定上限 {remaining_quota:.2f} U")
                effective_balance = remaining_quota
            else:
                # 余额不足剩余额度时，使用实际余额
                self._log(f"⚠️ 余额不足: 余额 {real_balance:.2f} < 剩余额度 {remaining_quota:.2f} -> 使用余额")
                effective_balance = real_balance
        else:
             # 未配置总资金，仅显示当前余额
             pass
        
        # === [修正] 根据交易方向计算最大可行数量 ===
        is_closing_position = False
        max_trade_limit = 0.0

        if signal_data['signal'] == 'BUY':
            # 买入/开多：受限于 USDT 余额和配额
            # 即使当前是空仓，BUY信号的主要目的是"开多"（代码逻辑是先平空再开多）
            # 所以这里计算的是"开多"的能力，应使用 USDT 余额计算
            if self.trade_mode == 'cash':
                max_trade_limit = (effective_balance * 0.99) / current_price
            else:
                max_trade_limit = (effective_balance * self.leverage * 0.99) / current_price
        
        elif signal_data['signal'] == 'SELL':
            # 卖出/开空
            if self.trade_mode == 'cash':
                # 现货卖出：受限于持有的币种数量 (不受USDT配额限制!)
                spot_bal = self.get_spot_balance()
                max_trade_limit = spot_bal
                is_closing_position = True # 视为平仓性质，不受配额限制
            else:
                # 合约
                if current_position and current_position['side'] == 'long':
                    # 平多仓逻辑：
                    # 这里代码将执行 "先平后开" (Reversal)，所以这里的 trade_amount 实际上是用于 "新开空单" 的数量。
                    # 平仓操作在后续代码中固定使用 current_position['size']，不消耗此处的 trade_amount。
                    
                    # 因此，这里应该计算的是 "新开空单" 的能力，基于 USDT 余额
                    is_closing_position = False 
                    max_trade_limit = (effective_balance * self.leverage * 0.99) / current_price
                else:
                    # 开空仓：受限于 USDT 余额和配额
                    max_trade_limit = (effective_balance * self.leverage * 0.99) / current_price

        # 逻辑核心：取三者中的最小值
        # 1. config_amount: 用户想买的数量
        # 2. ai_suggest_amount: AI 建议的数量
        # 3. max_trade_limit: 实际账户允许的最大数量
        
        if is_closing_position:
            # 平仓逻辑：不受买入配额(config_amount/effective_balance)限制
            # 但受持仓量(max_trade_limit)限制
            trade_amount = min(ai_suggest_amount, max_trade_limit)
            self._log(f"📉 平仓/卖出模式: 不受买入配额限制。持仓: {max_trade_limit}, AI建议: {ai_suggest_amount} -> 执行: {trade_amount}")
        else:
            # 开仓逻辑：
            # [策略优化] 如果 AI 信心极高 (HIGH)，允许突破 config_amount 的限制，直接使用 ai_suggest_amount (但在 max_trade_limit 范围内)
            # 这解决了 "AI 想梭哈但被配置卡住" 的问题
            
            raw_confidence = signal_data.get('confidence', '').upper()
            
            if raw_confidence == 'HIGH':
                # 高信心模式：信任 AI 的判断，忽略 config.json 里的 amount 限制，仅受余额限制
                trade_amount = min(ai_suggest_amount, max_trade_limit)
                self._log(f"🦁 激进模式 (信心高): 忽略配置限制 {config_amount}，跟随 AI 建议 {ai_suggest_amount}")
                self._log(f"   (余额上限: {max_trade_limit:.4f})")
            else:
                # 普通模式：受限于配额、AI建议和配置数量
                trade_amount = min(config_amount, ai_suggest_amount, max_trade_limit)
        
        # [修复] 使用交易所规则处理精度和最小数量
        try:
            # 1. 先检查最小下单限制
            market = self.exchange.market(self.symbol)
            limits = market.get('limits', {})
            min_amount = limits.get('amount', {}).get('min')
            min_cost = limits.get('cost', {}).get('min')
            
            # [增强] 自动适配最小数量策略
            # 如果 trade_amount < min_amount，但账户允许交易更多（max_trade_limit >= min_amount），
            # 且这是 AI 的 BUY 信号，我们尝试自动提升到 min_amount 以避免被拒单。
            if min_amount is not None and trade_amount < min_amount:
                 if max_trade_limit >= min_amount and signal_data['signal'] == 'BUY':
                     self._log(f"⚠️ 交易数量 {trade_amount} 小于最小限制 {min_amount}，自动提升至最小单位")
                     trade_amount = min_amount
                 else:
                    self._log(f"🚫 跳过下单: 数量 {trade_amount} 小于最小限制 {min_amount}", 'warning')
                    self.send_notification(f"⚠️ 无法下单\n数量 {trade_amount} 小于最小限制 {min_amount}")
                    return

            # 2. 精度截断
            try:
                precise_amount_str = self.exchange.amount_to_precision(self.symbol, trade_amount)
                trade_amount = float(precise_amount_str)
            except Exception as precision_error:
                self._log(f"🚫 精度转换失败 (可能数量太小): {precision_error}", 'warning')
                return
            
            # 3. 再次检查截断后的数量和金额
            if min_amount is not None and trade_amount < min_amount:
                self._log(f"🚫 跳过下单: 截断后数量 {trade_amount} 小于最小限制 {min_amount}", 'warning')
                return
                
            # [新增] 检查最小下单金额 (Min Cost) 并尝试自动适配
            if min_cost is not None:
                estimated_cost = trade_amount * current_price
                if estimated_cost < min_cost:
                    # 如果预估金额不足，但账户有钱，且这是 BUY 信号，尝试加钱买
                    if max_trade_limit * current_price >= min_cost and signal_data['signal'] == 'BUY':
                         # 计算满足最小金额所需的数量，并多加 5% 缓冲
                         required_amount = (min_cost / current_price) * 1.05
                         precise_req_amount = float(self.exchange.amount_to_precision(self.symbol, required_amount))
                         self._log(f"⚠️ 交易金额 {estimated_cost:.2f}U 小于最小限制 {min_cost}U，尝试调整数量至 {precise_req_amount}")
                         trade_amount = precise_req_amount
                    else:
                        self._log(f"🚫 跳过下单: 预估金额 {estimated_cost:.2f}U 小于最小金额限制 {min_cost}U", 'warning')
                        return
                
        except Exception as e:
            self._log(f"❌ 精度/限额检查出错: {e}", 'error')
            trade_amount = float(f"{trade_amount:.4f}")

        # 打印风控日志
        if trade_amount != ai_suggest_amount:
            self._log(f"🛡️ 风控介入: AI建议 {ai_suggest_amount} -> 最终执行 {trade_amount}")
            # [修复] 变量名不一致问题 (config_amount vs self.config_amount)
            # 这里的 config_amount 应该是 execute_trade 开头从 self.config_amount 取的值
            # 但为了准确，我们直接打印当前模式
            limit_info = f"余额限制: {max_trade_limit:.4f}"
            if self.config_amount != 'auto':
                limit_info = f"配置限制: {self.config_amount}, " + limit_info
            
            self._log(f"   ({limit_info})")
            
        if trade_amount <= 0:
            self._log(f"🚫 跳过下单: 最终交易数量为 {trade_amount}")
            return

        # === 执行交易指令 ===
        try:
            order_result = None
            action_type = ""
            
            # 1. 现货交易逻辑
            if self.trade_mode == 'cash':
                if signal_data['signal'] == 'BUY':
                    action_type = "现货买入"
                    self._log(f"🚀 正在执行: {action_type} {trade_amount} ...")
                    order_result = self.exchange.create_market_order(self.symbol, 'buy', trade_amount)
                
                elif signal_data['signal'] == 'SELL':
                    # 现货卖出检查余额
                    base_currency = self.symbol.split('/')[0] 
                    balance = self.exchange.fetch_balance()
                    coin_balance = 0
                    
                    if base_currency in balance:
                        coin_balance = balance[base_currency]['free']
                    elif 'info' in balance and 'data' in balance['info']:
                         for asset in balance['info']['data'][0]['details']:
                             if asset['ccy'] == base_currency:
                                 coin_balance = float(asset['availBal'])
                    
                    if coin_balance >= trade_amount:
                        action_type = "现货卖出"
                        self._log(f"📉 正在执行: {action_type} {trade_amount} (持有: {coin_balance})...")
                        order_result = self.exchange.create_market_order(self.symbol, 'sell', trade_amount)
                    else:
                        self._log(f"🚫 无法卖出: 持有 {base_currency} 不足 (余额: {coin_balance}, 需要: {trade_amount})", 'error')
                        return

            # 2. 合约交易逻辑
            else:
                if signal_data['signal'] == 'BUY':
                    if current_position and current_position['side'] == 'short':
                        self._log("🔄 平空仓...")
                        self.exchange.create_market_order(self.symbol, 'buy', current_position['size'], params={'reduceOnly': True})
                        self.send_notification(f"🔄 平空仓\n数量: {current_position['size']}")
                        time.sleep(1)
                    
                    # [修改] 允许加仓 (Pyramiding)
                    # 只要资金风控允许 (max_trade_limit > 0)，即使持有 long 也可以继续买入
                    if not current_position or current_position['side'] == 'short' or current_position['side'] == 'long':
                        action_type = "开多仓"
                        if current_position and current_position['side'] == 'long':
                            action_type = "多单加仓"
                            
                        self._log(f"📈 正在执行: {action_type} {trade_amount} ...")
                        order_result = self.exchange.create_market_order(self.symbol, 'buy', trade_amount, params={'tdMode': self.trade_mode})

                elif signal_data['signal'] == 'SELL':
                    if current_position and current_position['side'] == 'long':
                        self._log("🔄 平多仓...")
                        self.exchange.create_market_order(self.symbol, 'sell', current_position['size'], params={'reduceOnly': True})
                        self.send_notification(f"🔄 平多仓\n数量: {current_position['size']}")
                        time.sleep(1)
                    
                    # [修改] 允许加仓 (Pyramiding)
                    if not current_position or current_position['side'] == 'long' or current_position['side'] == 'short':
                        action_type = "开空仓"
                        if current_position and current_position['side'] == 'short':
                            action_type = "空单加仓"

                        self._log(f"📉 正在执行: {action_type} {trade_amount} ...")
                        order_result = self.exchange.create_market_order(self.symbol, 'sell', trade_amount, params={'tdMode': self.trade_mode})

            # === 交易成功确认日志 ===
            if order_result:
                order_id = order_result.get('id', 'Unknown')
                filled = order_result.get('filled', trade_amount)
                price = order_result.get('average', current_price)
                if price is None: price = current_price
                
                log_msg = f"✅ 交易成功! [{action_type}] 数量: {filled} | 价格: {price} | ID: {order_id}"
                self._log(log_msg)
                self.send_notification(f"{log_msg}\n理由: {signal_data['reason']}")

        except Exception as e:
            error_msg = str(e)
            if "51008" in error_msg or "Insufficient USDT margin" in error_msg:
                 self._log(f"❌ 交易失败: 保证金不足 (错误代码 51008)", 'error')
                 self._log(f"   原因可能为: 1. 余额不足支付保证金; 2. 交易数量小于最小合约单位(通常为1张); 3. 未划转资金到交易账户")
                 self.send_notification(f"⚠️ 交易失败: 保证金不足\n请检查余额或最小交易单位")
            else:
                self._log(f"❌ 订单执行崩溃: {e}", 'error')
                self.send_notification(f"⚠️ 订单执行失败\n错误: {str(e)}")

    def get_account_balance(self):
        """获取账户余额"""
        try:
            # 尝试获取交易账户余额
            params = {}
            if self.test_mode:
                params = {'simulated': True} # 如果是模拟盘可能需要这个参数，视具体交易所而定
                
            balance = self.exchange.fetch_balance(params)
            
            # 调试：打印一下原始数据结构，方便排查（仅在余额为0时打印一次）
            # print(f"DEBUG BALANCE: {balance}") 
            
            # 优先检查 USDT 余额
            if 'USDT' in balance:
                return balance['USDT']['free']
            elif 'info' in balance and 'data' in balance['info']:
                 # 针对OKX统一账户的特殊处理
                 for asset in balance['info']['data'][0]['details']:
                     if asset['ccy'] == 'USDT':
                         return float(asset['availBal'])

            # 如果没有找到 USDT，可能是现货账户（针对 SELL 操作），检查当前币种余额
            base_currency = self.symbol.split('/')[0]
            if base_currency in balance:
                return balance[base_currency]['free']
            elif 'info' in balance and 'data' in balance['info']:
                for asset in balance['info']['data'][0]['details']:
                     if asset['ccy'] == base_currency:
                         return float(asset['availBal'])
            
            return 0
        except Exception as e:
            self._log(f"获取余额失败: {e}", 'error')
            return 0

    def record_pnl_to_csv(self, total_equity, current_pnl, pnl_percent):
        """记录盈亏数据到CSV文件"""
        csv_file = "pnl_history.csv"
        file_exists = os.path.isfile(csv_file)
        
        try:
            with open(csv_file, 'a', encoding='utf-8') as f:
                # 如果文件不存在，先写表头
                if not file_exists:
                    f.write("timestamp,total_equity,pnl_usdt,pnl_percent\n")
                
                # 写入数据
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp},{total_equity:.2f},{current_pnl:.2f},{pnl_percent:.2f}\n")
        except Exception as e:
            self._log(f"写入CSV失败: {e}", 'error')

    def close_all_positions(self):
        """清空当前币种所有仓位"""
        try:
            pos = self.get_current_position()
            if pos:
                self._log(f"正在市价平仓 {pos['symbol']} ({pos['side']})...")
                side = 'buy' if pos['side'] == 'short' else 'sell'
                self.exchange.create_market_order(self.symbol, side, pos['size'], params={'reduceOnly': True})
                self._log("平仓指令已发送。")
        except Exception as e:
            self._log(f"平仓失败: {e}", 'error')

    def run(self):
        """运行单次交易循环"""
        print("\n" + "=" * 80)
        self._log(f"🚀 开始执行交易循环...")
        
        # [新增] 启动时先校准一次费率 (如果没有上次更新时间)
        if not hasattr(self, 'last_fee_update_time'):
            self._update_fee_rate()
            self.last_fee_update_time = time.time()
        
        # [新增] 定期检查费率 (每 4 小时)
        if time.time() - self.last_fee_update_time > 4 * 3600:
            self._update_fee_rate()
            self.last_fee_update_time = time.time()
        
        # 0. 优先检查全局风控 (已移交给 RiskManager，此处保留空位)
        # self.check_global_pnl_and_exit()
        
        # 获取余额
        balance = self.get_account_balance()
        self._log(f"💰 当前可用余额: {balance:.2f} USDT")

        price_data = self.get_ohlcv()
        if not price_data:
            return

        # [新增] 每次循环前，根据当前价格动态更新 amount (如果是 auto 模式)
        self._update_amount_auto(price_data['price'])

        # 计算颜色箭头
        price_change = price_data['price_change']
        arrow = "🟢" if price_change > 0 else "🔴" if price_change < 0 else "⚪"
        
        self._log(f"📊 当前价格: ${price_data['price']:,.2f} {arrow} ({price_change:+.2f}%)")
        
        signal_data = self.analyze_with_deepseek(price_data)
        if signal_data:
            self.execute_trade(signal_data)
        
        print("=" * 80 + "\n")


def load_config():
    """加载配置文件"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # [Security] 优先使用环境变量覆盖配置中的敏感信息
        # OKX 凭证
        if os.getenv('OKX_API_KEY'):
            config['exchanges']['okx']['api_key'] = os.getenv('OKX_API_KEY')
        if os.getenv('OKX_SECRET'):
            config['exchanges']['okx']['secret'] = os.getenv('OKX_SECRET')
        if os.getenv('OKX_PASSWORD'):
            config['exchanges']['okx']['password'] = os.getenv('OKX_PASSWORD')
            
        # DeepSeek 凭证
        if os.getenv('DEEPSEEK_API_KEY'):
            config['models']['deepseek']['api_key'] = os.getenv('DEEPSEEK_API_KEY')
            
        return config
    except FileNotFoundError:
        print("未找到config.json，请先创建配置文件")
        return None

def print_banner():
    """打印启动横幅"""
    banner = """
    ██████╗ ██████╗ ██╗   ██╗██████╗ ████████╗ ██████╗ 
   ██╔════╝ ██╔══██╗╚██╗ ██╔╝██╔══██╗╚══██╔══╝██╔═══██╗
   ██║      ██████╔╝ ╚████╔╝ ██████╔╝   ██║   ██║   ██║
   ██║      ██╔══██╗  ╚██╔╝  ██╔═══╝    ██║   ██║   ██║
   ╚██████╗ ██║  ██║   ██║   ██║        ██║   ╚██████╔╝
    ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝        ╚═╝    ╚═════╝ 
    
    🤖 CryptoOracle AI Trading System | v2.2 (Security Hardening)
    ===================================================
    """
    print(banner)
    # [修复] 显式将 Banner 写入日志文件，而不是仅在控制台打印
    logging.info(banner)
    logging.info("\n" + "="*50 + "\n🚀 系统启动 (SYSTEM STARTUP)\n" + "="*50)

def main():
    print_banner()
    config = load_config()
    if not config:
        return

    # 初始化DeepSeek客户端
    deepseek_config = config['models']['deepseek']
    proxy = config['trading'].get('proxy', '')
    
    # 构造 OpenAI 客户端参数
    client_params = {
        'api_key': deepseek_config['api_key'],
        'base_url': deepseek_config['base_url']
    }
    
    # [新增] 如果配置了代理，则设置 http_client
    if proxy:
        print(f"🌍 使用代理连接 DeepSeek: {proxy}")
        import httpx
        client_params['http_client'] = httpx.Client(proxies=proxy)

    deepseek_client = OpenAI(**client_params)

    # 初始化OKX交易所
    okx_config = config['exchanges']['okx']
    exchange_params = {
        'options': okx_config.get('options', {'defaultType': 'swap'}), # 默认使用 swap，现货 symbol 会自动识别
        'apiKey': okx_config['api_key'],
        'secret': okx_config['secret'],
        'password': okx_config['password'],
    }
    
    # [新增] 如果配置了代理，则设置 ccxt 代理
    if proxy:
        print(f"🌍 使用代理连接 OKX: {proxy}")
        exchange_params['proxies'] = {
            'http': proxy,
            'https': proxy
        }
    
    exchange = ccxt.okx(exchange_params)
    
    # [新增] 加载市场数据，用于获取精度和最小下单数量
    print("⏳ 正在加载 OKX 市场数据...")
    exchange.load_markets()

    # [新增] 启动自检程序
    print("\n" + "="*30)
    print("🛠️ 正在执行系统自检...")
    print("💡 提示: 若更换了配置币种，建议先将旧币种转换为 USDT，以保证盈亏统计连续性。")
    try:
        # 1. 检查 OKX 连接和权限
        balance = exchange.fetch_balance()
        print("✅ OKX API 连接成功")
        
        # [新增] 资金与持仓全景扫描
        # A. 检查 USDT 资金
        total_usdt = 0
        free_usdt = 0
        if 'USDT' in balance:
            total_usdt = float(balance['USDT']['total'])
            free_usdt = float(balance['USDT']['free'])
        elif 'info' in balance and 'data' in balance['info']: # 统一账户
             for asset in balance['info']['data'][0]['details']:
                 if asset['ccy'] == 'USDT':
                     total_usdt = float(asset['eq']) # 权益
                     free_usdt = float(asset['availBal']) # 可用
        
        # 对比配置资金与实际资金
        config_initial = config['trading'].get('risk_control', {}).get('initial_balance_usdt', 0)
        
        # [修改] 简化 main 函数自检，详细资产盘点移交给 RiskManager
        print(f"💰 账户 USDT 权益: {total_usdt:.2f} U (可用: {free_usdt:.2f} U)")
        
        # B. 检查未受管辖的资产 (编外资产)
        configured_symbols = [s['symbol'].split('/')[0] for s in config['symbols']]
        unmanaged_assets = []
        
        # 遍历余额中所有非零资产
        if 'total' in balance:
            for currency, amount in balance['total'].items():
                if amount > 0 and currency != 'USDT' and currency not in configured_symbols:
                    unmanaged_assets.append(f"{currency}({amount})")
        
        if unmanaged_assets:
            print(f"⚠️ 发现编外资产: {', '.join(unmanaged_assets)}")
            print("   (注: 风控系统已启用 [资金隔离] 模式，这些编外资产的波动【不会】触发机器人的止损/止盈)")
        
        # 2. 检查 DeepSeek 连接
        print("⏳ 正在测试 DeepSeek API...")
        deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5
        )
        print("✅ DeepSeek API 连接成功")
        
        print("🚀 系统自检完成，准备启动交易循环")
        print("="*30 + "\n")
        
    except Exception as e:
        print(f"❌ 自检失败: {e}")
        print("⚠️ 请检查 API Key 配置或网络连接")
        # return 
        
    # 创建交易实例列表
    traders = []
    for symbol_conf in config['symbols']:
        trader = DeepSeekTrader(symbol_conf, config['trading'], exchange, deepseek_client)
        traders.append(trader)

    print(emoji.emojize(":rocket: 多币种交易机器人已启动"))
    if config['trading']['test_mode']:
        print(emoji.emojize(":test_tube: 当前为测试模式"))

    # [新增] 初始化全局风控管理器并执行首次资产盘点
    risk_manager = RiskManager(exchange, config['trading'].get('risk_control', {}), traders)
    
    # [新增] 发送启动通知
    if config['trading'].get('notification', {}).get('enabled', False):
        print("📨 正在发送启动通知测试...")
        risk_manager.send_notification(f"🚀 机器人已启动\n当前模式: {'测试模式' if config['trading']['test_mode'] else '实盘模式'}\n监控币种: {len(traders)} 个")

    
    # [优化] 先预热数据，避免日志打断后续的表格显示
    print("⏳ 正在预热市场数据 (K线 & 指标)...")
    for trader in traders:
        try:
            # 这一步会触发 get_ohlcv -> 预热日志
            trader.get_ohlcv()
        except:
            pass
    print("✅ 数据预热完成")

    # 显式执行一次启动时的资产盘点 (打印详细表格)
    # 注意：这里传入 total_usdt (USDT总权益)，risk_manager 会自动加上持仓市值
    # 如果 total_usdt 在 try 块中未定义(发生异常)，则设为 0
    start_equity = locals().get('total_usdt', 0)
    risk_manager.initialize_baseline(start_equity)
    
    # 启动时显示一次历史盈亏趋势图
    risk_manager.display_pnl_history()

    def job():
        # [修改] 使用 logging.info 记录到日志文件，确保日志里也有分割线
        sep_start = "\n" + "▼" * 50
        sep_msg = f"⏰ 批次执行开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        sep_end = "▲" * 50 + "\n"
        
        print(sep_start)
        print(sep_msg)
        print(sep_end)
        
        # 写入日志文件，方便后续查看
        logging.info(f"{sep_start}\n{sep_msg}\n{sep_end}")
        
        # 1. 执行全局风控检查
        risk_manager.check()
        
        # 2. 执行交易逻辑
        for trader in traders:
            trader.run()
            time.sleep(1) # 间隔防止API限流

    # 设置定时任务
    timeframe = config['trading']['timeframe']
    if 'm' in timeframe:
        minutes = int(timeframe.replace('m', ''))
        schedule.every(minutes).minutes.do(job)
    elif 'h' in timeframe:
        hours = int(timeframe.replace('h', ''))
        schedule.every(hours).hours.do(job)
    else:
        schedule.every(1).minutes.do(job)

    # 立即执行一次
    job()

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
