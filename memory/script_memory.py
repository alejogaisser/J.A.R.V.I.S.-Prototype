"""Central, file-free catalog of reusable JARVIS routines."""
from __future__ import annotations
import json, re, subprocess, sys
from pathlib import Path
from threading import Lock
from core.clock import local_now
BASE=Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent.parent
SCRIPT_MEMORY_PATH=BASE/"memory"/"scripts.json"; _lock=Lock()
def _key(name): return re.sub(r"[^a-z0-9]+","_",str(name).lower()).strip("_") or "unnamed_routine"
def load_scripts():
    try:
        data=json.loads(SCRIPT_MEMORY_PATH.read_text(encoding="utf-8"))
        if data.get("version")==2 and isinstance(data.get("scripts"),dict): return data
    except (OSError,ValueError,TypeError,json.JSONDecodeError): pass
    return {"version":2,"scripts":{}}
def register_script(name,code,purpose,language="python"):
    data=load_scripts(); entry={"name":name.strip(),"purpose":purpose.strip()[:600],"language":language.lower().strip(),"code":code,"updated":local_now().isoformat()}
    data["scripts"][_key(name)]=entry; SCRIPT_MEMORY_PATH.parent.mkdir(parents=True,exist_ok=True)
    with _lock: SCRIPT_MEMORY_PATH.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return entry
def get_script(name): return load_scripts()["scripts"].get(_key(name))
def is_registered_script(name): return get_script(name) is not None
def run_script(name,timeout=30):
    entry=get_script(name)
    if not entry: return f"Unknown routine: {name}"
    commands={"python":[sys.executable,"-c"],"py":[sys.executable,"-c"],"powershell":["powershell","-NoProfile","-Command"],"ps1":["powershell","-NoProfile","-Command"],"javascript":["node","-e"],"js":["node","-e"]}
    command=commands.get(entry.get("language","python"))
    if not command: return f"Unsupported routine language: {entry.get('language')}"
    try:
        result=subprocess.run(command+[entry["code"]],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
        output="\n".join(x for x in (result.stdout.strip(),result.stderr.strip()) if x)
        return output or f"Routine '{entry['name']}' completed."
    except subprocess.TimeoutExpired: return f"Routine '{entry['name']}' timed out after {timeout}s."
    except Exception as exc: return f"Routine '{entry['name']}' failed: {exc}"
def format_scripts_for_prompt(limit=25):
    entries=list(load_scripts()["scripts"].values())[-limit:]
    if not entries:return ""
    return "[KNOWN ROUTINES — stored internally; run by routine_name]\n"+"\n".join(f"- {e['name']}: {e['purpose']} | language={e['language']}" for e in entries)+"\n"
