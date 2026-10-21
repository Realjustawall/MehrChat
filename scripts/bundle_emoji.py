"""Build offline 48px emoji atlases from pinned Twemoji 17 and Unicode emoji-test."""
import argparse, json, re, math
from pathlib import Path
from PIL import Image
parser=argparse.ArgumentParser();parser.add_argument('twemoji');parser.add_argument('unicode_test');args=parser.parse_args()
assets=Path('assets');root=Path(args.twemoji)/'assets/72x72';entries=[];group='';subgroup=''
for line in Path(args.unicode_test).read_text(encoding='utf-8').splitlines():
    if line.startswith('# group:'):group=line.split(':',1)[1].strip()
    if line.startswith('# subgroup:'):subgroup=line.split(':',1)[1].strip()
    m=re.match(r'^([0-9A-F ]+)\s*; fully-qualified\s*#\s*\S+\s+E[\d.]+\s+(.+)$',line)
    if not m:continue
    value=''.join(chr(int(n,16)) for n in m[1].split())
    code='-'.join(f'{ord(c):x}' for c in value)
    source=root/(code+'.png')
    if not source.exists():source=root/(code.replace('-fe0f','')+'.png')
    if source.exists():entries.append((value,source,m[2],group,subgroup))
assert len(entries)>=3900,len(entries)
metadata={};side=32;cell=48;capacity=side*side
for page in range(math.ceil(len(entries)/capacity)):
    atlas=Image.new('RGBA',(side*cell,side*cell))
    for slot,(value,source,name,group,subgroup) in enumerate(entries[page*capacity:(page+1)*capacity]):
        x,y=slot%side*cell,slot//side*cell
        with Image.open(source) as image:atlas.paste(image.resize((cell,cell),Image.Resampling.LANCZOS),(x,y))
        metadata[value]={'page':page,'x':x,'y':side*cell-y-cell,'name':name,'category':group,'subgroup':subgroup}
    target=assets/f'emoji-atlas-{page}.png'
    temporary=target.with_suffix('.partial.png')
    atlas.save(temporary,compress_level=6)
    with Image.open(temporary) as verified:verified.verify()
    temporary.replace(target)
# FE0F is optional for many typed sequences. Aliases retain the canonical image.
for value,item in list(metadata.items()):
    alias=value.replace('\ufe0f','')
    if alias and alias!=value:metadata.setdefault(alias,dict(item,alias=True))
(assets/'emoji-atlas.json').write_text(json.dumps(metadata,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
(assets/'emoji.json').write_text(json.dumps([e[0] for e in entries],ensure_ascii=False),encoding='utf-8')
(assets/'licenses/Unicode-emoji-source.txt').write_text('Emoji 17.0 Unicode data: https://www.unicode.org/Public/emoji/17.0/emoji-test.txt\nUnicode data license: https://www.unicode.org/license.txt\nTwemoji graphics: https://github.com/jdecked/twemoji/tree/v17.0.3\nSee Twemoji-graphics-LICENSE.txt.\n')
print(len(entries),'canonical emoji;',len(metadata),'including typed aliases;',math.ceil(len(entries)/capacity),'atlas pages')
