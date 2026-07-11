from flask import Flask, jsonify, render_template, request, redirect
from pathlib import Path
import json, os, tempfile, threading, time, shutil

app=Flask(__name__)
DATA_DIR=Path(os.environ.get("DATA_DIR","data"))
INITIAL_DIR=Path(__file__).parent/"initial_data"
APP_PASSWORD=os.environ.get("APP_PASSWORD","1234")
USERS={"yeop","yeom","yeong"}
lock=threading.Lock()

def authorized():
    if not APP_PASSWORD: return True
    return request.headers.get("Authorization","")==f"Bearer {APP_PASSWORD}"

def data_file(user): return DATA_DIR/f"academy_online_{user}.json"
def ensure_user_data(user):
    p=data_file(user)
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    initial=INITIAL_DIR/f"{user}.json"
    must_seed=not p.exists()
    if p.exists() and user=="yeop":
        try:
            current=json.loads(p.read_text(encoding="utf-8"))
            names=[s.get("name") for c in current.get("classes",[]) for s in c.get("students",[])]
            must_seed=(current.get("__onlineSeedVersion",0)<3 or not current.get("classes") or "김학생" in names)
        except Exception:
            must_seed=True
    if must_seed:
        if initial.exists(): shutil.copyfile(initial,p)
        else: p.write_text('{"classes":[],"records":{},"todos":[],"pad":""}',encoding="utf-8")
    return p

def read_data(user):
    p=ensure_user_data(user)
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}

def write_data(user,data):
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f"academy_{user}_",suffix=".json",dir=str(DATA_DIR))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,data_file(user))
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

@app.get("/")
def root(): return redirect("/yeop")

@app.get("/<user>")
def index(user):
    if user not in USERS: return "Not Found",404
    return render_template("index.html",user=user)

@app.get("/<user>/health")
def health(user):
    if user not in USERS: return jsonify(error="not found"),404
    return jsonify(ok=True,user=user,time=int(time.time()))

@app.get("/<user>/api/data")
def get_data(user):
    if user not in USERS: return jsonify(error="not found"),404
    if not authorized(): return jsonify(error="unauthorized"),401
    with lock: data=read_data(user)
    return jsonify(data=data,user=user)

@app.post("/<user>/api/data")
def save_data(user):
    if user not in USERS: return jsonify(error="not found"),404
    if not authorized(): return jsonify(error="unauthorized"),401
    body=request.get_json(silent=True) or {}
    if not isinstance(body.get("data"),dict): return jsonify(error="invalid data"),400
    with lock: write_data(user,body["data"])
    return jsonify(ok=True,user=user,saved_at=int(time.time()))

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
