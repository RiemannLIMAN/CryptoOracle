# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v2.3] - 2025-12-20 (System Optimization)

### 🔧 Core Fixes & Improvements
- **Config Auto-Patch**:
    - Fixed an issue where the `notification` configuration in the root directory of `config.json` was ignored.
    - Added auto-detection logic: if the notification config exists in the root but is missing under `trading`, the system automatically merges it to ensure Feishu/DingTalk messages are sent correctly.
- **Version Management Refactor**:
    - Extracted system version (`SYSTEM_VERSION`) and feature description (`VERSION_FEATURE`) into global constants.
    - Simplified version iteration and maintenance, eliminating the need to deep-dive into code to update the Banner display.

## [v2.2] - 2025-12-19 (Security Hardening)

### 🔒 Security & Configuration
- **Environment Variable Support (.env)**:
    - Migrated sensitive credentials (API Keys, Secrets, Passwords) from `config.json` to `.env` file.
    - Added `python-dotenv` dependency to auto-load environment variables.
    - Created `.env.example` template for safe sharing and deployment.
- **Git Security**:
    - Updated `.gitignore` to strictly exclude `.env` files, preventing accidental key leakage.
    - Removed sensitive data from `config.json` and replaced with placeholders.
- **Documentation**:
    - Updated `README.md` and `CONFIG_README.md` with new secure configuration guides.
    - Added `GIT_UPLOAD_GUIDE.md` for standardized deployment workflows.

## [v2.1] - 2025-12-18 (Trend-Falcon Upgrade)

### 🚀 New Core Features
- **Trend-Aware Reversal Logic**:
    - Empowered AI to recognize positions that are fighting the trend.
    - When a position deviates from a strong trend, the AI can proactively suggest closing the position and immediately opening a reverse order (e.g., Close Short -> Open Long), turning potential losses into profit opportunities.
- **RSI Passivation Warning**:
    - Optimized AI prompts to explicitly warn: In strong trends (ADX > 30), RSI indicators can become passivated (invalid). It is strictly forbidden to short solely based on RSI > 80.
- **Stop-Loss Priority**:
    - Established the principle of Stop-Loss Priority. If floating loss exceeds 3% and the trend has not changed, the AI will no longer wait for a perfect candlestick reversal pattern but will suggest an immediate stop-loss exit.

### 🛡️ Risk Control Adjustments
- **Anti-Liquidation Mode**:
    - Increased max loss amount (`max_loss_usdt`) from 5.0 USDT to **15.0 USDT**.
    - Increased max loss rate (`max_loss_rate`) from 10% to **15%**.
    - *Goal*: Enhance account resilience and prevent premature washouts during violent fluctuations or "pin bars".

### ⚙️ System Optimizations
- **Unified Logging**:
    - Deprecated independent startup logs; merged everything into `trading_bot.log`.
    - Fixed the issue of double console output.
- **Windows Support**:
    - Added `src/start_bot.bat` script for one-click startup on Windows.

---

## [v2.0] - 2025-12-17 (Initial Release)
- **Hybrid AI Decision Engine**: Integrated DeepSeek-V3 with CCXT.
- **Dynamic Persona AI**: Switches between Trend/Grid/Defensive modes based on ADX/ATR.
- **Triple-Layer Risk Control**: Config Lock, AI Soft Limit, Balance Hard Limit.
- **Smart Capital Governance**: Independent fund allocation for each symbol.
