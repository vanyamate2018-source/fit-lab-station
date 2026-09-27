import os,subprocess,sys

def test_drag_scroll_does_not_select():
    code='''from PySide6.QtWidgets import QApplication,QListWidget,QDialog
from PySide6.QtCore import QTimer,Qt,QPoint
from PySide6.QtTest import QTest
from master.ui.choices import ChoicePicker
app=QApplication([]);p=ChoicePicker('Частота');p.addItems([str(i) for i in range(100)]);p.show()
errors=[]
def check():
 d=p.findChild(QDialog)
 try:
  v=d.findChild(QListWidget);vp=v.viewport();start=QPoint(vp.width()//2,vp.height()-50)
  QTest.mousePress(vp,Qt.MouseButton.LeftButton,pos=start)
  for n in range(1,11):QTest.mouseMove(vp,start-QPoint(0,n*20),delay=20)
  QTest.mouseRelease(vp,Qt.MouseButton.LeftButton,pos=start-QPoint(0,200))
  assert d.isVisible(),'Drag closed picker'
  assert p.currentIndex()==0,'Drag selected item'
  assert v.verticalScrollBar().value()>0,'No scroll'
  item=v.itemAt(QPoint(30,30));expected=v.row(item)
  QTest.mouseClick(vp,Qt.MouseButton.LeftButton,pos=QPoint(30,30))
  assert p.currentIndex()==expected,'Tap did not select'
  assert not d.isVisible(),'Tap did not close'
 except Exception as e:errors.append(str(e))
 finally:d.reject()
QTimer.singleShot(100,check);p.choose()
assert not errors,errors
'''
    r=subprocess.run([sys.executable,'-c',code],env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stderr
