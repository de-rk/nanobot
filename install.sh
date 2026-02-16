#!/bin/bash
#
# Nanobot Systemd Service Installation Script
#
# This is a standalone alternative to: nanobot install-service
# Use this if you prefer a shell script or if the CLI command is unavailable.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Nanobot Service Installation ===${NC}"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}Error: Please do not run this script as root${NC}"
    echo "Run as your normal user. The script will ask for sudo when needed."
    exit 1
fi

# Get current user and working directory
CURRENT_USER=$(whoami)
NANOBOT_DIR=$(pwd)
NANOBOT_BIN=$(which nanobot 2>/dev/null || echo "")

if [ -z "$NANOBOT_BIN" ]; then
    echo -e "${RED}Error: nanobot command not found in PATH${NC}"
    echo "Please install nanobot first:"
    echo "  pip install -e ."
    echo "  or: uv tool install nanobot-ai"
    exit 1
fi

echo -e "${BLUE}Configuration:${NC}"
echo "  User: $CURRENT_USER"
echo "  Working Directory: $NANOBOT_DIR"
echo "  Nanobot Binary: $NANOBOT_BIN"
echo ""

# Check if service already exists
if [ -f "/etc/systemd/system/nanobot.service" ]; then
    echo -e "${YELLOW}Warning: nanobot.service already exists${NC}"
    read -p "Do you want to overwrite it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
    echo -e "${YELLOW}Stopping existing service...${NC}"
    sudo systemctl stop nanobot 2>/dev/null || true
fi

# Create log directory
echo -e "${YELLOW}Creating log directory...${NC}"
sudo mkdir -p /var/log/nanobot
sudo chown $CURRENT_USER:$CURRENT_USER /var/log/nanobot
echo -e "${GREEN}✓${NC} Log directory created"

# Generate service file from template
echo -e "${YELLOW}Generating service file...${NC}"
SERVICE_FILE="/tmp/nanobot.service"
cat > $SERVICE_FILE << EOF
[Unit]
Description=Nanobot AI Assistant
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$NANOBOT_DIR
ExecStart=$NANOBOT_BIN gateway
Restart=always
RestartSec=10
StandardOutput=append:/var/log/nanobot/stdout.log
StandardError=append:/var/log/nanobot/stderr.log

# Prevent memory leaks from crashing the system
MemoryMax=2G
MemoryHigh=1.5G

[Install]
WantedBy=multi-user.target
EOF

EOF

echo -e "${GREEN}✓${NC} Service file generated"

# Install service file
echo -e "${YELLOW}Installing systemd service...${NC}"
sudo cp $SERVICE_FILE /etc/systemd/system/nanobot.service
sudo chmod 644 /etc/systemd/system/nanobot.service
echo -e "${GREEN}✓${NC} Service file installed"

# Reload systemd
echo -e "${YELLOW}Reloading systemd daemon...${NC}"
sudo systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd reloaded"

# Enable service
echo -e "${YELLOW}Enabling nanobot service...${NC}"
sudo systemctl enable nanobot.service
echo -e "${GREEN}✓${NC} Service enabled (will start on boot)"

# Start service
echo -e "${YELLOW}Starting nanobot service...${NC}"
sudo systemctl start nanobot.service
echo -e "${GREEN}✓${NC} Service started"

# Wait a moment for service to initialize
sleep 2

# Check status
echo ""
echo -e "${GREEN}=== Installation Complete ===${NC}"
echo ""
echo "Service status:"
sudo systemctl status nanobot.service --no-pager -l || true

echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo "  Check status:  ${GREEN}sudo systemctl status nanobot${NC}"
echo "  View logs:     ${GREEN}sudo journalctl -u nanobot -f${NC}"
echo "  Stop service:  ${GREEN}sudo systemctl stop nanobot${NC}"
echo "  Start service: ${GREEN}sudo systemctl start nanobot${NC}"
echo "  Restart:       ${GREEN}sudo systemctl restart nanobot${NC}"
echo "  Disable:       ${GREEN}sudo systemctl disable nanobot${NC}"
echo ""
echo -e "${BLUE}Log files:${NC}"
echo "  stdout: /var/log/nanobot/stdout.log"
echo "  stderr: /var/log/nanobot/stderr.log"
echo ""
echo -e "${YELLOW}Note:${NC} The service has memory limits (2GB max) to prevent system crashes."
