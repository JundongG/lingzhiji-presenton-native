# SPDX-License-Identifier: Apache-2.0
"""Regression checks for the deliberately image-free, selectable native template."""
import json
from io import BytesIO
from pathlib import Path
import unittest
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from templates.v2.models.layouts import SlideLayouts, MergedComponents
from templates.v2.schema import get_template_schema
from services.chat.slide_ui_helpers import _validate_visual_insert_tree
from services.native_standard_pptx import export_standard_pptx
ROOT=Path(__file__).resolve().parents[4]
class NativeEditableTemplateTests(unittest.TestCase):
 def setUp(self):self.template=json.loads((ROOT/'templates/native_editable/template.json').read_text())
 def test_selectable_metadata_and_schema(self):
  self.assertEqual(self.template['id'],'native_editable');self.assertIn('Native Editable',self.template['name'])
  SlideLayouts.model_validate({'layouts':self.template['layouts']});MergedComponents.model_validate({'components':self.template['merged_components']})
  schema=get_template_schema({'layouts':self.template['layouts']});self.assertEqual(len(schema['layouts']),5)
  for slide in self.template['layouts']:_validate_visual_insert_tree(slide)
 def test_five_layouts_have_native_data_and_no_images(self):
  result=export_standard_pptx(self.template['layouts'],title='Synthetic template regression',theme=self.template['theme']);self.assertFalse(result.warnings)
  with ZipFile(BytesIO(result.pptx_bytes)) as z:
   slides=[n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
   self.assertEqual(len(slides),5);self.assertEqual(sum(len(ET.fromstring(z.read(n)).findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}tbl')) for n in slides),1)
   self.assertEqual(len([n for n in z.namelist() if n.startswith('ppt/charts/chart') and n.endswith('.xml')]),3)
   self.assertEqual(len([n for n in z.namelist() if n.startswith('ppt/embeddings/')]),3)
   self.assertFalse(any(n.startswith('ppt/media/') for n in z.namelist()))
 def test_series_names_and_placeholder_content_remain_meaningful(self):
  line=self.template['layouts'][3]['components'][1]['elements'][0]
  self.assertEqual([s['name'] for s in line['series']],['方案甲','方案乙'])
  self.assertNotIn('decorative_shape',json.dumps(line,ensure_ascii=False))
  texts=[]
  def walk(v):
   if isinstance(v,dict):
    if isinstance(v.get('text'),str):texts.append(v['text'])
    for child in v.values():walk(child)
   elif isinstance(v,list):
    for child in v:walk(child)
  walk(self.template['layouts']);self.assertFalse(any('原生可编辑' in t or '合成测试' in t for t in texts))
if __name__=='__main__':unittest.main()
