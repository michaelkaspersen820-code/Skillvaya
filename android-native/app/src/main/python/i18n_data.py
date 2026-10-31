"""SV82-I18N: Skillvaya on-screen wording in other languages (built by build_i18n.py; do not edit by hand)."""
import json, os
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n_data.json"), encoding="utf-8") as _f:
    _D = json.load(_f)
VERSION = _D["version"]
I18N = _D["langs"]
