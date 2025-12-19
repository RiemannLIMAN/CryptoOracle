# 🚀 启动脚本使用指南 (Script Usage Guide)

为了方便在 Linux (Ubuntu/CentOS) 服务器上长期稳定运行机器人，我们提供了一键启动脚本 `src/start_bot.sh`。

## ✨ 脚本功能
1.  **自动环境识别**：智能检测 `venv`, `conda` 或系统 Python 环境。
2.  **后台静默运行**：使用 `nohup` 让机器人在后台运行，关闭 SSH 窗口也不会断开。
3.  **防重复启动**：自动检测是否已有实例运行，防止资金冲突。
4.  **启动自检**：启动后自动监控前 5 秒状态，确保没有报错退出。

---

## 🛠️ 快速开始

### 1. 赋予执行权限 (首次需要)
进入 `src` 目录，赋予脚本可执行权限：

```bash
cd OKXBot_Workspace/src
chmod +x start_bot.sh
```

### 2. 启动机器人
直接运行脚本：

```bash
./start_bot.sh
```

**启动成功示例**：
```text
✅ 检测到已激活的 Conda 环境: /root/anaconda3/envs/okx_ds
⚡ 正在启动后台进程...
⏳ 正在验证进程状态 (PID: 69014)，请等待 5 秒...
✅ 启动成功！机器人正在后台运行。
🆔 进程 PID: 69014
📄 日志文件: ../log/startup_20251217_xxxx.log
```

---

## 🪟 Windows 用户 (推荐)

我们提供了 `src/start_bot.bat` 批处理脚本，支持自动检测 `venv` 并启动。

### 启动方法
1. 进入 `src` 文件夹。
2. 双击运行 `start_bot.bat` (或者在 CMD 中运行)。
3. **注意**: 请保持黑色命令窗口开启。Windows 暂不支持像 Linux 那样的 `nohup` 后台模式，关闭窗口会停止机器人。

---

## ⚙️ 高级配置 (自定义虚拟环境)

如果您使用了自定义名称的虚拟环境（例如 `okx_ds` 或 `my_env`），脚本默认可能找不到。您可以有两种方式解决：

### 方法 A：先激活环境 (推荐)
在运行脚本前，手动激活您的环境：
```bash
conda activate okx_ds
./start_bot.sh
```
*脚本会自动识别当前激活的环境，无需修改代码。*

### 方法 B：修改脚本配置
编辑 `start_bot.sh` 文件，修改第 31 行：
```bash
# [可配置] 设置您的虚拟环境名称
CUSTOM_VENV_NAME="okx_ds"
```
这样脚本就能自动扫描到 `../okx_ds` 目录了。

---

## 🕹️ 运维管理

### 查看实时日志
启动成功后，脚本会提示日志路径。您可以使用 `tail -f` 实时查看：
```bash
# 查看启动日志 (包含报错信息)
tail -f ../log/startup.log

# 查看交易日志 (包含详细策略输出)
# 找到 log 目录下最新的 trading_bot_xxx.log 文件
tail -f ../log/trading_bot_2025xxxx.log
```

### 停止机器人
脚本启动成功后会显示 PID (进程ID)。
```bash
# 方式 1: 使用 PID (假设 PID 是 69014)
kill 69014

# 方式 2: 查找并杀掉所有 python 进程 (慎用)
ps -ef | grep okx_deepseek.py
# 找到 PID 后 kill
```

---

## ❓ 常见问题

**Q: 提示 `Permission denied`?**
A: 忘记执行 `chmod +x start_bot.sh` 了。

**Q: 提示 `Exit 127` 或 `command not found`?**
A: 服务器没安装 Python，或者脚本没找到您的 Python 环境。请尝试 **方法 A** (先激活环境)。

**Q: 提示 `检测到机器人已在运行`?**
A: 脚本发现旧进程还在。输入 `y` 可以自动杀掉旧进程并重启，输入 `n` 则取消操作。
