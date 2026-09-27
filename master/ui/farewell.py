"""Lightweight Vector closing screen; no compositor or media dependency."""
import math
from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient
from PySide6.QtWidgets import QWidget

class FarewellScreen(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.caption = 'Завершаем работу'
        self.clock = QElapsedTimer(); self.clock.start()
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.timer = QTimer(self); self.timer.setInterval(40)
        self.timer.timeout.connect(self.update); self.timer.start()
        self.show(); self.raise_()

    def set_caption(self, text):
        self.caption = text; self.update()

    def hideEvent(self, event):
        self.timer.stop(); super().hideEvent(event)

    def paintEvent(self, event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h=self.width(),self.height(); t=self.clock.elapsed()/1000
        background=QLinearGradient(0,0,w,h)
        background.setColorAt(0,QColor('#20231f'));background.setColorAt(1,QColor('#0b0f10'))
        p.fillRect(self.rect(),background)
        center_y=h*.43; radius=min(w*.24,h*.29)
        for scale,offset in ((1,0),(1.12,135)):
            r=radius*scale
            p.setPen(QPen(QColor(255,191,101,45),1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(w/2-r,center_y-r,2*r,2*r))
            p.setPen(QPen(QColor(255,191,101,145),2))
            p.drawArc(QRectF(w/2-r,center_y-r,2*r,2*r),int((offset-t*12)*16),38*16)
        font=QFont('Arial');font.setBold(True);font.setItalic(True)
        font.setPixelSize(max(30,min(72,int(w*.065))))
        p.setFont(font);p.setPen(QColor('#ffcb88'))
        p.drawText(QRectF(0,center_y-48,w,96),Qt.AlignmentFlag.AlignCenter,'FIT-LAB')
        font.setItalic(False);font.setBold(False);font.setPixelSize(max(16,min(24,int(w*.022))))
        p.setFont(font);p.setPen(QColor('#e6ded0'))
        p.drawText(QRectF(w*.1,h*.78,w*.8,40),Qt.AlignmentFlag.AlignCenter,self.caption)
        p.setPen(QPen(QColor(255,191,101,int(70+60*(1+math.sin(t*1.4))/2)),2))
        p.drawLine(int(w*.38),int(h*.88),int(w*.62),int(h*.88))
        p.end()
