"""Shape a logical line once, keeping emoji ZWJ/flag/keycap sequences atomic."""
import arabic_reshaper
from bidi import algorithm as bidi

def shaped(value, emoji_pattern=None):
    value=str(value)
    replacements={}
    if emoji_pattern is not None:
        # Bidi normally discards ZWJ, splitting families/professions into symbols.
        # Reserve only unused PUA characters and treat them as neutral objects.
        next_code=0xe000
        def protect(match):
            nonlocal next_code
            while chr(next_code) in value or chr(next_code) in replacements:next_code+=1
            code=chr(next_code);next_code+=1
            replacements[code]=match.group()
            return code
        value=emoji_pattern.sub(protect,value)
    value=arabic_reshaper.reshape(value)
    if not replacements:return bidi.get_display(value)
    storage=bidi.get_empty_storage()
    base=bidi.get_base_level(''.join('\ufffc' if c in replacements else c for c in value))
    storage['base_level']=base;storage['base_dir']=('L','R')[base]
    bidi.get_embedding_levels(value,storage,False,False)
    for char in storage['chars']:
        if char['ch'] in replacements:char['type']=char['orig']='ON'
    for operation in (bidi.explicit_embed_and_overrides,bidi.resolve_weak_types,bidi.resolve_neutral_types,
                      bidi.resolve_implicit_levels,bidi.reorder_resolved_levels,bidi.apply_mirroring):
        operation(storage,False)
    return ''.join(replacements.get(c['ch'],c['ch']) for c in storage['chars'])
