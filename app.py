from flask import Flask, jsonify, render_template, request
from pathlib import Path
import json, os, tempfile, threading, time

app=Flask(__name__)
DATA_DIR=Path(os.environ.get('DATA_DIR','data'))
DATA_FILE=DATA_DIR/'academy_online_data.json'
APP_PASSWORD=os.environ.get('APP_PASSWORD','1234')
lock=threading.Lock()

def authorized():
    if not APP_PASSWORD: return True
    h=request.headers.get('Authorization','')
    return h == f'Bearer {APP_PASSWORD}'

def read_data():
    if not DATA_FILE.exists(): return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}

def write_data(data):
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='academy_',suffix='.json',dir=str(DATA_DIR))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,DATA_FILE)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

@app.get('/')
def index(): return render_template('index.html')

@app.get('/health')
def health(): return jsonify(ok=True,time=int(time.time()))

@app.get('/api/data')
def get_data():
    if not authorized(): return jsonify(error='unauthorized'),401
    with lock: data=read_data()
    return jsonify(data=data)

@app.post('/api/data')
def save_data():
    if not authorized(): return jsonify(error='unauthorized'),401
    body=request.get_json(silent=True) or {}
    if not isinstance(body.get('data'),dict): return jsonify(error='invalid data'),400
    with lock: write_data(body['data'])
    return jsonify(ok=True,saved_at=int(time.time()))

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT','10000')))
