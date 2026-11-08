"""
Lab shim: the Lab uses exactly the same pharmacy dictionary as the production system.
The single implementation lives in unified_app/modules/pharmacy_dict.py (data: unified_app/modules/pharmacy_data/).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from unified_app.modules.pharmacy_dict import (  # noqa: E402,F401
    CUSTOM_DICT_PATH,
    DATA_DIR,
    PHONETIC_MIN_SIM,
    add_custom_word,
    apply_pharmacy_dictionary,
    apply_phonetic_matching,
    clean_thai_unicode,
    correct_transcript,
    get_stats,
    load_custom_dict,
    remove_custom_word,
    save_custom_dict,
)
