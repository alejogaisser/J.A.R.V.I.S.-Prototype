"""Interactive geographic web surfaces for the holographic globe and live map."""

from __future__ import annotations

import json
from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView


def _document(title: str, body: str, script: str) -> str:
    return f"""<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title>
<style>
*{{box-sizing:border-box}}html,body{{width:100%;height:100%;margin:0;overflow:hidden;background:#02070c;color:#c9f7ff;font-family:Consolas,monospace}}
canvas{{width:100%;height:100%;display:block}}.hud{{position:fixed;left:18px;top:17px;z-index:3;pointer-events:none}}
.title{{font-size:12px;letter-spacing:3px;color:#72e8ff}}.meta{{margin-top:6px;font-size:9px;line-height:1.6;color:#5c8491}}
.help{{position:fixed;right:18px;bottom:14px;font-size:9px;color:#416571;letter-spacing:1px}}
</style></head><body>{body}<script>{script}</script></body></html>"""


_GLOBE_SCRIPT = r"""
const c=document.getElementById('scene'),x=c.getContext('2d');let W,H,dpr=1,rot=-.5,tilt=-.15,zoom=1,drag=false,px=0,py=0,target=null,routePath=[];
const pts=[];for(let lat=-84;lat<=84;lat+=6)for(let lon=-180;lon<180;lon+=6){let la=lat*Math.PI/180,lo=lon*Math.PI/180;pts.push([Math.cos(la)*Math.cos(lo),Math.sin(la),Math.cos(la)*Math.sin(lo)])}
function resize(){dpr=Math.min(devicePixelRatio||1,2);W=innerWidth;H=innerHeight;c.width=W*dpr;c.height=H*dpr;x.setTransform(dpr,0,0,dpr,0,0)}
function focusLocation(lat,lon,label){rot=-lon*Math.PI/180;tilt=Math.max(-1.1,Math.min(1.1,lat*Math.PI/180*.65));zoom=1.55;target={lat,lon,label};document.getElementById('focus').textContent=`FOCUS / ${label||lat.toFixed(2)+', '+lon.toFixed(2)}`}
window.focusLocation=focusLocation;
window.showRoute=path=>{routePath=path||[];if(routePath.length){let p=routePath[Math.floor(routePath.length/2)];focusLocation(p.lat,p.lng,'ROUTE / '+routePath.length+' POINTS')}};
function frame(){x.clearRect(0,0,W,H);let R=Math.min(W,H)*.31*zoom,cx=W*.51,cy=H*.52,cr=Math.cos(rot),sr=Math.sin(rot),ct=Math.cos(tilt),st=Math.sin(tilt);let grd=x.createRadialGradient(cx-R*.2,cy-R*.2,R*.05,cx,cy,R*1.1);grd.addColorStop(0,'rgba(0,172,255,.13)');grd.addColorStop(.72,'rgba(0,32,52,.38)');grd.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=grd;x.beginPath();x.arc(cx,cy,R*1.12,0,7);x.fill();
x.globalCompositeOperation='lighter';for(const p of pts){let X=p[0]*cr-p[2]*sr,Z=p[0]*sr+p[2]*cr,Y=p[1]*ct-Z*st;Z=p[1]*st+Z*ct;if(Z<-.06)continue;let a=.18+.82*(Z+1)/2,sz=1.05+1.8*a;x.fillStyle=`rgba(77,225,255,${a*.85})`;x.fillRect(cx+X*R,cy-Y*R,sz,sz)}x.strokeStyle='rgba(77,225,255,.58)';x.lineWidth=1;x.beginPath();x.arc(cx,cy,R,0,7);x.stroke();
if(routePath.length){x.strokeStyle='rgba(255,211,106,.9)';x.shadowColor='#ffd36a';x.shadowBlur=10;x.lineWidth=2;x.beginPath();let started=false;for(const q of routePath){let la=q.lat*Math.PI/180,lo=q.lng*Math.PI/180,p=[Math.cos(la)*Math.cos(lo),Math.sin(la),Math.cos(la)*Math.sin(lo)],X=p[0]*cr-p[2]*sr,Z=p[0]*sr+p[2]*cr,Y=p[1]*ct-Z*st;Z=p[1]*st+Z*ct;if(Z<0){started=false;continue}let sx=cx+X*R,sy=cy-Y*R;if(!started){x.moveTo(sx,sy);started=true}else x.lineTo(sx,sy)}x.stroke();x.shadowBlur=0}for(let k=0;k<3;k++){x.strokeStyle=`rgba(63,207,255,${.12-k*.025})`;x.beginPath();x.ellipse(cx,cy,R*(1.17+k*.12),R*(.18+k*.035),-.18+k*.17,0,7);x.stroke()}x.globalCompositeOperation='source-over';if(!drag)rot+=.0015;requestAnimationFrame(frame)}
c.onmousedown=e=>{drag=true;px=e.clientX;py=e.clientY};c.onmousemove=e=>{if(!drag)return;rot+=(e.clientX-px)*.008;tilt=Math.max(-1.2,Math.min(1.2,tilt+(e.clientY-py)*.005));px=e.clientX;py=e.clientY};onmouseup=()=>drag=false;c.onwheel=e=>{e.preventDefault();zoom=Math.max(.55,Math.min(2.35,zoom*(e.deltaY>0?.9:1.1)))},{passive:false};addEventListener('resize',resize);resize();frame();
"""


_OPEN_MAP_SCRIPT = r"""
const status=document.getElementById('focus');
if(!window.maplibregl){status.textContent='LIVE MAP UNAVAILABLE / USE HOLO MODE';throw new Error('MapLibre failed to load')}
const map=new maplibregl.Map({
  container:'map',style:'https://tiles.openfreemap.org/styles/dark',
  center:[-58.3816,-34.6037],zoom:1.55,pitch:18,bearing:0,
  projection:{type:'globe'},antialias:true,attributionControl:true
});
map.addControl(new maplibregl.NavigationControl({visualizePitch:true}),'bottom-right');
map.addControl(new maplibregl.GlobeControl(),'bottom-right');
map.on('style.load',()=>{
  map.setProjection({type:'globe'});
  if(map.setFog)map.setFog({color:'rgb(2,10,16)','high-color':'rgb(5,56,75)','space-color':'rgb(0,2,5)','horizon-blend':.16,'star-intensity':.28});
});
map.on('load',()=>{
  status.textContent='OPEN DATA LINK / ONLINE';
  // OpenFreeMap's dark theme is intentionally preserved. Only typography
  // and administrative boundaries receive a restrained contrast lift.
  for(const layer of (map.getStyle().layers||[])){
    const id=String(layer.id||'').toLowerCase();
    if(layer.type==='symbol'&&layer.layout&&layer.layout['text-field']!==undefined){
      try{
        map.setPaintProperty(layer.id,'text-color','#f0fbff');
        map.setPaintProperty(layer.id,'text-halo-color','rgba(0,8,13,.94)');
        map.setPaintProperty(layer.id,'text-halo-width',1.15);
        map.setPaintProperty(layer.id,'text-halo-blur',.25);
      }catch(e){}
    }
    if(layer.type==='line'&&/(boundary|admin|border|country|state|province)/.test(id)){
      try{
        map.setPaintProperty(layer.id,'line-color','#a9cbd4');
        map.setPaintProperty(layer.id,'line-opacity',.46);
      }catch(e){}
    }
  }
  map.addSource('jarvis-route',{type:'geojson',data:{type:'Feature',geometry:{type:'LineString',coordinates:[]}}});
  map.addLayer({id:'jarvis-route-glow',type:'line',source:'jarvis-route',paint:{'line-color':'#40dfff','line-width':9,'line-opacity':.22,'line-blur':7}});
  map.addLayer({id:'jarvis-route',type:'line',source:'jarvis-route',paint:{'line-color':'#8ef5ff','line-width':3.5,'line-opacity':.95}});
  if(map.getSource('openmaptiles')&&!map.getLayer('jarvis-buildings')){
    try{map.addLayer({id:'jarvis-buildings',source:'openmaptiles','source-layer':'building',type:'fill-extrusion',minzoom:14,filter:['!=',['get','hide_3d'],true],paint:{'fill-extrusion-color':'#0d6f83','fill-extrusion-height':['coalesce',['get','render_height'],['get','height'],6],'fill-extrusion-base':['coalesce',['get','render_min_height'],0],'fill-extrusion-opacity':.68}})}catch(e){}
  }
});
window.focusLocation=(lat,lon,label)=>{
  status.textContent='FOCUS / '+label;
  map.flyTo({center:[lon,lat],zoom:12.5,pitch:62,bearing:24,duration:2800,essential:true});
};
window.showRoute=path=>{
  const coords=(path||[]).map(p=>[p.lng,p.lat]);
  const source=map.getSource('jarvis-route');if(source)source.setData({type:'Feature',properties:{},geometry:{type:'LineString',coordinates:coords}});
  if(coords.length>1){const bounds=coords.reduce((b,p)=>b.extend(p),new maplibregl.LngLatBounds(coords[0],coords[0]));map.fitBounds(bounds,{padding:90,pitch:52,bearing:18,duration:2600});status.textContent='ACTIVE ROUTE / OPENSTREETMAP'}
};
"""


class GeoWorkspace(QWidget):
    locationRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent); root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        bar=QHBoxLayout(); bar.setContentsMargins(18,9,18,9); self.search=QLineEdit(); self.search.setPlaceholderText("LOCATION / CITY / LANDMARK")
        self.search.setStyleSheet("color:#bdf5ff;background:#06131b;border:1px solid #164353;padding:7px")
        go=QPushButton("LOCATE"); live=QPushButton("LIVE MAP"); holo=QPushButton("HOLO GLOBE")
        go.clicked.connect(self._request); self.search.returnPressed.connect(self._request)
        live.clicked.connect(self.show_open_map); holo.clicked.connect(self.show_offline)
        bar.addWidget(self.search,1); bar.addWidget(go); bar.addWidget(live); bar.addWidget(holo); root.addLayout(bar)
        self.view=QWebEngineView(); root.addWidget(self.view,1); self.show_open_map()

    def _request(self):
        query=self.search.text().strip()
        if query: self.locationRequested.emit(query)

    def show_offline(self):
        body='<canvas id="scene"></canvas><div class="hud"><div class="title">PLANETARY GEO INTERFACE</div><div class="meta" id="focus">OFFLINE HOLOGRAPHIC MODE</div></div><div class="help">DRAG TO ROTATE · WHEEL TO ZOOM · GOOGLE MODE REQUIRES SETUP</div>'
        self.view.setHtml(_document("JARVIS Geo",body,_GLOBE_SCRIPT),QUrl("https://jarvis.local/geo"))

    def focus_location(self, latitude: float, longitude: float, label: str):
        js=f"focusLocation({float(latitude)},{float(longitude)},{json.dumps(label)})"; self.view.page().runJavaScript(js)

    def show_route(self, path: list[dict]):
        self.view.page().runJavaScript(f"showRoute({json.dumps(path)})")

    def show_open_map(self):
        body = '''
<link href="https://unpkg.com/maplibre-gl@5.10.0/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@5.10.0/dist/maplibre-gl.js"></script>
<div id="map" style="width:100%;height:100%;filter:saturate(1.28) brightness(.92) contrast(1.15)"></div>
<div style="position:fixed;inset:0;pointer-events:none;z-index:2;background:repeating-linear-gradient(0deg,transparent 0,transparent 4px,rgba(67,221,255,.025) 5px),linear-gradient(90deg,rgba(0,217,255,.08) 1px,transparent 1px),linear-gradient(rgba(0,217,255,.055) 1px,transparent 1px),radial-gradient(circle at 50% 50%,transparent 35%,rgba(0,8,14,.5) 100%);background-size:auto,80px 80px,80px 80px,auto;box-shadow:inset 0 0 90px rgba(18,203,255,.2),inset 0 0 0 1px rgba(84,230,255,.24)"></div>
<div class="hud"><div class="title">OPEN PLANETARY GEO INTERFACE</div><div class="meta" id="focus">LINKING OPEN DATA LAYERS…</div><div class="meta">MAPLIBRE / OPENFREEMAP / OPENSTREETMAP</div></div>
<div class="help">DRAG · ROTATE · PITCH · ZOOM · ZERO KEYS · ZERO BILLING</div>'''
        self.view.setHtml(_document("JARVIS Open Geo", body, _OPEN_MAP_SCRIPT), QUrl("https://jarvis.local/geo"))
