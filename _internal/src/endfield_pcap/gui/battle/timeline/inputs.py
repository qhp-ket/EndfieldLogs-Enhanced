"""Paint independently interpreted input spans; no canonical snapshot mutation."""
from __future__ import annotations
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QColor,QBrush,QPen
from endfield_pcap.inputlog.interpret import tooltip

COLORS={'skill':'#3287ef','ultimate':'#ed9b32','combo':'#ad65e3','switch':'#699ca5','other':'#8492a4'}


def draw_inputs(view,y,scale,x_at):
    evidence=getattr(view,'input_evidence',{})
    actions=evidence.get('actions',[])
    raw=evidence.get('raw',[])
    view.input_markers=0
    global_actions=[]
    role_cells=[cell for cell in view._role_cells if cell[3]]
    for action in actions:
        if action['action'] not in {'skill','ultimate','combo'} and not evidence.get('settings',{}).get('show_other'): continue
        owner=action.get('character_key')
        if action['action']=='combo':
            if not role_cells: continue
            top=min(cell[0] for cell in role_cells)
            height=max(cell[0]+cell[1] for cell in role_cells)-top
        else:
            cell=next((c for c in view._role_cells if c[3]==owner),None) if owner else None
            if not cell:
                if view._character and owner and owner!=view._character: continue
                global_actions.append(action);continue
            top,height=cell[0],cell[1]
        paint_span(view,action,top,height,x_at)
    if global_actions or raw:
        height=44*scale
        view._labels.append((y,height,'输入证据','input',''))
        for action in global_actions: paint_span(view,action,y,height,x_at)
        # Continuous values are reduced only for pixels drawn. The file and indexed range stay intact.
        buckets={}
        for row in raw:
            key=(row['device'],row['code'],round(x_at(row['time_ms'])))
            buckets[key]=row
        for row in buckets.values():
            x=x_at(row['time_ms'])
            value=row.get('value')
            ratio=(max(-32768,min(32767,value))/32768) if type(value) in (int,float) else 0
            marker=view.scene().addEllipse(x-1,y+height/2-ratio*height*.35,2,2,QPen(QColor('#899ab3')),QBrush(QColor('#899ab3')))
            marker.setToolTip(f'{row["time_ms"]/1000:.3f}s · {row["device"]} · {row["code"]}\n{value}')
        y+=height
    return y


def paint_span(view,action,top,height,x_at):
    start,duration,width=view._time_extent
    left,right=x_at(max(start,action['start_ms'])),x_at(min(start+duration,action['end_ms']))
    if right<left: return
    color=QColor(COLORS.get(action['action'],COLORS['other']))
    fill=QColor(color);fill.setAlpha(36)
    pen=QPen(color,1.5)
    if action['action']=='combo' or action['interrupted']: pen.setStyle(Qt.PenStyle.DashLine)
    rect=view.scene().addRect(QRectF(left,top,max(1,right-left),height),QPen(Qt.PenStyle.NoPen),QBrush(fill))
    rect.setZValue(4);rect.setToolTip(action.get('tooltip') or tooltip(action))
    rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    line=view.scene().addLine(left,top,left,top+height,pen)
    line.setZValue(5);line.setToolTip(rect.toolTip())
    line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    if action['interrupted']:
        edge=view.scene().addLine(right,top,right,top+height,pen);edge.setZValue(5);edge.setToolTip(rect.toolTip())
        edge.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    view.input_markers+=1
