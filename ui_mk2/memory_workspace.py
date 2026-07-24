"""Interactive graph containing only real, active JARVIS memory records."""
from __future__ import annotations

import json

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView

from memory.graph_index import build_memory_graph
from ui_mk2.web_workspaces import _document


_SCRIPT = r"""
const canvas=document.getElementById('scene'),ctx=canvas.getContext('2d');let W=0,H=0,dpr=1;
let graph={nodes:[],edges:[],stats:{}},nodes=[],scale=1,ox=0,oy=0,drag=null,pan=false,mx=0,my=0,startX=0,startY=0,query='',selected=null,hover=null,showNames=false;
const colors={category:'#54e5ff',context:'#70ffbd',memory:'#ffd36a'};
function resize(){dpr=Math.min(devicePixelRatio||1,2);W=innerWidth;H=innerHeight;canvas.width=W*dpr;canvas.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0)}
function lookup(){return new Map(nodes.map(n=>[n.id,n]))}
function neighbors(id){const out=new Set([id]);for(const e of graph.edges){if(e.source===id)out.add(e.target);if(e.target===id)out.add(e.source)}return out}
function setGraph(g){graph=g;const hubs=g.nodes.filter(n=>n.kind!=='memory'),span=Math.min(W,H)*.30,positions=new Map();hubs.forEach((v,i)=>{const a=(i/Math.max(1,hubs.length))*Math.PI*2-Math.PI/2,rad=hubs.length===1?0:span;positions.set(v.id,{x:Math.cos(a)*rad,y:Math.sin(a)*rad})});const firstHub=new Map();for(const e of g.edges)if(e.kind==='membership')firstHub.set(e.target,e.source);nodes=g.nodes.map((v,i)=>{let p=positions.get(v.id);if(!p){const hub=positions.get(firstHub.get(v.id))||{x:0,y:0},a=i*2.399963;p={x:hub.x+Math.cos(a)*(58+(i%5)*14),y:hub.y+Math.sin(a)*(58+(i%5)*14)}}return({...v,...p,vx:0,vy:0,r:v.kind==='memory'?5.2:v.kind==='context'?13:16})});selected=null;document.getElementById('stats').textContent=`${g.stats.memories||0} REAL MEMORIES  /  ${g.stats.categories||0} CATEGORIES  /  ${g.stats.contexts||0} CONTEXTS`;}
function active(n){return !selected||neighbors(selected).has(n.id)}
function matches(n){return !query||(`${n.label} ${n.group||''} ${n.value||''}`).toLowerCase().includes(query)}
function sim(){if(!nodes.length)return;const map=lookup();for(let i=0;i<nodes.length;i++){const a=nodes[i];a.vx+=-a.x*.00008;a.vy+=-a.y*.00008;for(let j=i+1;j<nodes.length;j++){const b=nodes[j],dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy+140,f=(a.kind==='memory'&&b.kind==='memory'?48:82)/d2;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f}}for(const e of graph.edges){const a=map.get(e.source),b=map.get(e.target);if(!a||!b)continue;const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,w=e.kind==='explicit_relation'?115:82,f=(d-w)*.00007;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f}const bound=Math.min(W,H)*.45/scale;for(const n of nodes)if(n!==drag){n.vx=Math.max(-1.4,Math.min(1.4,n.vx*.9));n.vy=Math.max(-1.4,Math.min(1.4,n.vy*.9));n.x+=n.vx;n.y+=n.vy;const r=Math.hypot(n.x,n.y);if(r>bound){n.x*=bound/r;n.y*=bound/r}}}
function world(x,y){return{x:(x-W/2-ox)/scale,y:(y-H/2-oy)/scale}}
function hit(x,y){const p=world(x,y);return [...nodes].reverse().find(n=>Math.hypot(n.x-p.x,n.y-p.y)<Math.max(11,n.r+4)/scale)}
function nucleus(n,c){ctx.strokeStyle=c;ctx.fillStyle='rgba(2,15,22,.9)';ctx.lineWidth=1.6/scale;ctx.shadowColor=c;ctx.shadowBlur=14;if(n.kind==='category'){ctx.beginPath();for(let i=0;i<6;i++){const a=Math.PI/3*i-Math.PI/2,x=n.x+Math.cos(a)*n.r,y=n.y+Math.sin(a)*n.r;i?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.closePath();ctx.fill();ctx.stroke();ctx.beginPath();ctx.arc(n.x,n.y,n.r*.45,0,7);ctx.stroke()}else{ctx.save();ctx.translate(n.x,n.y);ctx.rotate(Math.PI/4);ctx.strokeRect(-n.r*.68,-n.r*.68,n.r*1.36,n.r*1.36);ctx.restore();ctx.beginPath();ctx.arc(n.x,n.y,3,0,7);ctx.fillStyle=c;ctx.fill()}ctx.shadowBlur=0}
function draw(){sim();ctx.clearRect(0,0,W,H);ctx.save();ctx.translate(W/2+ox,H/2+oy);ctx.scale(scale,scale);const map=lookup(),focus=selected?neighbors(selected):null;for(const e of graph.edges){const a=map.get(e.source),b=map.get(e.target);if(!a||!b)continue;const on=!focus||(focus.has(a.id)&&focus.has(b.id));ctx.globalAlpha=on?.62:.025;ctx.strokeStyle=e.kind==='context'?'#46e9b0':e.kind==='explicit_relation'?'#dc82ff':'#3acde8';ctx.lineWidth=(on?1.05:.4)/scale;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}for(const n of nodes){const on=active(n)&&matches(n),c=colors[n.kind]||colors.memory;ctx.globalAlpha=on?1:.055;if(n.kind==='memory'){ctx.shadowColor=c;ctx.shadowBlur=on?12:0;ctx.fillStyle=c;ctx.beginPath();ctx.arc(n.x,n.y,n.r+(query&&matches(n)?2:0),0,7);ctx.fill();ctx.shadowBlur=0}else nucleus(n,c);const label=n.kind!=='memory'||showNames||n===hover||(query&&matches(n));if(label){ctx.font=`${Math.max(7,10/scale)}px Consolas`;ctx.fillStyle=n.kind==='memory'?'#e8faff':c;ctx.fillText(n.label,n.x+n.r+6,n.y-4);if(n.kind!=='memory'){ctx.font=`${Math.max(6,7/scale)}px Consolas`;ctx.fillStyle='#527b87';ctx.fillText(`${n.count||0} MEM`,n.x+n.r+6,n.y+8)}}}ctx.globalAlpha=1;ctx.restore();requestAnimationFrame(draw)}
function detail(n){const d=document.getElementById('detail');if(!n){d.classList.remove('visible');return}d.classList.add('visible');document.getElementById('detailName').textContent=n.label;document.getElementById('detailMeta').textContent=n.kind==='memory'?`${n.group.toUpperCase()} / REAL MEMORY`:`${n.kind.toUpperCase()} NUCLEUS / ${n.count||0} MEMORIES`;document.getElementById('detailValue').textContent=n.kind==='memory'?(n.value||'No visible value'):'Click to isolate this nucleus';}
canvas.onmousedown=e=>{mx=startX=e.clientX;my=startY=e.clientY;drag=hit(mx,my);pan=!drag};canvas.onmousemove=e=>{hover=hit(e.clientX,e.clientY);detail(hover);if(drag){const p=world(e.clientX,e.clientY);drag.x=p.x;drag.y=p.y;drag.vx=drag.vy=0}else if(pan&&(Math.abs(e.clientX-startX)>2||Math.abs(e.clientY-startY)>2)){ox+=e.clientX-mx;oy+=e.clientY-my}mx=e.clientX;my=e.clientY};canvas.onmouseleave=()=>{hover=null;detail(null)};onmouseup=e=>{const moved=Math.hypot(e.clientX-startX,e.clientY-startY);if(moved<5){const n=hit(e.clientX,e.clientY);if(n&&n.kind!=='memory')selected=selected===n.id?null:n.id;else if(!n)selected=null}drag=null;pan=false};
canvas.onwheel=e=>{e.preventDefault();scale=Math.max(.38,Math.min(4,scale*(e.deltaY>0?.9:1.1)))},{passive:false};window.filterGraph=q=>query=(q||'').toLowerCase();document.getElementById('labelsToggle').onchange=e=>showNames=e.target.checked;document.getElementById('resetFocus').onclick=()=>selected=null;addEventListener('resize',resize);resize();draw();new QWebChannel(qt.webChannelTransport,channel=>{window.bridge=channel.objects.bridge;bridge.graphJson.connect(raw=>setGraph(JSON.parse(raw)));bridge.requestGraph()});
"""


_BODY = '''<style>
.memory-controls{position:fixed;right:18px;top:16px;z-index:5;display:flex;gap:10px;align-items:center;background:rgba(2,14,21,.9);border:1px solid #164b5e;padding:8px 10px;box-shadow:0 0 18px rgba(44,216,255,.12)}
.toggle{display:flex;align-items:center;gap:9px;color:#76dff2;font-size:9px;letter-spacing:1.5px;cursor:pointer}.toggle input{display:none}.track{width:42px;height:20px;border:1px solid #1c6075;border-radius:12px;background:#06151d;position:relative;box-shadow:inset 0 0 8px rgba(0,210,255,.12)}.track:after{content:"";position:absolute;width:14px;height:14px;left:2px;top:2px;border-radius:50%;background:#39717e;box-shadow:0 0 5px #1aa9c7;transition:.2s}.toggle input:checked+.track{border-color:#56f0c2;background:rgba(22,111,91,.25);box-shadow:0 0 12px rgba(86,240,194,.25)}.toggle input:checked+.track:after{left:24px;background:#72ffd2;box-shadow:0 0 10px #55ffc8}
#resetFocus{font:9px Consolas;color:#67dff5;background:#05141c;border:1px solid #195165;padding:5px 8px;cursor:pointer}#resetFocus:hover{color:#d8fbff;border-color:#54e5ff}.detail{position:fixed;left:18px;bottom:42px;width:310px;padding:11px 13px;background:rgba(2,15,22,.94);border:1px solid #1a566b;opacity:0;transform:translateY(5px);transition:.16s;pointer-events:none}.detail.visible{opacity:1;transform:none}.detail-name{color:#d9faff;font-size:12px}.detail-meta{color:#4fdcf4;font-size:8px;letter-spacing:1.4px;margin-top:4px}.detail-value{color:#83aeb9;font-size:9px;line-height:1.45;margin-top:7px;white-space:normal}
</style><canvas id="scene"></canvas><div class="hud"><div class="title">REAL MEMORY TOPOLOGY</div><div class="meta" id="stats">INDEXING VERIFIED MEMORIES…</div></div><div class="memory-controls"><label class="toggle">NAMES<input id="labelsToggle" type="checkbox"><i class="track"></i></label><button id="resetFocus">SHOW ALL</button></div><div id="detail" class="detail"><div id="detailName" class="detail-name"></div><div id="detailMeta" class="detail-meta"></div><div id="detailValue" class="detail-value"></div></div><div class="help">CLICK NUCLEUS TO ISOLATE · CLICK EMPTY SPACE TO RESET · DRAG · WHEEL ZOOM</div><script src="qrc:///qtwebchannel/qwebchannel.js"></script>'''


class MemoryBridge(QObject):
    graphJson = pyqtSignal(str)

    @pyqtSlot()
    def requestGraph(self) -> None:
        try:
            payload = build_memory_graph()
        except Exception as exc:
            payload = {"nodes": [], "edges": [], "stats": {}, "error": str(exc)}
        self.graphJson.emit(json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))


class MemoryGraphWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        tools = QHBoxLayout(); tools.setContentsMargins(18, 9, 18, 9)
        self.search = QLineEdit(); self.search.setPlaceholderText("FILTER REAL MEMORIES")
        self.search.setStyleSheet("color:#bdf5ff;background:#06131b;border:1px solid #164353;padding:7px")
        refresh = QPushButton("REFRESH MEMORIES"); refresh.clicked.connect(self.refresh)
        refresh.setStyleSheet(
            "QPushButton{color:#6fe7fa;background:#06151d;border:1px solid #1b5b70;"
            "padding:7px 12px;font:9px Consolas;letter-spacing:1px}"
            "QPushButton:hover{color:#e0fbff;border-color:#54e5ff;background:#09232e}"
        )
        tools.addWidget(self.search, 1); tools.addWidget(refresh); layout.addLayout(tools)
        self.view = QWebEngineView(); layout.addWidget(self.view, 1)
        self.bridge = MemoryBridge(self)
        self.channel = QWebChannel(self.view.page()); self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.setHtml(_document("JARVIS Real Memory", _BODY, _SCRIPT), QUrl("https://jarvis.local/memory"))
        self.search.textChanged.connect(
            lambda value: self.view.page().runJavaScript(f"filterGraph({json.dumps(value)})")
        )

    def refresh(self) -> None:
        self.bridge.requestGraph()
