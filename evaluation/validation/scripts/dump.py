import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from _paths import EVAL, WORK, TOOL, VAL, RATER  # noqa: E402
import json, re, subprocess, sys
REPOS={'dk':f'{WORK}/dronekit-python','pp':f'{WORK}/pandapower'}
rows=[]
for p in ('dk','pp'):
    raw=json.load(open(f'{VAL}/{p}_raw.json'))
    for ci,c in enumerate(raw):
        for ii,it in enumerate(c['items']):
            m=re.search(r" in (\S+)$",it['message']) or re.search(r"'([^']+\.py)'",it['message']) or re.search(r": (\S+\.py)",it['message'])
            path=m.group(1) if m else None
            text=''
            if path and it['line']:
                src=subprocess.run(['git','-C',REPOS[p],'show',f"{c['sha']}:{path}"],capture_output=True,text=True).stdout.splitlines()
                if it['line']<=len(src): text=src[it['line']-1].strip()
            rows.append({'id':f'{p}3-{ci:02d}-{ii:03d}','project':p,'sha':c['sha'],'commit_idx':ci,'file':path,**it,'code':text})
json.dump(rows,open(f'{VAL}/items.json','w'),indent=1)
for r in rows:
    if r['category'] in sys.argv[1:]:
        print(r['id'], r['sha'][:8], r['message'], 'L', r['line'], '|', r['code'][:110], '|', r['detail'].replace('\n',' / ')[:200])
