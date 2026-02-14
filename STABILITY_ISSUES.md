# Nanobot 稳定性问题诊断报告

## 发现的问题

### 1. 🔴 致命问题：主循环缺少异常处理

**位置：** `nanobot/cli/commands.py:270-285`

**问题代码：**
```python
async def run():
    try:
        await cron.start()
        await heartbeat.start()
        await asyncio.gather(
            agent.run(),
            channels.start_all(),
        )
    except KeyboardInterrupt:
        console.print("\nShutting down...")
        heartbeat.stop()
        cron.stop()
        agent.stop()
        await channels.stop_all()

asyncio.run(run())
```

**问题分析：**
- ❌ 只捕获 `KeyboardInterrupt`，其他所有异常都会导致程序直接退出
- ❌ 如果 `agent.run()` 或 `channels.start_all()` 抛出任何异常，程序会崩溃
- ❌ `asyncio.gather()` 默认在第一个异常时就会停止所有任务
- ❌ 没有异常日志，无法诊断崩溃原因

**影响：**
- 任何未预料的异常都会导致整个服务停止
- 无法在日志中看到崩溃原因
- 服务器上看起来像是"自动停止"

### 2. 🟡 日志配置缺失

**问题：**
- 代码中使用 `loguru` 的 `logger`，但没有配置日志输出
- 默认只输出到 stderr，服务器后台运行时可能丢失
- 没有日志文件持久化

**影响：**
- 错误信息可能看不到
- 无法事后分析问题
- 调试困难

### 3. 🟡 Agent Loop 可能静默退出

**位置：** `nanobot/agent/loop.py:97-124`

**问题代码：**
```python
async def run(self) -> None:
    """Run the agent loop, processing messages from the bus."""
    self._running = True
    logger.info("Agent loop started")

    while self._running:
        try:
            msg = await asyncio.wait_for(
                self.bus.consume_inbound(),
                timeout=1.0
            )
            # ... process message
        except asyncio.TimeoutError:
            continue
```

**问题分析：**
- ✅ 内部异常处理正确
- ⚠️ 但如果 `while` 循环因为 `self._running = False` 退出，`run()` 方法会返回
- ⚠️ 这会导致 `asyncio.gather()` 中的一个任务完成，可能触发整体退出

### 4. 🟢 Heartbeat 和 Cron 服务正常

**检查结果：**
- ✅ Heartbeat 有完整的异常处理
- ✅ Cron 有完整的异常处理
- ✅ 都使用后台任务，不会阻塞主循环

## 修复方案

### 修复 1：添加全局异常处理和日志

**优先级：** 🔴 高

```python
async def run():
    try:
        await cron.start()
        await heartbeat.start()
        await asyncio.gather(
            agent.run(),
            channels.start_all(),
        )
    except KeyboardInterrupt:
        console.print("\nShutting down...")
    except Exception as e:
        logger.exception(f"Fatal error in main loop: {e}")
        console.print(f"[red]Fatal error: {e}[/red]")
        raise
    finally:
        # Always cleanup
        heartbeat.stop()
        cron.stop()
        agent.stop()
        await channels.stop_all()
```

### 修复 2：配置日志文件输出

**优先级：** 🔴 高

在 `serve` 命令开始时添加：

```python
from loguru import logger
import sys

# Configure logger to write to file
log_dir = Path.home() / ".nanobot" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "nanobot.log"

# Remove default handler
logger.remove()

# Add file handler with rotation
logger.add(
    log_file,
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
)

# Also keep stderr output
logger.add(
    sys.stderr,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
)

logger.info(f"Logging to {log_file}")
```

### 修复 3：使用 return_exceptions 保持运行

**优先级：** 🟡 中

```python
await asyncio.gather(
    agent.run(),
    channels.start_all(),
    return_exceptions=True  # 不要因为一个任务失败就停止所有任务
)
```

但需要检查返回值：

```python
results = await asyncio.gather(
    agent.run(),
    channels.start_all(),
    return_exceptions=True
)

for i, result in enumerate(results):
    if isinstance(result, Exception):
        logger.error(f"Task {i} failed: {result}")
```

## 测试建议

### 1. 添加崩溃测试

创建测试脚本模拟各种异常：

```python
# test_crash.py
import asyncio

async def test_agent_crash():
    """Test what happens when agent crashes"""
    await asyncio.sleep(5)
    raise RuntimeError("Simulated agent crash")

async def test_channel_crash():
    """Test what happens when channel crashes"""
    await asyncio.sleep(3)
    raise ConnectionError("Simulated channel crash")

async def main():
    try:
        await asyncio.gather(
            test_agent_crash(),
            test_channel_crash(),
        )
    except Exception as e:
        print(f"Caught: {e}")

asyncio.run(main())
```

### 2. 监控脚本

创建监控脚本检测进程状态：

```bash
#!/bin/bash
# monitor_nanobot.sh

while true; do
    if ! pgrep -f "nanobot serve" > /dev/null; then
        echo "$(date): nanobot not running, restarting..."
        cd /path/to/nanobot
        nohup nanobot serve >> /tmp/nanobot_monitor.log 2>&1 &
    fi
    sleep 60
done
```

## 部署建议

### 使用 systemd 服务（推荐）

创建 `/etc/systemd/system/nanobot.service`:

```ini
[Unit]
Description=Nanobot AI Assistant
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/nanobot
ExecStart=/usr/local/bin/nanobot serve
Restart=always
RestartSec=10
StandardOutput=append:/var/log/nanobot/stdout.log
StandardError=append:/var/log/nanobot/stderr.log

[Install]
WantedBy=multi-user.target
```

启用服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable nanobot
sudo systemctl start nanobot
```

查看日志：
```bash
sudo journalctl -u nanobot -f
```

## 预期效果

修复后：
- ✅ 所有异常都会被捕获和记录
- ✅ 日志持久化到文件，可以事后分析
- ✅ 程序崩溃时有明确的错误信息
- ✅ 使用 systemd 自动重启
- ✅ 可以追踪停机原因

## 立即行动

1. **添加日志配置**（最重要）
2. **添加全局异常处理**
3. **使用 systemd 管理服务**
4. **监控日志文件**

这样就能看到程序为什么停止了。
