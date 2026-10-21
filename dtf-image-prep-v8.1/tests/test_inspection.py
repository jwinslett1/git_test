import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
import pytest
from png_inspection import inspect_png
import main

@pytest.mark.parametrize('mode', ['RGB','RGBA','P'])
def test_opaque_png_is_red(tmp_path,mode):
    p=tmp_path/'opaque.png';Image.new(mode,(60,60),(0,0,0,255) if mode=='RGBA' else 0).save(p)
    r=inspect_png(p)
    assert r['transparency']=='✕ No'
    assert r['transparency_tone']=='red'
    assert r['dpi']=='Unknown'
    assert r['ghost']=='— None found'

def test_palette_transparency_and_dpi(tmp_path):
    im=Image.new('P',(60,60),0);im.paste(1,(10,10,50,50));im.info['transparency']=0
    p=tmp_path/'palette.png';im.save(p,transparency=0,dpi=(300,300))
    r=inspect_png(p);assert r['transparency']=='✓ Yes';assert r['dpi']=='300'

def test_ghosts_vs_soft_edges(tmp_path):
    a=np.zeros((100,100,4),np.uint8)
    a[31:69,31:69,3]=255;a[30:70,30:70,3]=np.maximum(a[30:70,30:70,3],10)
    p=tmp_path/'soft.png';Image.fromarray(a).save(p)
    assert inspect_png(p)['ghost']=='— None found'
    a[5:8,5:8,3]=3;Image.fromarray(a).save(p)
    r=inspect_png(p);assert r['ghost']=='✓ Possible';assert '9 faint pixels' in r['ghost_detail']

def test_partial_empty_and_faint(tmp_path):
    p=tmp_path/'test.png'
    Image.new('RGBA',(20,20),(0,0,0,128)).save(p)
    assert inspect_png(p)['transparency']=='Partial'
    Image.new('RGBA',(20,20)).save(p)
    assert inspect_png(p)['transparency']=='Empty'
    Image.new('RGBA',(20,20),(0,0,0,5)).save(p)
    assert inspect_png(p)['ghost']=='Review'

def test_distinct_xy_dpi(tmp_path):
    p=tmp_path/'dpi.png';Image.new('RGB',(5,5)).save(p,dpi=(300,600))
    assert inspect_png(p)['dpi']=='300 × 600'

def wait_for(app,predicate):
    deadline=time.monotonic()+10
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    assert predicate()

def test_async_table_errors_and_stale_results(tmp_path):
    app=main.QApplication.instance() or main.QApplication([])
    p=tmp_path/'good.png';Image.new('RGB',(20,20)).save(p,dpi=(300,300))
    bad=tmp_path/'broken.png';bad.write_bytes(b'not a PNG')
    w=main.MainWindow();w.show_sources(tmp_path,[p,bad])
    wait_for(app,lambda:w.file_list.topLevelItem(1).text(1)=='Error')
    assert w.file_list.topLevelItem(0).text(1)=='✕ No'
    assert w.file_list.topLevelItem(0).text(3)=='300'
    w.file_list.topLevelItem(0).setSelected(True)
    assert w.selected_sources()==(p,)
    previous=w.inspection_generation
    w.show_sources(tmp_path,[p])
    w.on_inspection_result(previous,0,{'error':'stale result'})
    assert w.file_list.topLevelItem(0).text(1)!='Error'
    wait_for(app,lambda:w.file_list.topLevelItem(0).text(1)=='✕ No')
    w.close()
