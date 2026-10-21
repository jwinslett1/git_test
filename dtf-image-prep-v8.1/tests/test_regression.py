import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import time
from pathlib import Path
import numpy as np
import pytest
from PIL import Image, ImageFilter
import tifffile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_engine as engine
import main

@pytest.mark.parametrize('shrink', [1, 2, 3])
@pytest.mark.parametrize('size', [(1,1), (3,7), (70,60)])
def test_mask_matches_original(shrink, size):
    values = np.random.default_rng(34).integers(0,256,(size[1],size[0]), dtype=np.uint8)
    alpha = Image.fromarray(values)
    expected = alpha.filter(ImageFilter.MinFilter(2*shrink+1)).filter(ImageFilter.GaussianBlur(.35))
    np.testing.assert_array_equal(engine.make_spot_mask(alpha, shrink), expected)

def source(path):
    image = Image.new('RGBA', (100,100))
    image.paste((70,120,180,255), (20,20,80,80))
    image.save(path, dpi=(300,300))

def settings(path, save=False, overwrite=False):
    return main.JobSettings(path, overwrite, save, 2, True, 4, True)

def test_canvas_before_spot_and_tiff(tmp_path):
    path = tmp_path/'art.png'; source(path)
    prepared = engine.prepare_image(path)
    assert prepared.size == (210,210)  # 60 px artwork + 150 px canvas
    assert prepared.getchannel('A').getbbox() == (75,75,135,135)
    out=tmp_path/'art.tif'
    engine.export_tiff_image_with_w1(prepared,out,2)
    with tifffile.TiffFile(out) as tif:
        page=tif.pages[0]; pixels=page.asarray()
        assert tuple(map(int,page.extrasamples)) == (2,0)
        assert page.tags[34377].value == engine._photoshop_resources()
    np.testing.assert_array_equal(pixels[:,:,:4],np.asarray(prepared))
    expected=255-np.asarray(engine.make_spot_mask(prepared.getchannel('A'),2))
    np.testing.assert_array_equal(pixels[:,:,4],expected)
    assert engine.verify_tiff_structure(out)[0]
    prepared.close()

def test_tiff_only_does_not_write_png(tmp_path,monkeypatch):
    source(tmp_path/'ART.PNG')
    def forbidden(*args,**kwargs): raise AssertionError('PNG encoding invoked')
    monkeypatch.setattr(main,'save_prepared_png',forbidden)
    result=[]; worker=main.Worker(settings(tmp_path))
    worker.finished.connect(lambda ok,msg:result.append(ok)); worker.run()
    assert result == [True]
    assert len(list((tmp_path/'TIFF FILES').glob('*.tif'))) == 1
    assert not (tmp_path/'RESIZED').exists()

def test_failure_keeps_original_and_cleans_staging(tmp_path,monkeypatch):
    path=tmp_path/'art.png';source(path);before=path.read_bytes()
    def fail(*args): raise RuntimeError('simulated TIFF failure')
    monkeypatch.setattr(main,'export_tiff_image_with_w1',fail)
    result=[]; worker=main.Worker(settings(tmp_path,True,True))
    worker.finished.connect(lambda ok,msg:result.append(ok)); worker.run()
    assert result == [False]
    assert path.read_bytes() == before
    assert not list(tmp_path.rglob('*.dtfprep-*'))

def test_cancel_keeps_original(tmp_path,monkeypatch):
    path=tmp_path/'art.png';source(path);before=path.read_bytes()
    worker=main.Worker(settings(tmp_path,True,True))
    original=main.save_prepared_png
    def save_then_stop(*args): original(*args);worker.request_stop()
    monkeypatch.setattr(main,'save_prepared_png',save_then_stop)
    worker.run()
    assert path.read_bytes() == before
    assert not list(tmp_path.rglob('*.dtfprep-*'))
    assert not list(tmp_path.rglob('*.tif'))

def test_sixty_image_batch(tmp_path):
    for i in range(60): source(tmp_path/f'art{i}.png')
    result=[];worker=main.Worker(settings(tmp_path))
    worker.finished.connect(lambda ok,msg:result.append(ok));worker.run()
    assert result == [True]
    assert len(list((tmp_path/'TIFF FILES').glob('*.tif'))) == 60

def test_gui_two_batches(tmp_path,monkeypatch):
    app=main.QApplication.instance() or main.QApplication([])
    monkeypatch.setattr(main.QMessageBox,'information',lambda *args:None)
    source(tmp_path/'art.png')
    window=main.MainWindow();window.source_dir=tmp_path
    window.save_png.setChecked(False);window.make_tiff.setChecked(True)
    for _ in range(2):
        window.start_processing()
        deadline=time.monotonic()+10
        while window.thread is not None and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        assert window.thread is None
        assert window.worker is None
        assert window.run_btn.isEnabled()
    window.close()

def test_existing_output_folders_and_selected_file(tmp_path):
    for name in ('first.png','second.png'): source(tmp_path/name)
    resized=tmp_path/'resized ';resized.mkdir()
    tiffs=tmp_path/'tiff files';tiffs.mkdir()
    job=settings(tmp_path,True)
    job.selected_files=(tmp_path/'second.png',)
    result=[];worker=main.Worker(job)
    worker.finished.connect(lambda ok,msg:result.append(ok));worker.run()
    assert result==[True]
    assert (resized/'second_resized.png').exists()
    assert (tiffs/'second_resized.tif').exists()
    assert not (tmp_path/'RESIZED').exists()
    assert not (tmp_path/'TIFF FILES').exists()
    assert not (resized/'first_resized.png').exists()

def test_modern_metadata_matches_photocraft_import():
    import struct
    raw=engine._photoshop_resources();resources={};pos=0
    while pos<len(raw):
        assert raw[pos:pos+4]==b'8BIM'
        rid=int.from_bytes(raw[pos+4:pos+6],'big');pos+=6
        n=raw[pos];pos+=1+n+(1+n)%2
        length=int.from_bytes(raw[pos:pos+4],'big');pos+=4
        resources[rid]=raw[pos:pos+length];pos+=length+length%2
    data=resources[1045];names=[]
    while data:
        n=int.from_bytes(data[:4],'big');names.append(data[4:4+2*n].decode('utf-16-be').rstrip('\0'));data=data[4+2*n:]
    assert names==['Transparency','w1']
    modern=resources[1077]
    assert modern[:4]==struct.pack('>I',1)
    assert len(modern)==30
    # PhotoCraft skips the transparency entry when two Unicode names describe
    # one extra spot plane plus merged transparency.
    spot=modern[4+13:4+26]
    assert struct.unpack('>H4HHB',spot)==(0,65535,65535,65535,0,100,2)

def test_gui_selection_and_centering(tmp_path):
    app=main.QApplication.instance() or main.QApplication([])
    paths=[tmp_path/'first.png',tmp_path/'second.png']
    for p in paths:source(p)
    window=main.MainWindow();window.show_sources(tmp_path,paths)
    assert window.selected_sources()==tuple(paths)
    window.file_list.topLevelItem(1).setSelected(True)
    assert window.selected_sources()==(paths[1],)
    assert window.alpha_threshold.alignment()==main.Qt.AlignmentFlag.AlignCenter
    assert Path(window.browse_start())==tmp_path
    window.close()
