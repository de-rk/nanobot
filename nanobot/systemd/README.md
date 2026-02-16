# Nanobot Systemd Service

This directory contains the systemd service template for running nanobot as a system service.

## Installation

After installing nanobot, run:

```bash
# Install the service (will prompt for sudo password)
nanobot install-service

# Start the service
sudo systemctl start nanobot

# Check status
sudo systemctl status nanobot

# View logs
sudo journalctl -u nanobot -f
```

## Custom Installation

You can specify a custom user and working directory:

```bash
nanobot install-service --user myuser --workdir /path/to/nanobot
```

## Uninstallation

```bash
nanobot uninstall-service
```

## Features

- **Auto-restart**: Service automatically restarts on failure
- **Memory limits**: Prevents memory leaks from crashing the system (2GB max)
- **Logging**: Logs to `~/.nanobot/workspace/logs/` (separate from application logs)
- **Clean shutdown**: Properly stops all channels and services

## Log Files

The service creates separate log files in `~/.nanobot/workspace/logs/`:
- `nanobot.log` - Application log (from nanobot gateway)
- `service.log` - Service stdout
- `service-error.log` - Service stderr

## Manual Installation

If you prefer to install manually:

1. Copy the template:
   ```bash
   sudo cp nanobot.service.template /etc/systemd/system/nanobot.service
   ```

2. Edit the file and replace placeholders:
   - `{user}` - User to run as
   - `{workdir}` - Working directory
   - `{nanobot_path}` - Path to nanobot executable
   - `{log_dir}` - Log directory path (e.g., /root/.nanobot/workspace/logs)

3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable nanobot
   sudo systemctl start nanobot
   ```
