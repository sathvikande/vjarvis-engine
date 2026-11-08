#!/usr/bin/env bash
set -e

# ==============================================================================
# vjarvis-engine Automated 1-Click Installer
# ==============================================================================

BOLD="\033[1m"
GREEN="\033[0;32m"
CYAN="\033[0;36m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
NC="\033[0m"

echo -e "${BOLD}${CYAN}=== Installing vjarvis-engine ===${NC}"

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[Error] python3 could not be found. Please install Python 3.9+ first.${NC}"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}[✓] Detected Python ${PY_VERSION}${NC}"

# 2. Setup Virtual Environment
VENV_DIR="$HOME/.vjarvis/venv"
echo -e "${CYAN}[*] Setting up isolated environment at ${VENV_DIR}...${NC}"
mkdir -p "$HOME/.vjarvis"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# 3. Upgrade pip and install package + dependencies
echo -e "${CYAN}[*] Downloading and installing all dependencies...${NC}"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r requirements.txt --quiet
"$VENV_DIR/bin/pip" install -e . --quiet

# 4. Link CLI binary to ~/.local/bin
INSTALL_BIN_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_BIN_DIR"

ln -sf "$VENV_DIR/bin/vjarvis" "$INSTALL_BIN_DIR/vjarvis"
echo -e "${GREEN}[✓] Binary symlinked to ${INSTALL_BIN_DIR}/vjarvis${NC}"

# 5. Check PATH
case ":$PATH:" in
  *":$INSTALL_BIN_DIR:"*) ;;
  *)
    echo -e "${YELLOW}[!] Note: ${INSTALL_BIN_DIR} is not currently in your PATH.${NC}"
    echo -e "${YELLOW}    Add it by running:${NC}"
    echo -e "    ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
    echo -e "${YELLOW}    (Add this line to your ~/.bashrc or ~/.zshrc)${NC}"
    ;;
esac

# 6. Run quick self-test
echo -e "${CYAN}[*] Running self-test suite...${NC}"
"$VENV_DIR/bin/pytest" -q

echo -e "\n${BOLD}${GREEN}======================================================================${NC}"
echo -e "${BOLD}${GREEN}  vjarvis-engine installed successfully!                              ${NC}"
echo -e "${BOLD}${GREEN}======================================================================${NC}"
echo -e "You can now run vjarvis commands directly from anywhere:\n"
echo -e "  ${BOLD}vjarvis --help${NC}      # View all commands"
echo -e "  ${BOLD}vjarvis serve${NC}       # Start the local FastAPI metrics bridge"
echo -e "  ${BOLD}vjarvis patch ...${NC}   # Run interactive patcher & rollback loop"
echo -e "  ${BOLD}vjarvis auto ...${NC}    # Automated AI log triage & patch"
echo -e "  ${BOLD}vjarvis metrics${NC}     # Inspect live regression statistics\n"
