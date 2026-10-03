#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run an authenticated Presenton UI with isolated state and loopback listeners.

Install/apply the source add-on and dependencies separately. This launcher never
creates credentials or reads provider configuration. It does not open a public
port or create a tunnel. Use only a platform-supported PRIVATE port-forward URL.
"""
from pathlib import Path
import argparse,os,shutil,signal,subprocess,time
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
PIN='e158a014cc1e29da0a27fe539db08dcbcea5c69d'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--presenton',type=Path,required=True);p.add_argument('--state-dir',type=Path,required=True);p.add_argument('--python',type=Path,required=True);p.add_argument('--node',default='node');p.add_argument('--port',type=int,default=3000);p.add_argument('--api-port',type=int,default=8000);p.add_argument('--private-origin',help='Verified HTTPS origin for a platform-private port forward; no path/query/token');a=p.parse_args()
 repo=a.presenton.resolve(strict=True);state=a.state_dir.resolve();python=a.python.expanduser().absolute();node=shutil.which(a.node)
 if not python.is_file():raise SystemExit('Python executable does not exist.')
 # Keep the venv executable path: resolving its symlink would bypass pyvenv.cfg.
 if node is None:raise SystemExit('Node is not installed; no changes made.')
 if state==repo or state.is_relative_to(repo) or state==ROOT or state.is_relative_to(ROOT):raise SystemExit('Keep runtime state outside both source repositories.')
 if not (1024<=a.port<=65535 and 1024<=a.api_port<=65535 and a.port!=a.api_port):raise SystemExit('Choose two distinct unprivileged ports.')
 pin=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
 if pin!=PIN:raise SystemExit('Unsupported upstream commit.')
 if not (repo/'servers/fastapi/services/native_standard_pptx.py').is_file():raise SystemExit('Apply the native add-on first.')
 origin=f'http://127.0.0.1:{a.port}'
 if a.private_origin:
  u=urlparse(a.private_origin)
  if u.scheme!='https' or not u.netloc or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):raise SystemExit('private-origin must be a clean, verified HTTPS origin.')
  origin=a.private_origin.rstrip('/')
 os.umask(0o077)  # New runtime state is private to the current OS account.
 for name in ['home','data','tmp','cache','logs']:(state/name).mkdir(parents=True,exist_ok=True)
 env={'PATH':str(python.parent)+os.pathsep+str(Path(node).parent)+os.pathsep+'/usr/bin:/bin','HOME':str(state/'home'),'APP_DATA_DIRECTORY':str(state/'data'),'TEMP_DIRECTORY':str(state/'tmp'),'USER_CONFIG_PATH':str(state/'data/userConfig.json'),'XDG_CACHE_HOME':str(state/'cache'),'CAN_CHANGE_KEYS':'true','MEM0_ENABLED':'false','DISABLE_IMAGE_GENERATION':'true','DISABLE_ANONYMOUS_TRACKING':'true','NEXT_TELEMETRY_DISABLED':'1','PRESENTON_COMMUNITY_ENABLED':'false','PRESENTON_APP_ROOT':str(repo),'NEXT_PUBLIC_URL':origin,'PRESENTON_PUBLIC_URL':origin,'FAST_API_INTERNAL_URL':f'http://127.0.0.1:{a.api_port}','APP_VERSION':'0.9.11-beta','PYTHONUNBUFFERED':'1'}
 children=[];logs=[]
 def stop(_sig=None,_frame=None):
  for child in children:
   if child.poll() is None:child.terminate()
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 try:
  for name,cwd,cmd in [('backend',repo/'servers/fastapi',[str(python),'server.py','--port',str(a.api_port),'--reload','false']),('frontend',repo/'servers/nextjs',[node,'node_modules/next/dist/bin/next','dev','--webpack','-H','127.0.0.1','-p',str(a.port)])]:
   log=open(state/'logs'/f'{name}.log','a');logs.append(log);children.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT))
  print(f'UI process launched on loopback port {a.port}; API on {a.api_port}. Authentication remains enabled.',flush=True)
  print('This does not confirm that the private forwarding URL is reachable. Verify its access controls before entering credentials.',flush=True)
  while all(child.poll() is None for child in children):time.sleep(1)
 finally:
  stop()
  for child in children:
   try:child.wait(timeout=10)
   except subprocess.TimeoutExpired:child.kill();child.wait()
  for log in logs:log.close()
if __name__=='__main__':main()
