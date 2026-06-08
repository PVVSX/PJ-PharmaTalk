"""
CSS styles for Streamlit UI
"""
CUSTOM_CSS = """
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        color: #1f77b4;
        margin-bottom: 2rem;
    }
    .status-box {
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .status-success {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .status-warning {
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        color: #856404;
    }
    .status-error {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    .mic-button {
        width: 100%;
        height: 60px;
        font-size: 1.2rem;
        margin: 0.5rem 0;
    }
    /* Enlarge main record toggle button */
    button[key="record_toggle_button"] {
        font-size: 1.6rem !important;
        padding: 1.1rem 0.75rem !important;
        border-radius: 14px !important;
        font-weight: bold !important;
    }
    /* Keep buttons inside expanders compact */
    div[data-testid="stExpander"] div.stButton > button {
        font-size: 0.9rem !important;
        padding: 0.45rem 0.6rem !important;
        border-radius: 6px !important;
    }
</style>
"""

