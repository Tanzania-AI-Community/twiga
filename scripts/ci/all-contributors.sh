#!/bin/bash

# Script to manage contributors in a GitHub repository
# This is a wrapper for the all_contributors.py script

# Exit if any command fails
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/all_contributors.py"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${ROOT_DIR}"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check if the required Python packages are installed
if ! python3 -c "import requests" &> /dev/null; then
    echo "Installing required Python packages..."
    pip install requests
fi

# Make sure the Python script is executable
chmod +x "${PYTHON_SCRIPT}"

# Pass all arguments to the Python script
python3 "${PYTHON_SCRIPT}" "$@"
