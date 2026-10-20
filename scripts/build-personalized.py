"""Dispatch an owner-authorized CI build with PUBLIC connection settings only."""
import argparse
import base64
import json
import re
import subprocess
import time
import uuid
import sys
from pathlib import Path


def public_profile(path):
    raw = Path(path).read_bytes()
    if len(raw)>8192: raise ValueError('Profile too large')
    v = json.loads(raw)
    if set(v)!={'v','locked','relay'} or v['v']!=1 or v['locked'] is not True:
        raise ValueError('Invalid public deployment profile')
    r=v['relay']
    if set(r)!={'host','port','pin','transport','tls_pin'} or r['transport']!='tls-noise':
        raise ValueError('Only dedicated TLS profiles are supported')
    if not isinstance(r['host'],str) or not re.fullmatch(r'[A-Za-z0-9.:-]{1,253}',r['host']) or type(r['port']) is not int or not 1<=r['port']<=65535:
        raise ValueError('Invalid server address')
    if len(base64.b64decode(r['pin'],validate=True))!=32 or not re.fullmatch('[0-9a-f]{64}',r['tls_pin']):
        raise ValueError('Invalid public pins')
    return base64.b64encode(json.dumps(v,separators=(',',':')).encode()).decode()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--profile',required=True,type=Path)
    p.add_argument('--repo',default='Realjustawall/MehrChat')
    p.add_argument('--ref',required=True,help='Build branch or released tag containing this workflow')
    p.add_argument('--wait',action='store_true')
    p.add_argument('--sign',action='store_true',help='Sign Android release locally after downloading')
    p.add_argument('--output',type=Path,default=Path('dedicated-clients'))
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',a.repo): raise ValueError('Invalid repository')
    build_id='deployment-'+uuid.uuid4().hex[:16]
    payload={'ref':a.ref,'inputs':{'profile_b64':public_profile(a.profile),'build_id':build_id}}
    subprocess.run(['gh','api','--method','POST','repos/'+a.repo+'/actions/workflows/build.yml/dispatches','--input','-'],input=json.dumps(payload),text=True,check=True)
    print('Build requested:',build_id)
    print('Windows builds on Windows; Android builds on Linux. Admin/user private keys never enter the workflow.')
    if not a.wait:return
    deadline=time.monotonic()+7200
    while time.monotonic()<deadline:
        runs=json.loads(subprocess.check_output(['gh','api','repos/'+a.repo+'/actions/workflows/build.yml/runs?event=workflow_dispatch&per_page=30'],text=True))['workflow_runs']
        match=next((r for r in runs if r['display_title']=='MehrChat '+build_id),None)
        if match:
            if match['status']=='completed':
                if match['conclusion']!='success':raise RuntimeError('Build failed: '+match['html_url'])
                a.output.mkdir(parents=True,exist_ok=True)
                subprocess.run(['gh','run','download',str(match['id']),'--repo',a.repo,'--dir',str(a.output)],check=True)
                print('Dedicated client artifacts downloaded to',a.output)
                if a.sign:
                    subprocess.run([sys.executable,str(Path(__file__).with_name('sign-personalized.py')),str(a.output)],check=True)
                else:
                    print('Release APKs still require the deployment owner signing key; test APKs are marked debug.')
                return
            print('Build',match['status'],match['html_url'],flush=True)
        time.sleep(30)
    raise TimeoutError('Build still pending; see repository Actions')


if __name__=='__main__':main()
