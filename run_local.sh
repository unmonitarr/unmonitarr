#!/bin/bash
# Simple script to run unmonitarr locally with .env file

# Load environment variables from .env, stripping inline comments
if [ -f .env ]; then
    export $(cat .env | sed 's/#.*//g' | grep -v '^$' | xargs)
else
    echo "Error: .env file not found"
    exit 1
fi

# Set PYTHONPATH and run
export PYTHONPATH=src
python3 src/main.py
