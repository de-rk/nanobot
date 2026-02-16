#!/usr/bin/env python3
"""Diagnose Telegram bot conflicts by checking running processes and connections."""

import subprocess
import sys


def run_command(cmd):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"


def main():
    print("=" * 60)
    print("Telegram Bot Conflict Diagnostic")
    print("=" * 60)
    print()

    # Check for Python processes
    print("1. Checking for Python/nanobot processes:")
    print("-" * 60)
    output = run_command("ps aux | grep -E 'python.*nanobot|nanobot.*py' | grep -v grep | grep -v diagnose")
    if output:
        print(output)
        print()
        print("⚠️  Found running nanobot processes!")
        print("   Run: pkill -9 -f 'python.*nanobot' to stop them")
    else:
        print("✓ No nanobot processes found")
    print()

    # Check for processes on nanobot port
    print("2. Checking port 18790 (nanobot gateway):")
    print("-" * 60)
    output = run_command("lsof -i :18790 2>/dev/null || netstat -tuln 2>/dev/null | grep 18790")
    if output:
        print(output)
        print()
        print("⚠️  Port 18790 is in use")
    else:
        print("✓ Port 18790 is free")
    print()

    # Check systemd services
    print("3. Checking systemd services:")
    print("-" * 60)
    output = run_command("systemctl --user list-units | grep nanobot 2>/dev/null || echo 'No systemd services found'")
    print(output)
    print()

    # Check for screen/tmux sessions
    print("4. Checking screen/tmux sessions:")
    print("-" * 60)
    screen_output = run_command("screen -ls 2>/dev/null | grep -i nanobot || echo 'No screen sessions'")
    tmux_output = run_command("tmux ls 2>/dev/null | grep -i nanobot || echo 'No tmux sessions'")
    print(f"Screen: {screen_output}")
    print(f"Tmux: {tmux_output}")
    print()

    # Check Docker containers
    print("5. Checking Docker containers:")
    print("-" * 60)
    output = run_command("docker ps | grep nanobot 2>/dev/null || echo 'No Docker containers found'")
    print(output)
    print()

    print("=" * 60)
    print("Diagnostic complete")
    print("=" * 60)
    print()
    print("If you found multiple instances, stop them all before restarting:")
    print("  1. pkill -9 -f 'python.*nanobot'")
    print("  2. systemctl --user stop nanobot (if using systemd)")
    print("  3. docker stop <container> (if using Docker)")
    print("  4. Wait 30 seconds")
    print("  5. python3 scripts/clear_telegram_webhook.py")
    print("  6. Restart nanobot")


if __name__ == "__main__":
    main()
