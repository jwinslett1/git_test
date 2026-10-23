import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
import numpy as np
import pytest,tifffile
import main,image_engine as engine

def sample(p):
    im=Image.new('RGBA',(100,90));im.paste((100,50,30,255),(20,20,80,70));im.save(p,dpi=(300,300))

def test_custom_canvas_and_trim_disabled(tmp_path):
    p=tmp_path/'a.png';sample(p)
    out=engine.prepare_image(p,trim=True,canvas_inches=1)
    assert out.size==(360,350);out.close()
    out=engine.prepare_image(p,trim=False,canvas_inches=2)
    assert out.size==(100,90);out.close()
    out=engine.prepare_image(p,trim=True,canvas_inches=0)
    assert out.size==(60,50);out.close()

def test_zero_contraction_is_exact_alpha():
    alpha=Image.fromarray(np.random.default_rng(4).integers(0,256,(30,30),dtype=np.uint8))
    np.testing.assert_array_equal(engine.make_spot_mask(alpha,0),np.asarray(alpha))

@pytest.mark.parametrize('value',[-1,float('nan'),float('inf')])
def test_invalid_canvas(value):
    with pytest.raises(ValueError):engine.add_half_inch_canvas(Image.new('RGBA',(5,5)),value)

def test_checkbox_selection_preview_and_defaults(tmp_path,monkeypatch):
    app=main.QApplication.instance() or main.QApplication([])
    paths=[tmp_path/'a.png',tmp_path/'b.png']
    for p in paths:sample(p)
    w=main.MainWindow();w.show_sources(tmp_path,paths);w.show()
    assert w.selected_sources()==tuple(paths)
    w.file_list.setCurrentItem(w.file_list.topLevelItem(1))
    assert w.selected_sources()==tuple(paths)
    deadline=time.monotonic()+10
    while w.preview.image_item is None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    assert w.preview.image_item is not None
    assert 'b.png' in w.preview_caption.text()
    w.preview.set_fit(False);assert not w.preview.fit_mode
    w.preview.set_fit(True);assert w.preview.fit_mode
    w.select_all.click();assert not w.selected_sources()
    messages=[];monkeypatch.setattr(main.QMessageBox,'information',lambda *args:messages.append(args))
    w.start_processing();assert w.thread is None;assert messages
    w.file_list.topLevelItem(0).setCheckState(0,main.Qt.CheckState.Checked)
    assert w.select_all.checkState()==main.Qt.CheckState.PartiallyChecked
    w.select_all.click();assert w.selected_sources()==tuple(paths)
    w.trim_edges.setCurrentIndex(1);assert not w.canvas_increase.isEnabled()
    assert w.canvas_increase.value()==.5
    assert w.contraction.currentData()==1
    assert w.alpha_threshold.count()==10
    result=dict(transparency='✓ Yes',transparency_tone='green',transparency_detail='',ghost='✓ Possible',ghost_tone='amber',ghost_detail='test',dpi='300')
    w.on_inspection_result(w.inspection_generation,0,result)
    assert w.file_list.topLevelItem(0).text(3)=='●'
    result['ghost']='— None found';w.on_inspection_result(w.inspection_generation,0,result)
    assert w.file_list.topLevelItem(0).text(3)==''
    w.close()

def test_worker_uses_new_settings_and_zero_mask(tmp_path):
    p=tmp_path/'a.png';sample(p)
    job=main.JobSettings(tmp_path,False,False,0,True,4,True,(p,),False,5)
    worker=main.Worker(job);result=[];worker.finished.connect(lambda ok,msg:result.append(ok));worker.run()
    assert result==[True]
    a=tifffile.imread(tmp_path/'TIFF FILES/a_resized.tif')
    assert a.shape==(90,100,5)
    np.testing.assert_array_equal(a[:,:,4],255-a[:,:,3])
