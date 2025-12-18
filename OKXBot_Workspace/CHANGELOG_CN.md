# 变更日志 (Changelog)

本项目的所有重大变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵守 [语义化版本控制](https://semver.org/lang/zh-CN/spec/v2.0.0.html)。

---

## [v2.1] - 2025-12-18 (趋势猎鹰升级 Trend-Falcon Upgrade)

### 🚀 新增核心特性
- **趋势反手逻辑 (Trend-Aware Reversal Logic)**:
    - 赋予 AI 识别逆势持仓的能力。
    - 当持仓方向与强趋势背离时，AI 能够主动建议平仓并立即反手开单（例如：平空 -> 开多），将潜在亏损转化为盈利机会。
- **RSI 钝化警示 (RSI Passivation Warning)**:
    - 优化 AI 提示词，明确警示：在强趋势（ADX > 30）下，RSI 指标会钝化（失效）。严禁仅凭 RSI > 80 就逆势做空。
- **止损优先 (Stop-Loss Priority)**:
    - 确立止损优先原则。如果浮亏超过 3% 且趋势未变，AI 将不再等待完美的 K 线反转形态，而是直接建议止损离场。

### 🛡️ 风控体系调整
- **抗单模式 (Anti-Liquidation Mode)**:
    - 将最大亏损额 (`max_loss_usdt`) 从 5.0 U 提升至 **15.0 U**。
    - 将最大亏损率 (`max_loss_rate`) 从 10% 提升至 **15%**。
    - *目的*: 增强账户韧性，防止在剧烈波动或“插针”行情中被过早清洗出局。

### ⚙️ 系统优化
- **日志统一 (Unified Logging)**:
    - 废弃独立的启动日志，统一合并至 `trading_bot.log`。
    - 修复了控制台双重输出的问题。
- **Windows 适配 (Windows Support)**:
    - 新增 `src/start_bot.bat` 脚本，支持 Windows 环境一键启动。

---

## [v2.0] - 2025-12-17 (初始版本)
- **混合智能决策引擎**: 集成 DeepSeek-V3 与 CCXT。
- **动态人格 AI**: 基于 ADX/ATR 切换 趋势/震荡/网格 模式。
- **三重风控体系**: 配置锁、AI 软限、余额硬限。
- **智能资金治理**: 针对每个币种独立分配资金。
