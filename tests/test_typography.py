import json
from pathlib import Path
import re
import unittest
from mehrchat.bidi_text import shaped

class TextShaping(unittest.TestCase):
    def test_persian_joining_and_password_hint(self):
        self.assertIn('\ufeb3',shaped('سلام'))
        self.assertNotEqual(shaped('رمز عبور'),'رمز عبور')
    def test_emoji_sequences_survive_bidi(self):
        emoji=['👨\u200d👩\u200d👧\u200d👦','👍🏽','🏳️\u200d🌈','1️⃣']
        pattern=re.compile('|'.join(re.escape(v) for v in emoji))
        value=shaped('سلام '+' '.join(emoji)+' English',pattern)
        for e in emoji:self.assertIn(e,value)
        self.assertIn('English',value)
    def test_complete_unicode17_catalog_and_atlas_bounds(self):
        root=Path(__file__).resolve().parents[1]/'assets'
        canonical=json.loads((root/'emoji.json').read_text())
        data=json.loads((root/'emoji-atlas.json').read_text())
        self.assertGreaterEqual(len(canonical),3944)
        self.assertEqual(len(canonical),len(set(canonical)))
        from PIL import Image
        for page in range(4):
            with Image.open(root/f'emoji-atlas-{page}.png') as image:image.verify()
        for emoji in canonical:
            item=data[emoji]
            self.assertTrue((root/f"emoji-atlas-{item['page']}.png").is_file())
            self.assertLessEqual(item['x']+48,1536);self.assertLessEqual(item['y']+48,1536)
    def test_english_catalog_covers_onboarding(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'assets/en.json').read_text())
        for source in ['ورود','ساخت حساب','رمز عبور','نمایش و زبان','پیش‌نمایش','ارسال','تیره','روشن']:
            self.assertNotRegex(data[source],r'[\u0600-\u06ff]')
