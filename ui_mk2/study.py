"""Holographic Study workspace for structured scientific artifacts."""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>JARVIS Study</title>
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<script src="https://www.geogebra.org/apps/deployggb.js"></script>
<style>
*{box-sizing:border-box}html,body{height:100%;margin:0;background:#02070c;color:#c9f7ff;font-family:Consolas,monospace;overflow:hidden}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,transparent 0,transparent 5px,rgba(71,225,255,.025) 6px),linear-gradient(90deg,rgba(43,205,255,.045) 1px,transparent 1px),linear-gradient(rgba(43,205,255,.035) 1px,transparent 1px);background-size:auto,72px 72px,72px 72px}
#shell{height:100%;display:grid;grid-template-columns:minmax(260px,34%) 1fr;gap:12px;padding:14px;position:relative}
.panel{border:1px solid #18566b;background:linear-gradient(145deg,rgba(5,25,35,.94),rgba(1,9,15,.96));box-shadow:inset 0 0 32px rgba(0,198,255,.06),0 0 18px rgba(0,190,255,.05);min-height:0;overflow:auto}
.head{padding:14px 16px;border-bottom:1px solid #164353;position:sticky;top:0;background:#06131beF;z-index:2}.eyebrow{font-size:9px;letter-spacing:3px;color:#4edfff}.title{font-size:19px;letter-spacing:1px;margin-top:6px;color:#e0fbff}.subject{display:inline-block;margin-top:9px;padding:3px 8px;border:1px solid #2a7990;color:#68eaff;font-size:9px}
.content{padding:14px 16px}.label{font-size:8px;color:#527a86;letter-spacing:2px;margin:14px 0 6px}.text{white-space:pre-wrap;line-height:1.55;font-size:12px}.result{color:#89ffd5;border-left:2px solid #45f0bd;padding:9px;background:rgba(24,116,91,.09)}
.step{display:grid;grid-template-columns:28px 1fr;gap:8px;margin:7px 0;padding:8px;border:1px solid #123947;background:rgba(3,23,31,.7)}.num{color:#4edfff}.note{color:#8dafb9;font-size:10px;margin:7px 0}.source{color:#ffd36a;font-size:9px;margin-right:10px}
#visual{height:100%;min-height:340px;position:relative;overflow:hidden}.empty{height:100%;display:flex;align-items:center;justify-content:center;text-align:center;color:#416a76;letter-spacing:2px;line-height:2}.viz{width:100%;height:100%}#mol2d{padding:30px;height:100%;display:flex;align-items:center;justify-content:center}#mol2d svg{max-width:100%;max-height:100%;filter:drop-shadow(0 0 9px #34dfff)}
canvas{width:100%;height:100%}.corner{position:fixed;width:28px;height:28px;border-color:#42ddff;pointer-events:none}.tl{left:8px;top:8px;border-left:2px solid;border-top:2px solid}.br{right:8px;bottom:8px;border-right:2px solid;border-bottom:2px solid}
@media(max-width:850px){#shell{grid-template-columns:1fr;grid-template-rows:48% 52%}}
</style></head><body><i class="corner tl"></i><i class="corner br"></i><main id="shell">
<section class="panel"><div class="head"><div class="eyebrow">JARVIS / SCIENTIFIC WORKSPACE</div><div id="title" class="title">STUDY MODULE</div><div id="subject" class="subject">READY</div></div><div class="content"><div class="label">PROBLEM</div><div id="problem" class="text">Awaiting a mathematical or scientific artifact.</div><div class="label">VERIFIED RESULT</div><div id="result" class="text result">No result loaded.</div><div id="steps"></div><div id="notes"></div><div id="sources"></div></div></section>
<section class="panel" id="visual"><div class="empty">HOLOGRAPHIC VISUALIZATION ARRAY<br>2D / 3D / VECTOR / MOLECULAR / ANATOMY</div></section></main>
<script>
const by=id=>document.getElementById(id), text=(id,value)=>by(id).textContent=value||'—';
function clearVisual(){const v=by('visual');v.innerHTML=''}
function localCanvas(host){const c=document.createElement('canvas');c.className='viz';host.appendChild(c);return c}
function rotatePoint(p,yaw,pitch){const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),x=p[0]*cy-p[2]*sy,z=p[0]*sy+p[2]*cy;return[x,p[1]*cp-z*sp,p[1]*sp+z*cp]}
function eulerPoint(p,r){r=r||[0,0,0];let[x,y,z]=p,[cx,sx]=[Math.cos(r[0]),Math.sin(r[0])],[cy,sy]=[Math.cos(r[1]),Math.sin(r[1])],[cz,sz]=[Math.cos(r[2]),Math.sin(r[2])];[y,z]=[y*cx-z*sx,y*sx+z*cx];[x,z]=[x*cy+z*sy,-x*sy+z*cy];return[x*cz-y*sz,x*sz+y*cz,z]}
function rgb(hex,shade=1,alpha=1){const n=parseInt(String(hex||'#42ddff').slice(1),16),r=Math.min(255,((n>>16)&255)*shade),g=Math.min(255,((n>>8)&255)*shade),b=Math.min(255,(n&255)*shade);return`rgba(${r|0},${g|0},${b|0},${alpha})`}
function interactiveMesh(canvas,meshes,labels,title){const ctx=canvas.getContext('2d'),state={yaw:-.55,pitch:.32,zoom:1,drag:false,x:0,y:0};let frame=0;
function draw(){frame=0;const rect=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2),w=rect.width,h=rect.height;canvas.width=Math.max(1,w*d);canvas.height=Math.max(1,h*d);ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,w,h);const extent=Math.max(1,...meshes.flatMap(m=>m.vertices.flatMap(p=>p.map(Math.abs)))),scale=Math.min(w,h)*.34*state.zoom/extent,faces=[];
meshes.forEach(mesh=>{const points=mesh.vertices.map(p=>rotatePoint(p,state.yaw,state.pitch));mesh.faces.forEach(face=>{const ps=face.map(i=>points[i]),a=ps[0],b=ps[1],c=ps[2],ux=b[0]-a[0],uy=b[1]-a[1],uz=b[2]-a[2],vx=c[0]-a[0],vy=c[1]-a[1],vz=c[2]-a[2],nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx,nl=Math.hypot(nx,ny,nz)||1,light=Math.max(0,(nx*.25+ny*.45+nz*.86)/nl),depth=ps.reduce((sum,p)=>sum+p[2],0)/ps.length;faces.push({ps,depth,color:mesh.color,alpha:mesh.alpha??.86,shade:.28+.72*light})})});
faces.sort((a,b)=>a.depth-b.depth);faces.forEach(face=>{ctx.beginPath();face.ps.forEach((p,i)=>{const x=w/2+p[0]*scale,y=h/2-p[1]*scale;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.closePath();ctx.fillStyle=rgb(face.color,face.shade,face.alpha);ctx.fill();ctx.strokeStyle=rgb(face.color,Math.min(1.25,face.shade+.2),.24);ctx.lineWidth=.65;ctx.stroke()});
ctx.font='10px Consolas';ctx.textAlign='center';labels.forEach(label=>{const p=rotatePoint(label.center,state.yaw,state.pitch),x=w/2+p[0]*scale,y=h/2-p[1]*scale;ctx.fillStyle='#dffaff';ctx.fillRect(x-2,y-2,4,4);ctx.fillStyle='#9edce8';ctx.fillText(label.text,x,y-8)});ctx.textAlign='left';ctx.fillStyle='#8bddea';ctx.font='11px Consolas';ctx.fillText(title,18,24);ctx.fillStyle='#416a76';ctx.font='9px Consolas';ctx.fillText('DRAG TO ROTATE  ·  WHEEL TO ZOOM  ·  LOCAL RENDERER',18,h-18)}
const request=()=>{if(!frame)frame=requestAnimationFrame(draw)};canvas.addEventListener('pointerdown',e=>{state.drag=true;state.x=e.clientX;state.y=e.clientY;canvas.setPointerCapture(e.pointerId)});canvas.addEventListener('pointermove',e=>{if(!state.drag)return;state.yaw+=(e.clientX-state.x)*.009;state.pitch=Math.max(-1.35,Math.min(1.35,state.pitch+(e.clientY-state.y)*.009));state.x=e.clientX;state.y=e.clientY;request()});canvas.addEventListener('pointerup',()=>state.drag=false);canvas.addEventListener('wheel',e=>{e.preventDefault();state.zoom=Math.max(.45,Math.min(3,state.zoom*Math.exp(-e.deltaY*.001)));request()},{passive:false});new ResizeObserver(request).observe(canvas);request()}
function renderPlot2dLocal(v,host){const c=localCanvas(host),ctx=c.getContext('2d');function draw(){const r=c.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2),w=r.width,h=r.height,pad=58;c.width=w*d;c.height=h*d;ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,w,h);const xs=(v.x&&v.x.length?v.x:[-1,1]),valid=(v.y||[]).filter(Number.isFinite),ys=valid.length?valid:[0],xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),yr=(ymax-ymin)||1,xr=(xmax-xmin)||1,X=x=>pad+(x-xmin)/xr*(w-pad*1.4),Y=y=>h-pad-(y-ymin)/yr*(h-pad*1.6);ctx.strokeStyle='#123947';ctx.lineWidth=1;ctx.fillStyle='#648d98';ctx.font='9px Consolas';for(let i=0;i<=10;i++){const x=pad+i*(w-pad*1.4)/10,y=pad*.65+i*(h-pad*1.6)/10;ctx.beginPath();ctx.moveTo(x,pad*.65);ctx.lineTo(x,h-pad);ctx.stroke();ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad*.4,y);ctx.stroke()}ctx.strokeStyle='#42ddff';ctx.lineWidth=2.5;ctx.shadowColor='#42ddff';ctx.shadowBlur=8;ctx.beginPath();let open=false;(v.y||[]).forEach((y,i)=>{if(!Number.isFinite(y)){open=false;return}const x=X(xs[i]),py=Y(y);open?ctx.lineTo(x,py):ctx.moveTo(x,py);open=true});ctx.stroke();ctx.shadowBlur=0;ctx.fillStyle='#baf7ff';ctx.font='11px Consolas';ctx.fillText(v.expression||'FUNCTION',18,24);ctx.fillStyle='#648d98';ctx.font='9px Consolas';ctx.fillText(`${xmin.toFixed(2)} ≤ x ≤ ${xmax.toFixed(2)}   ·   ${ymin.toFixed(2)} ≤ y ≤ ${ymax.toFixed(2)}   ·   LOCAL RENDERER`,18,h-18)}new ResizeObserver(draw).observe(c);draw()}
function renderPlot3dLocal(v,host){const xs=(v.x&&v.x.length?v.x:[-1,1]),ys=(v.y&&v.y.length?v.y:[-1,1]),zs=v.z||[],values=zs.flat().filter(Number.isFinite),finite=values.length?values:[0],zmin=Math.min(...finite),zmax=Math.max(...finite),cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2,cz=(zmin+zmax)/2,span=Math.max(Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys),zmax-zmin,1),vertices=[],faces=[],index=[];zs.forEach((row,j)=>{index[j]=[];row.forEach((z,i)=>{index[j][i]=vertices.length;vertices.push([(xs[i]-cx)*3/span,(ys[j]-cy)*3/span,Number.isFinite(z)?(z-cz)*3/span:0])})});for(let j=0;j<zs.length-1;j++)for(let i=0;i<zs[j].length-1;i++)if([zs[j][i],zs[j][i+1],zs[j+1][i+1],zs[j+1][i]].every(Number.isFinite))faces.push([index[j][i],index[j][i+1],index[j+1][i+1],index[j+1][i]]);const c=localCanvas(host);interactiveMesh(c,[{vertices,faces,color:'#29dfff',alpha:.78}],[],`${v.expression||'SURFACE'} · 3D SURFACE`)}
function renderPlotLocal(v,host){v.type==='plot2d'?renderPlot2dLocal(v,host):renderPlot3dLocal(v,host)}
function anatomyMesh(part){const n=28,m=18,vertices=[],faces=[],center=part.center||[0,0,0],scale=part.scale||[1,1,1],rot=part.rotation||[0,0,0];for(let j=0;j<=m;j++){const t=j/m;for(let i=0;i<n;i++){const u=2*Math.PI*i/n,phi=Math.PI*(t-.5),radius=part.shape==='tube'?Math.sin(Math.PI*t):Math.cos(phi);let p=part.shape==='tube'?[scale[0]*radius*Math.cos(u),scale[1]*(2*t-1),scale[2]*radius*Math.sin(u)]:[scale[0]*radius*Math.cos(u),scale[1]*Math.sin(phi),scale[2]*radius*Math.sin(u)];p=eulerPoint(p,rot);vertices.push([p[0]+center[0],p[1]+center[1],p[2]+center[2]])}}for(let j=0;j<m;j++)for(let i=0;i<n;i++){const k=j*n+i,next=j*n+(i+1)%n;faces.push([k,next,next+n,k+n])}return{vertices,faces,color:part.color,alpha:part.opacity??.86}}
function renderAnatomyLocal(v,host){const parts=v.parts||[],c=localCanvas(host);interactiveMesh(c,parts.map(anatomyMesh),parts.filter(p=>p.label).map(p=>({center:p.center,text:p.label})),`${String(v.organ||'ANATOMY').toUpperCase()} · EDUCATIONAL 3D SCHEMATIC`)}
function renderPlot(v){clearVisual();const d=document.createElement('div');d.className='viz';by('visual').appendChild(d);renderPlotLocal(v,d)}
function renderForces(v){clearVisual();const c=document.createElement('canvas');by('visual').appendChild(c);const ctx=c.getContext('2d');function draw(){const r=c.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2);c.width=r.width*d;c.height=r.height*d;ctx.setTransform(d,0,0,d,0,0);const w=r.width,h=r.height,cx=w/2,cy=h/2,forces=v.forces||[],max=Math.max(1,...forces.map(f=>f.magnitude));ctx.strokeStyle='#164353';ctx.lineWidth=1;for(let i=0;i<w;i+=48){ctx.beginPath();ctx.moveTo(i,0);ctx.lineTo(i,h);ctx.stroke()}for(let i=0;i<h;i+=48){ctx.beginPath();ctx.moveTo(0,i);ctx.lineTo(w,i);ctx.stroke()}ctx.strokeStyle='#5fdfff';ctx.beginPath();ctx.moveTo(30,cy);ctx.lineTo(w-30,cy);ctx.moveTo(cx,30);ctx.lineTo(cx,h-30);ctx.stroke();ctx.fillStyle='#0a2632';ctx.strokeStyle='#a8f7ff';ctx.lineWidth=2;ctx.fillRect(cx-42,cy-30,84,60);ctx.strokeRect(cx-42,cy-30,84,60);
forces.forEach((f,i)=>{const a=-f.angle_deg*Math.PI/180,L=70+125*f.magnitude/max,ex=cx+Math.cos(a)*L,ey=cy+Math.sin(a)*L,col=['#42ddff','#ffd36a','#58ffbd','#dd82ff'][i%4];ctx.strokeStyle=col;ctx.fillStyle=col;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(ex,ey);ctx.stroke();const hd=.35;ctx.beginPath();ctx.moveTo(ex,ey);ctx.lineTo(ex-13*Math.cos(a-hd),ey-13*Math.sin(a-hd));ctx.lineTo(ex-13*Math.cos(a+hd),ey-13*Math.sin(a+hd));ctx.closePath();ctx.fill();ctx.font='12px Consolas';ctx.fillText(`${f.label} / ${f.magnitude} N`,ex+8,ey-8)});ctx.fillStyle='#78a9b5';ctx.font='10px Consolas';ctx.fillText(`ΣFx ${Number(v.sum_x).toFixed(3)} N  /  ΣFy ${Number(v.sum_y).toFixed(3)} N`,24,h-24)}draw();addEventListener('resize',draw,{once:true})}
function renderMolecule(v){clearVisual();const host=by('visual');if(v.molblock&&window.$3Dmol){const d=document.createElement('div');d.className='viz';host.appendChild(d);const viewer=$3Dmol.createViewer(d,{backgroundColor:'#02070c'});viewer.addModel(v.molblock,'sdf');viewer.setStyle({stick:{colorscheme:'Jmol',radius:.15},sphere:{colorscheme:'Jmol',scale:.28}});viewer.zoomTo();viewer.spin('y',.45);viewer.render()}else if(v.svg){const d=document.createElement('div');d.id='mol2d';d.innerHTML=v.svg;host.appendChild(d)}else{host.innerHTML='<div class="empty">MOLECULAR RENDERER UNAVAILABLE<br>TEXT DATA PRESERVED</div>'}}
function renderAnatomy(v){clearVisual();const host=by('visual'),d=document.createElement('div');d.className='viz';host.appendChild(d);renderAnatomyLocal(v,d)}
function renderGeoGebra(v){clearVisual();const host=by('visual');const d=document.createElement('div');d.id='ggb';d.className='viz';host.appendChild(d);if(!window.GGBApplet){d.className='empty';d.textContent='GEOGEBRA EMBED OFFLINE';return}const app=new GGBApplet({appName:'graphing3d',width:900,height:650,showToolBar:true,showAlgebraInput:true,showMenuBar:false,enableShiftDragZoom:true,appletOnLoad:api=>api.evalCommand(v.expression)},true);app.inject('ggb')}
function renderArtifact(a){a=a||{};text('title',a.title||'STUDY MODULE');text('subject',a.subject||'READY');text('problem',a.problem||'No problem supplied.');text('result',a.result||'No result supplied.');const steps=by('steps');steps.innerHTML='';(a.steps||[]).forEach((s,i)=>{const d=document.createElement('div');d.className='step';const n=document.createElement('span');n.className='num';n.textContent=String(i+1).padStart(2,'0');const t=document.createElement('span');t.textContent=s;d.append(n,t);steps.appendChild(d)});const notes=by('notes');notes.innerHTML='';(a.notes||[]).forEach(n=>{const d=document.createElement('div');d.className='note';d.textContent='◈ '+n;notes.appendChild(d)});const sources=by('sources');sources.innerHTML='';(a.sources||[]).forEach(s=>{const a=document.createElement('a');a.className='source';a.href=s.url;a.textContent=s.name;a.target='_blank';sources.appendChild(a)});const v=a.visualization||{};if(v.type==='plot2d'||v.type==='plot3d')renderPlot(v);else if(v.type==='free_body')renderForces(v);else if(v.type==='molecule')renderMolecule(v);else if(v.type==='anatomy')renderAnatomy(v);else if(v.type==='geogebra')renderGeoGebra(v);else by('visual').innerHTML='<div class="empty">SOLUTION DATA READY<br>NO VISUAL ARTIFACT REQUIRED</div>'}
window.renderArtifact=renderArtifact;
</script></body></html>"""


class StudyWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.latest_artifact: dict | None = None
        self._page_ready = False
        self._load_failed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(18, 8, 18, 8)
        label = QLabel("STUDY / LOCAL SCIENTIFIC CORE")
        label.setStyleSheet("color:#77eaff;font-family:Consolas;font-size:10px;letter-spacing:2px")
        self.pending = QLabel("READY")
        self.pending.setStyleSheet("color:#55ffbd;font-family:Consolas;font-size:9px")
        reload_button = QPushButton("RESTORE LAST")
        reload_button.clicked.connect(self.restore_latest)
        bar.addWidget(label)
        bar.addStretch()
        bar.addWidget(self.pending)
        bar.addWidget(reload_button)
        root.addLayout(bar)
        self._content = QStackedWidget()
        self._loading = QLabel("INITIALIZING STUDY CORE...")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet(
            "color:#55dfff;background:#02070c;font-family:Consolas;"
            "font-size:12px;letter-spacing:3px"
        )
        self.view = QWebEngineView()
        self._content.addWidget(self._loading)
        self._content.addWidget(self.view)
        root.addWidget(self._content, 1)
        self.view.loadFinished.connect(self._handle_load_finished)
        self.view.setHtml(_HTML, QUrl("https://jarvis.local/study"))

    def set_artifact(self, artifact: dict, pending: bool = False) -> None:
        self.latest_artifact = dict(artifact)
        self.pending.setText("RESULT WAITING" if pending else "LIVE RESULT")
        if not self._page_ready:
            return
        self._render_latest()

    def prepare_for_display(self) -> None:
        """Expose a deterministic local state while WebEngine initializes."""
        self._content.setCurrentWidget(self.view if self._page_ready else self._loading)
        if self._load_failed:
            self._start_page_load()
        if self._page_ready:
            self.restore_latest()

    def _handle_load_finished(self, loaded: bool) -> None:
        self._page_ready = bool(loaded)
        self._load_failed = not loaded
        if not self._page_ready:
            self._loading.setText("STUDY CORE FAILED TO LOAD / PRESS RESTORE LAST")
            self.pending.setText("LOAD ERROR")
            self._content.setCurrentWidget(self._loading)
            return
        self._content.setCurrentWidget(self.view)
        self.pending.setText("LIVE RESULT" if self.latest_artifact else "READY")
        self._render_latest()

    def _start_page_load(self) -> None:
        self._load_failed = False
        self._loading.setText("INITIALIZING STUDY CORE...")
        self.pending.setText("LOADING")
        self._content.setCurrentWidget(self._loading)
        self.view.setHtml(_HTML, QUrl("https://jarvis.local/study"))

    def _render_latest(self) -> None:
        if not self._page_ready or not self.latest_artifact:
            return
        self.view.page().runJavaScript(
            f"renderArtifact({json.dumps(self.latest_artifact, ensure_ascii=False)})"
        )

    def restore_latest(self) -> None:
        if not self._page_ready:
            if self._load_failed:
                self._start_page_load()
            return
        self.pending.setText("LIVE RESULT" if self.latest_artifact else "READY")
        self._render_latest()
