#!/usr/bin/env python3
"""
Speech-to-Text Application Entry Point
Main entry point for the Streamlit application
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run the main Streamlit app
from frontend.streamlit_app import main

if __name__ == "__main__":
    main()
