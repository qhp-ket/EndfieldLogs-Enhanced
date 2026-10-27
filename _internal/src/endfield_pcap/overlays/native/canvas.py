"""One QWidget per window, cached layouts and ordinary Python render modules."""
from PySide6.QtCore import Qt, QRectF, QSizeF, QPointF, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from endfield_pcap.overlays.templates import template_for, template_values
from . import MODULES
from .model import palette


class OverlayCanvas(QWidget):
    naturalSizeChanged = Signal(float,float,str)

    def __init__(self,entry,parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.modules=[]
        self.layout_revision=0
        self.paint_revision=0
        self._rects=[]
        self.scale=1.
        self.apply_entry(entry)

    def apply_entry(self,entry):
        template=template_for(entry)
        self.entry,self.template=entry,template
        if template.error:
            raise ValueError(template.error)
        types=[m['type'] for m in template.modules]
        if [type(m) for m in self.modules] != [MODULES[t] for t in types]:
            self.modules=[MODULES[t]() for t in types]
        values=template_values(entry,template)
        for module,declaration in zip(self.modules,template.modules):
            settings={**values,**declaration.get('settings',{})}
            settings.update({key:values[target] for key,target in declaration.get('setting_bindings',{}).items()})
            settings['_font_scale']=entry.font_scale
            module.apply_config(settings,template.theme)
        image=template.theme.get('image')
        self.background=QPixmap(str(template.path.parent/image)) if image else QPixmap()
        self.relayout()

    @property
    def bars(self):
        return len(self.modules)==1 and self.template.modules[0]['type']=='combo_skill' and self.modules[0].settings.get('display_style')=='bars'

    @property
    def uid_only(self):
        return len(self.modules)==1 and self.template.modules[0]['type']=='uid_mask'

    def receive(self,message):
        changed=False
        for module in self.modules:
            changed=module.receive(message) or changed
        if changed:
            self.relayout()
        return changed

    def set_connected(self,connected):
        for module in self.modules:
            module.connected=connected
        self.relayout()

    def relayout(self):
        theme=self.template.theme
        padding=theme.get('padding',0)
        gap=theme.get('spacing',8)
        horizontal=self.template.layout.get('direction')=='horizontal'
        layouts=[m.measure() for m in self.modules]
        width=sum(l.size.width() for l in layouts)+gap*max(0,len(layouts)-1) if horizontal else max(l.size.width() for l in layouts)
        height=max(l.size.height() for l in layouts) if horizontal else sum(l.size.height() for l in layouts)+gap*max(0,len(layouts)-1)
        self.natural_size=QSizeF(width+padding*2,height+padding*2)
        self.layout_revision+=1
        self._arrange()
        self.naturalSizeChanged.emit(self.natural_size.width(),self.natural_size.height(),'bars' if self.bars else 'circles')
        self.update()

    def _arrange(self):
        if not self.modules: return
        padding=self.template.theme.get('padding',0);gap=self.template.theme.get('spacing',8)
        horizontal=self.template.layout.get('direction')=='horizontal'
        self.scale=max(.01,min(self.width()/max(1.,self.natural_size.width()),self.height()/max(1.,self.natural_size.height())))
        if self.bars: self.scale=max(.01,self.height()/self.natural_size.height())
        x=y=padding;self._rects=[]
        for module in self.modules:
            layout=module.measure(max(1.,self.width()/self.scale-padding*2) if self.bars else None)
            self._rects.append((QRectF(x,y,layout.size.width(),layout.size.height()),layout))
            if horizontal: x+=layout.size.width()+gap
            else: y+=layout.size.height()+gap

    def resizeEvent(self,event):
        self._arrange();self.update()
        super().resizeEvent(event)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.scale,self.scale)
        if self.uid_only:
            self.modules[0].paint(painter,QRectF(0,0,self.width()/self.scale,self.height()/self.scale),self._rects[0][1],self.devicePixelRatioF())
        else:
            outer=QRectF(0,0,self.width()/self.scale,self.height()/self.scale)
            colors=palette(self.modules[0].settings,self.template.theme)
            painter.setBrush(colors['background'])
            painter.setPen(QPen(colors['border'],self.template.theme.get('border_width',.7)))
            radius=self.template.theme.get('radius',0 if self.modules[0].settings.get('theme') == 'endfield' else 8)
            painter.drawRoundedRect(outer.adjusted(.5,.5,-.5,-.5),radius,radius)
            if not self.background.isNull(): painter.drawPixmap(outer,self.background,self.background.rect())
            for module,(rect,layout) in zip(self.modules,self._rects):
                painter.save();painter.translate(rect.topLeft());painter.setClipRect(QRectF(QPointF(),rect.size()))
                module.paint(painter,QRectF(QPointF(),rect.size()),layout,self.devicePixelRatioF()*self.scale)
                painter.restore()
        self.paint_revision=self.layout_revision

    def tooltip(self,point):
        point=QPointF(point)/self.scale
        return '\n'.join(layout.tooltip(point-rect.topLeft()) for rect,layout in self._rects if rect.contains(point))
