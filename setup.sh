#!/bin/bash
# Setup script for Workload Model Calculator
# Creates a virtual environment and installs dependencies

set -e

echo "Setting up Workload Model Calculator..."

# Check Python version
python3 --version || {
    echo "ERROR: python3 not found. Please install Python 3.8+."
    exit 1
}

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo "Run 'python main.py' to execute the calculator."
echo "Run 'python main.py --dry-run' to see a data summary."
