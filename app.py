from flask import Flask, jsonify, render_template, request, redirect
from pathlib import Path
import json, os, tempfile, threading, time

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
INITIAL_DIR = BASE_DIR / "initial_data"
APP_PASSWORD = os.environ.get("APP_PASSWORD", "1234")
USERS = {"yeop", "yeom", "yeong"}
YEOP_DATASET_ID = "yeop-academy-20260711-v4"
lock = threading.Lock()

def choose_data_dir():
    candidates = []
    env = os.environ.get("DATA_DIR", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.extend([BASE_DIR / "data", Path("/tmp/sandsu-data")])
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue
    raise RuntimeError("사용 가능한 데이터 저장 경로가 없습니다.")

DATA_DIR = choose_data_dir()

def authorized():
    return (not APP_PASSWORD) or request.headers.get("Authorization", "") == f"Bearer {APP_PASSWORD}"

def data_file(user):
    return DATA_DIR / f"academy_online_{user}.json"

def initial_data(user):
    p = INITIAL_DIR / f"{user}.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"classes": [], "records": {}, "todos": [], "pad": ""}
    if user == "yeop":
        data["__datasetId"] = YEOP_DATASET_ID
        data["__onlineSeedVersion"] = 4
    return data

def looks_valid_yeop(data):
    if not isinstance(data, dict):
        return False
    classes = data.get("classes") or []
    students = sum(len(c.get("students") or []) for c in classes if isinstance(c, dict))
    return data.get("__datasetId") == YEOP_DATASET_ID and len(classes) >= 8 and students >= 50

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="academy_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def ensure_user_data(user):
    p = data_file(user)
    must_seed = not p.exists()
    if p.exists():
        try:
            current = json.loads(p.read_text(encoding="utf-8"))
            must_seed = (not looks_valid_yeop(current)) if user == "yeop" else (not isinstance(current, dict))
        except Exception:
            must_seed = True
    if must_seed:
        atomic_write(p, initial_data(user))
    return p

def read_data(user):
    try:
        p = ensure_user_data(user)
        data = json.loads(p.read_text(encoding="utf-8"))
        if user == "yeop" and not looks_valid_yeop(data):
            data = initial_data(user)
            atomic_write(p, data)
        return data
    except Exception:
        return initial_data(user)

def write_data(user, data):
    if user == "yeop":
        data["__datasetId"] = YEOP_DATASET_ID
        data["__onlineSeedVersion"] = 4
    atomic_write(data_file(user), data)

@app.get("/")
def root(): return redirect("/yeop")

@app.get("/<user>")
def index(user):
    if user not in USERS: return "Not Found", 404
    return render_template("index.html", user=user)

@app.get("/<user>/health")
def health(user):
    if user not in USERS: return jsonify(error="not found"), 404
    data = read_data(user)
    classes = data.get("classes") or []
    students = sum(len(c.get("students") or []) for c in classes)
    return jsonify(ok=True, user=user, data_dir=str(DATA_DIR), classes=len(classes), students=students, dataset=data.get("__datasetId"), time=int(time.time()))

@app.get("/<user>/api/data")
def get_data(user):
    if user not in USERS: return jsonify(error="not found"), 404
    if not authorized(): return jsonify(error="unauthorized"), 401
    with lock: data = read_data(user)
    return jsonify(data=data, user=user)

@app.post("/<user>/api/data")
def save_data(user):
    if user not in USERS: return jsonify(error="not found"), 404
    if not authorized(): return jsonify(error="unauthorized"), 401
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("data"), dict): return jsonify(error="invalid data"), 400
    with lock: write_data(user, body["data"])
    return jsonify(ok=True, user=user, saved_at=int(time.time()))

@app.post("/<user>/api/reset")
def reset_data(user):
    if user not in USERS: return jsonify(error="not found"), 404
    if not authorized(): return jsonify(error="unauthorized"), 401
    with lock:
        data = initial_data(user)
        atomic_write(data_file(user), data)
    classes = data.get("classes") or []
    students = sum(len(c.get("students") or []) for c in classes)
    return jsonify(ok=True, user=user, classes=len(classes), students=students)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
