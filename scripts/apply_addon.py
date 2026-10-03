#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Apply the reviewed source-only overlay to one pinned Presenton checkout.

Default is a dry run. No dependency installation, network, credentials or services.
"""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PIN='e158a014cc1e29da0a27fe539db08dcbcea5c69d'
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--presenton',required=True,type=Path);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 dest=args.presenton.resolve(strict=True)
 def git(*parts):return subprocess.run(['git','-C',str(dest),*parts],capture_output=True,text=True,check=True).stdout.strip()
 if Path(git('rev-parse','--show-toplevel')).resolve()!=dest:raise SystemExit('Use the upstream checkout root; no files changed.')
 if git('rev-parse','HEAD')!=PIN:raise SystemExit('Unsupported upstream commit; no files changed.')
 patch=ROOT/'patches/native-export.patch'
 if not patch.exists():raise SystemExit('Integration patch is missing; no files changed.')
 manifest=json.loads((ROOT/'release-manifest.json').read_text())
 if patch.is_symlink() or hashlib.sha256(patch.read_bytes()).hexdigest()!=manifest['patch_sha256']:raise SystemExit('Patch hash mismatch; no files changed.')
 overlay=(ROOT/'overlay').resolve(strict=True)
 items=[]
 for item in manifest['overlay']:
  rel=Path(item['path'])
  if rel.is_absolute() or '..' in rel.parts:raise SystemExit('Invalid overlay path')
  source=ROOT/'overlay'/rel;target=dest/rel
  if source.is_symlink() or not source.is_file():raise SystemExit(f'Invalid source: {rel}')
  if any(parent.is_symlink() for parent in source.parents if parent!=ROOT and ROOT in parent.parents):raise SystemExit(f'Symlink source parent: {rel}')
  if not source.resolve(strict=True).is_relative_to(overlay):raise SystemExit(f'Source outside overlay: {rel}')
  if hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:raise SystemExit(f'Hash mismatch: {rel}')
  if target.exists() or target.is_symlink():raise SystemExit(f'Target already exists: {rel}; no files changed.')
  if any(parent.is_symlink() for parent in target.parents if parent!=dest and dest in parent.parents):raise SystemExit(f'Symlink parent: {rel}')
  items.append((source,target))
 git('apply','--check',str(patch))
 if not args.apply:
  print(f'Dry run passed: {len(items)} new files and the integration patch. Re-run with --apply to write.');return
 git('apply',str(patch))
 for source,target in items:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 print('Source overlay applied. No dependencies, credentials or services were configured.')
if __name__=='__main__':main()
