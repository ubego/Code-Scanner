#!/bin/bash
# Code Scanner Autostart Management - Linux (systemd)
# Usage: ./autostart-linux.sh [install|remove|status] [config_path] [target_directory]

set -e

SERVICE_NAME="code-scanner"
USER_SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$USER_SERVICE_DIR/$SERVICE_NAME.service"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    echo "Code Scanner Autostart Management - Linux"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  install <config_path> <target_directory>  Install autostart service"
    echo "  remove                                     Remove autostart service"
    echo "  status                                     Check service status"
    echo ""
    echo "Examples:"
    echo "  $0 install /path/to/config.toml /path/to/project"
    echo "  $0 remove"
    echo "  $0 status"
    exit 1
}

find_code_scanner() {
    # Try to find code-scanner executable
    if command -v code-scanner &> /dev/null; then
        echo "code-scanner"
    elif command -v uv &> /dev/null; then
        echo "uv run code-scanner"
    else
        print_error "Could not find code-scanner or uv. Please install code-scanner first."
        exit 1
    fi
}

test_launch() {
    local config_path="$1"
    local target_dir="$2"
    local scanner_cmd="$3"
    
    print_info "Testing code-scanner launch..."
    print_info "Command: $scanner_cmd --config \"$config_path\" \"$target_dir\""
    echo ""
    
    # Run for 5 seconds, capture output
    local output
    output=$(timeout 5s $scanner_cmd --config "$config_path" "$target_dir" 2>&1 | head -30) || true
    
    echo "$output"
    echo ""
    
    # Check for success indicators
    if echo "$output" | grep -q "Scanner running\|Scanner loop started\|Scanner thread started"; then
        print_success "Test launch succeeded - scanner started correctly."
        return 0
    fi
    
    # Check for common error patterns
    if echo "$output" | grep -qi "error\|failed\|exception\|traceback\|could not\|cannot\|refused"; then
        print_error "Test launch failed. Please fix the issues above and try again."
        exit 1
    fi
    
    # No clear success or failure - warn but continue
    print_warning "Could not automatically verify launch success."
    print_warning "Please check the output above and ensure code-scanner starts correctly."
    read -p "Continue with installation? (y/N): " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        print_error "Installation cancelled."
        exit 1
    fi
}

check_legacy() {
    local new_exec="$1"
    
    if [[ -f "$SERVICE_FILE" ]]; then
        local current_exec
        current_exec=$(grep "^ExecStart=" "$SERVICE_FILE" | cut -d= -f2-)
        
        if [[ "$current_exec" != "$new_exec" ]]; then
            print_warning "Found existing autostart with different configuration:"
            echo ""
            echo "  Current: $current_exec"
            echo "  New:     $new_exec"
            echo ""
            read -p "Replace existing configuration? (y/N): " response
            if [[ ! "$response" =~ ^[Yy]$ ]]; then
                print_info "Installation cancelled."
                exit 0
            fi
            
            # Stop old service before replacing
            print_info "Stopping existing service..."
            systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
        fi
    fi
}

install_service() {
    local config_path="$1"
    local target_dir="$2"
    
    if [[ -z "$config_path" ]] || [[ -z "$target_dir" ]]; then
        print_error "Missing arguments. Usage: $0 install <config_path> <target_directory>"
        exit 1
    fi
    
    # Resolve paths to absolute
    config_path=$(realpath "$config_path")
    target_dir=$(realpath "$target_dir")
    
    # Verify files exist
    if [[ ! -f "$config_path" ]]; then
        print_error "Config file not found: $config_path"
        exit 1
    fi
    if [[ ! -d "$target_dir" ]]; then
        print_error "Target directory not found: $target_dir"
        exit 1
    fi
    
    # Find code-scanner
    local scanner_cmd
    scanner_cmd=$(find_code_scanner)
    
    # Build the command with 60-second delay
    local exec_start="sleep 60 && $scanner_cmd --config \"$config_path\" \"$target_dir\""
    
    # Test launch first
    test_launch "$config_path" "$target_dir" "$scanner_cmd"
    
    # Check for legacy configuration
    check_legacy "$exec_start"
    
    # Create service directory
    mkdir -p "$USER_SERVICE_DIR"
    
    # Create systemd service file
    print_info "Creating systemd service file..."
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Code Scanner - AI-driven code analysis for $target_dir
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash -c '$exec_start'
Restart=no
Environment=HOME=$HOME
Environment=PATH=$PATH

[Install]
WantedBy=default.target
EOF

    print_success "Created service file: $SERVICE_FILE"
    
    # Reload systemd and enable service
    print_info "Enabling and starting service..."
    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user start "$SERVICE_NAME"
    
    print_success "Code Scanner autostart installed successfully!"
    echo ""
    print_info "Useful commands:"
    echo "  systemctl --user status $SERVICE_NAME  # Check status"
    echo "  systemctl --user stop $SERVICE_NAME    # Stop service"
    echo "  systemctl --user start $SERVICE_NAME   # Start service"
    echo "  journalctl --user -u $SERVICE_NAME     # View logs"
}

remove_service() {
    if [[ ! -f "$SERVICE_FILE" ]]; then
        print_warning "No autostart service found."
        exit 0
    fi
    
    print_info "Stopping and disabling service..."
    systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    
    print_info "Removing service file..."
    rm -f "$SERVICE_FILE"
    systemctl --user daemon-reload
    
    print_success "Code Scanner autostart removed."
}

show_status() {
    if [[ -f "$SERVICE_FILE" ]]; then
        print_info "Service file: $SERVICE_FILE"
        echo ""
        systemctl --user status "$SERVICE_NAME" || true
    else
        print_warning "No autostart service configured."
    fi
}

# Main
case "${1:-}" in
    install)
        install_service "$2" "$3"
        ;;
    remove)
        remove_service
        ;;
    status)
        show_status
        ;;
    *)
        usage
        ;;
esac
