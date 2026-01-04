#!/bin/bash
# Code Scanner Autostart Management - macOS (LaunchAgents)
# Usage: ./autostart-macos.sh [install|remove|status] [config_path] [target_directory]

set -e

SERVICE_NAME="com.code-scanner"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$LAUNCH_AGENTS_DIR/$SERVICE_NAME.plist"

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
    echo "Code Scanner Autostart Management - macOS"
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
        which code-scanner
    elif command -v uv &> /dev/null; then
        echo "$(which uv) run code-scanner"
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
    
    # Run for 5 seconds, capture first 20 lines
    timeout 5s $scanner_cmd --config "$config_path" "$target_dir" 2>&1 | head -20 || true
    
    echo ""
    read -p "Did the test launch succeed? (y/N): " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        print_error "Test launch failed or was declined. Fix configuration before installing."
        exit 1
    fi
    print_success "Test launch verified."
}

check_legacy() {
    local config_path="$1"
    local target_dir="$2"
    
    if [[ -f "$PLIST_FILE" ]]; then
        print_warning "Found existing autostart configuration."
        echo ""
        echo "  Existing plist: $PLIST_FILE"
        echo ""
        read -p "Replace existing configuration? (y/N): " response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            print_info "Installation cancelled."
            exit 0
        fi
        
        # Unload old service before replacing
        print_info "Unloading existing service..."
        launchctl unload "$PLIST_FILE" 2>/dev/null || true
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
    config_path=$(cd "$(dirname "$config_path")" && pwd)/$(basename "$config_path")
    target_dir=$(cd "$target_dir" && pwd)
    
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
    
    # Test launch first
    test_launch "$config_path" "$target_dir" "$scanner_cmd"
    
    # Check for legacy configuration
    check_legacy "$config_path" "$target_dir"
    
    # Create LaunchAgents directory
    mkdir -p "$LAUNCH_AGENTS_DIR"
    
    # Create wrapper script with 60-second delay
    local wrapper_script="$HOME/.code-scanner/launch-wrapper.sh"
    mkdir -p "$(dirname "$wrapper_script")"
    cat > "$wrapper_script" << EOF
#!/bin/bash
# Code Scanner launch wrapper with startup delay
sleep 60
exec $scanner_cmd --config "$config_path" "$target_dir"
EOF
    chmod +x "$wrapper_script"
    
    # Create plist file
    print_info "Creating LaunchAgent plist..."
    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$SERVICE_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$wrapper_script</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$HOME/.code-scanner/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.code-scanner/launchd-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>$HOME</string>
        <key>PATH</key>
        <string>$PATH</string>
    </dict>
</dict>
</plist>
EOF

    print_success "Created plist file: $PLIST_FILE"
    
    # Load the service
    print_info "Loading LaunchAgent..."
    launchctl load "$PLIST_FILE"
    
    print_success "Code Scanner autostart installed successfully!"
    echo ""
    print_info "Useful commands:"
    echo "  launchctl list | grep code-scanner   # Check if running"
    echo "  launchctl unload \"$PLIST_FILE\"     # Stop service"
    echo "  launchctl load \"$PLIST_FILE\"       # Start service"
    echo "  cat ~/.code-scanner/launchd-*.log   # View logs"
}

remove_service() {
    if [[ ! -f "$PLIST_FILE" ]]; then
        print_warning "No autostart service found."
        exit 0
    fi
    
    print_info "Unloading LaunchAgent..."
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    
    print_info "Removing plist file..."
    rm -f "$PLIST_FILE"
    rm -f "$HOME/.code-scanner/launch-wrapper.sh"
    
    print_success "Code Scanner autostart removed."
}

show_status() {
    if [[ -f "$PLIST_FILE" ]]; then
        print_info "Plist file: $PLIST_FILE"
        echo ""
        echo "LaunchAgent status:"
        launchctl list | grep -E "code-scanner|$SERVICE_NAME" || echo "  Not currently loaded"
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
