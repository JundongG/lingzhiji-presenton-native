#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scan this add-on and all reachable Git blobs without printing matched values.

This is a focused release guard, not a replacement for independent review.
It intentionally never reads outside the repository or follows symlinks.
"""
from pathlib import Path
import json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
 'private_key':re.compile(rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----'),
 'provider_key':re.compile(rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b'),
 'github_token':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
 'google_api_key':re.compile(rb'\bAIza[A-Za-z0-9_-]{30,}\b'),
 'aws_access_key':re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
}
BLOCKED_DIRS={'node_modules','.venv','venv','app_data','data','logs','cache','.next-build','__pycache__'}
BLOCKED_SUFFIX={'.key','.pem','.p12','.pfx','.sqlite','.sqlite3','.db'}
def forbidden(rel):
 return bool(set(part.casefold() for part in rel.parts)&BLOCKED_DIRS or rel.suffix.lower() in BLOCKED_SUFFIX or rel.name.casefold()=='userconfig.json' or (rel.name.casefold().startswith('.env') and rel.name.casefold()!='.env.example'))
findings=[];count=0
for file in ROOT.rglob('*'):
 rel=file.relative_to(ROOT)
 if '.git' in rel.parts:continue
 if file.is_symlink():findings.append({'path':str(rel),'kind':'symlink'});continue
 if not file.is_file():continue
 if forbidden(rel):
  findings.append({'path':str(rel),'kind':'forbidden_release_file'});continue
 if file.stat().st_size>10_000_000:findings.append({'path':str(rel),'kind':'oversize_review_required'});continue
 payload=file.read_bytes();count+=1
 for kind,pattern in PATTERNS.items():
  if pattern.search(payload):findings.append({'path':str(rel),'kind':kind})
history_count=0
# Enumerate every reachable tree path, rather than rev-list's single path per
# deduplicated blob, so a blob once stored under .env cannot hide under a rename.
probe=subprocess.run(['git','rev-parse','--show-toplevel'],cwd=ROOT,text=True,capture_output=True)
if probe.returncode==0 and Path(probe.stdout.strip()).resolve()==ROOT:
 commits=subprocess.run(['git','rev-list','--all'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()
 blobs={}
 for commit in commits:
  listing=subprocess.run(['git','ls-tree','-rz','--full-tree',commit],cwd=ROOT,capture_output=True,check=True).stdout
  for entry in listing.split(b'\0'):
   if not entry:continue
   metadata,name=entry.split(b'\t',1);mode,kind,oid=metadata.decode().split()
   path=name.decode('utf-8','surrogateescape')
   if kind!='blob':continue
   blobs.setdefault(oid,set()).add(path)
 for oid,paths in blobs.items():
  blocked=[path for path in paths if forbidden(Path(path))]
  if blocked:
   for path in sorted(blocked):findings.append({'path':path,'object':oid,'kind':'forbidden_history_file'})
   continue
  path=sorted(paths)[0]
  size=int(subprocess.run(['git','cat-file','-s',oid],cwd=ROOT,text=True,capture_output=True,check=True).stdout)
  if size>10_000_000:
   findings.append({'path':path,'object':oid,'kind':'oversize_history_review_required'});continue
  payload=subprocess.run(['git','cat-file','blob',oid],cwd=ROOT,capture_output=True,check=True).stdout;history_count+=1
  for kind,pattern in PATTERNS.items():
   if pattern.search(payload):findings.append({'path':path,'object':oid,'kind':kind})
report={'files_scanned':count,'reachable_history_blobs_scanned':history_count,'match_values_printed':False,'findings':findings}
print(json.dumps(report,ensure_ascii=False,indent=2))
sys.exit(bool(findings))
