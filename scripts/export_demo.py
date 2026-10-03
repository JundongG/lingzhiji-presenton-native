#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate synthetic native PPTX examples offline. No account or model calls."""
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/'overlay/servers/fastapi'
sys.path.insert(0,str(BACKEND));sys.path.insert(0,str(BACKEND/'tests/unit'))
from services.native_standard_pptx import export_standard_pptx
from test_native_standard_pptx import fixture,edited_native_roundtrip

def verify(blob):
 with ZipFile(BytesIO(blob)) as archive:
  names=archive.namelist();slides=[n for n in names if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
  result={'slides':len(slides),'native_tables':sum(len(ET.fromstring(archive.read(n)).findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}tbl')) for n in slides),'native_charts':sum(n.startswith('ppt/charts/chart') and n.endswith('.xml') for n in names),'workbooks':sum(n.startswith('ppt/embeddings/') and n.endswith('.xlsx') for n in names),'raster_assets':sum(n.startswith('ppt/media/') for n in names)}
  if result!={'slides':5,'native_tables':1,'native_charts':3,'workbooks':3,'raster_assets':0}:raise RuntimeError('Unexpected demo structure')
  return result

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',required=True,type=Path);args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
 entries=[];revised=None
 for flag,name in [(False,'01-synthetic-original.pptx'),(True,'02-synthetic-revised.pptx')]:
  data=fixture(revised=flag);result=export_standard_pptx(data['slides'],title=data['title'])
  if result.warnings:raise RuntimeError('Unexpected export warning')
  row=verify(result.pptx_bytes);row['file']=name;entries.append(row);(args.output_dir/name).write_bytes(result.pptx_bytes)
  if flag:revised=result.pptx_bytes
 final=edited_native_roundtrip(revised);name='03-synthetic-native-api-edit-roundtrip.pptx';row=verify(final);row['file']=name;entries.append(row);(args.output_dir/name).write_bytes(final)
 report={'synthetic_data_only':True,'account_or_model_used':False,'powerpoint_ui_tested':False,'files':entries};(args.output_dir/'structure-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
