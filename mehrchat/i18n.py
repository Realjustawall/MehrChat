"""UI translation only; message contents never pass through this catalogue."""
import json
from pathlib import Path
from .appearance import appearance
EN=json.loads((Path(__file__).resolve().parent.parent/'assets/en.json').read_text(encoding='utf-8'))
def tr(text):
    text=str(text)
    if appearance.language=='fa':return text
    if text in EN:return EN[text]
    for prefix in ('مهر · ','نسخه ','فایل: '):
        if text.startswith(prefix):return EN[prefix]+text[len(prefix):]
    # Translating each complete line preserves names, keys and user-supplied data.
    return '\n'.join(EN.get(line,line) for line in text.split('\n'))
