from flask import Flask, jsonify, render_template, request, redirect
from pathlib import Path
from datetime import datetime
import copy, json, os, tempfile, threading, time

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
INITIAL_DIR = BASE_DIR / "initial_data"
APP_PASSWORD = os.environ.get("APP_PASSWORD", "1234")
USERS = {"yeop", "yeom", "yeong"}
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
    return (not APP_PASSWORD) or request.headers.get("Authorization", "") == f"Bearer {APP_PASSWORD}" or request.headers.get("X-SANDSU-PASSWORD", "") == APP_PASSWORD


def data_file(user):
    return DATA_DIR / f"{user}.json"


def blank_raw():
    return {
        "version": 0,
        "updated_at": "",
        "activeClassId": "",
        "selectedBookId": "",
        "classes": [],
        "books": [],
        "attendance": {},
        "pdfMemory": {},
        "monthlyExams": {},
        "monthlyMessages": {},
        "checkbusTeacherName": "",
        "quickMemoPad": "",
        "examPlanner": {},
        "attendanceRanges": [],
        "examSchedules": {},
        "lastGradePromotionYear": "",
        "todos": [],
        "studentMemos": [],
        "classMemos": {},
        "studentQuickMemos": {},
        "__viewState": {},
    }


def initial_raw(user):
    p = INITIAL_DIR / f"{user}.json"
    if not p.exists():
        return blank_raw()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else blank_raw()
    except Exception:
        return blank_raw()


def is_raw_format(data):
    return isinstance(data, dict) and isinstance(data.get("classes"), list) and (
        "attendance" in data or "monthlyMessages" in data or "studentMemos" in data
    )


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="academy_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ensure_user_data(user):
    p = data_file(user)
    if not p.exists():
        atomic_write(p, initial_raw(user))
        return p
    try:
        current = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        atomic_write(p, initial_raw(user))
        return p
    # v6 이전의 화면 전용 변환 데이터가 남아 있으면 원본 공용 구조로 자동 복구한다.
    if not is_raw_format(current):
        seed = initial_raw(user)
        if is_raw_format(seed):
            atomic_write(p, seed)
    return p


def read_raw(user):
    p = ensure_user_data(user)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else initial_raw(user)
    except Exception:
        return initial_raw(user)


def next_metadata(data, current=None):
    current_version = int((current or {}).get("version") or 0)
    incoming_version = int(data.get("version") or 0)
    data["version"] = max(current_version, incoming_version) + 1
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return data


def write_raw(user, data, bump=True):
    payload = copy.deepcopy(data) if isinstance(data, dict) else blank_raw()
    current = read_raw(user) if bump else None
    if bump:
        next_metadata(payload, current)
    atomic_write(data_file(user), payload)
    return payload


def active_classes(raw):
    result = []
    for c in raw.get("classes") or []:
        if not isinstance(c, dict):
            continue
        nc = {"id": c.get("id", ""), "name": c.get("name", ""), "students": []}
        for s in c.get("students") or []:
            if not isinstance(s, dict) or s.get("deletedAt"):
                continue
            nc["students"].append({"id": s.get("id", ""), "name": s.get("name", "")})
        result.append(nc)
    return result


def checked_text(value):
    checked = value.get("checkedAt")
    if not checked:
        return ""
    try:
        dt = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        text = str(checked)
        return text[11:16] if len(text) >= 16 else "출석"


def raw_to_view(raw):
    classes = active_classes(raw)
    student_class = {}
    valid_students = set()
    for c in classes:
        for s in c["students"]:
            student_class[s["id"]] = c["id"]
            valid_students.add(s["id"])

    records = {}

    def record(student_id, month_key):
        key = f"{student_id}_{month_key}"
        if key not in records:
            records[key] = {"attendance": {}, "memos": [], "progress": "", "score": "", "comments": ["", "", "", "", ""], "message": "", "status": ""}
        return records[key]

    for date_key, class_map in (raw.get("attendance") or {}).items():
        if not isinstance(date_key, str) or len(date_key) < 10 or not isinstance(class_map, dict):
            continue
        month_key, day = date_key[:7], str(int(date_key[8:10]))
        for class_id, student_map in class_map.items():
            if not isinstance(student_map, dict):
                continue
            for student_id, value in student_map.items():
                if student_id not in valid_students or not isinstance(value, dict):
                    continue
                record(student_id, month_key)["attendance"][day] = {
                    "text": checked_text(value),
                    "absent": bool(value.get("absent")),
                    "homework": bool(value.get("homeworkMissing")),
                    "off": bool(value.get("off")),
                }

    for memo in raw.get("studentMemos") or []:
        if not isinstance(memo, dict):
            continue
        student_id = memo.get("studentId")
        date = str(memo.get("date") or "")
        if student_id not in valid_students or len(date) < 7:
            continue
        month_key = date[:7]
        try:
            short_date = f"{int(date[5:7])}/{int(date[8:10])}"
        except Exception:
            short_date = date
        record(student_id, month_key)["memos"].append({
            "id": memo.get("id", ""), "date": short_date,
            "text": memo.get("content", ""), "pinned": bool(memo.get("pinned")),
        })

    for class_id, student_map in (raw.get("monthlyMessages") or {}).items():
        if not isinstance(student_map, dict):
            continue
        for student_id, month_map in student_map.items():
            if student_id not in valid_students or not isinstance(month_map, dict):
                continue
            for month_key, value in month_map.items():
                if not isinstance(value, dict):
                    continue
                r = record(student_id, month_key)
                r["progress"] = value.get("progress", "")
                comments = value.get("comments") or []
                r["comments"] = (list(comments) + ["", "", "", "", ""])[:5]
                r["message"] = value.get("message", "")
                status = value.get("messageStatus", "")
                if value.get("sentDone"):
                    status = "sent"
                r["status"] = status

    todos = []
    for t in raw.get("todos") or []:
        if not isinstance(t, dict):
            continue
        todos.append({
            "id": t.get("id", ""), "text": t.get("content", ""),
            "date": t.get("dueDate", ""), "done": bool(t.get("completed")),
            "createdAt": t.get("createdAt", ""),
        })

    return {
        "classes": classes,
        "records": records,
        "todos": todos,
        "pad": raw.get("quickMemoPad", ""),
        "activeClassId": raw.get("activeClassId", ""),
        "version": int(raw.get("version") or 0),
        "updated_at": raw.get("updated_at", ""),
    }


def parse_record_key(key):
    if not isinstance(key, str) or len(key) < 9:
        return None, None
    pos = key.rfind("_")
    student_id, month_key = key[:pos], key[pos + 1:]
    if len(month_key) != 7 or month_key[4] != "-":
        return None, None
    return student_id, month_key


def iso_now():
    return datetime.now().isoformat(timespec="milliseconds")


def merge_view_into_raw(raw, view):
    """Replace every online-editable dataset with the state sent by the UI.

    The previous implementation merged individual entries. That preserved items
    omitted by the client and therefore could resurrect deletions. This function
    treats the UI payload as the complete current state for active students while
    preserving fields and records that are outside the online student's scope.
    """
    merged = copy.deepcopy(raw)
    classes = merged.get("classes") or []
    student_class = {}
    active_student_ids = set()
    for c in classes:
        if not isinstance(c, dict):
            continue
        class_id = c.get("id")
        for student in c.get("students") or []:
            if not isinstance(student, dict):
                continue
            student_id = student.get("id")
            if not student_id:
                continue
            student_class[student_id] = class_id
            if not student.get("deletedAt"):
                active_student_ids.add(student_id)

    records = view.get("records") or {}
    if not isinstance(records, dict):
        records = {}

    # 1) Monthly progress/comments/message/status.
    # Clear all online-managed fields for active students first, then write the
    # complete state received from the UI. Unknown local-only fields are kept.
    monthly = merged.setdefault("monthlyMessages", {})
    for class_id, student_map in list(monthly.items()):
        if not isinstance(student_map, dict):
            continue
        for student_id, month_map in list(student_map.items()):
            if student_id not in active_student_ids or not isinstance(month_map, dict):
                continue
            for month_key, target in list(month_map.items()):
                if not isinstance(target, dict):
                    continue
                target["progress"] = ""
                target["comments"] = ["", "", "", "", ""]
                target["message"] = ""
                target["messageStatus"] = ""
                target["sentDone"] = False

    for key, record_value in records.items():
        student_id, month_key = parse_record_key(key)
        class_id = student_class.get(student_id)
        if student_id not in active_student_ids or not class_id or not isinstance(record_value, dict):
            continue
        target = monthly.setdefault(class_id, {}).setdefault(student_id, {}).setdefault(month_key, {})
        target["progress"] = record_value.get("progress", "")
        target["comments"] = (list(record_value.get("comments") or []) + ["", "", "", "", ""])[:5]
        target["message"] = record_value.get("message", "")
        status = record_value.get("status", "")
        target["messageStatus"] = status
        target["sentDone"] = status == "sent"

    # 2) Student memos. Replace the complete memo set for active students.
    # Memos belonging to withdrawn/unknown students remain untouched.
    preserved_memos = []
    for memo in merged.get("studentMemos") or []:
        if isinstance(memo, dict) and memo.get("studentId") not in active_student_ids:
            preserved_memos.append(memo)

    replacement_memos = []
    for key, record_value in records.items():
        student_id, month_key = parse_record_key(key)
        class_id = student_class.get(student_id)
        if student_id not in active_student_ids or not class_id or not isinstance(record_value, dict):
            continue
        for index, memo in enumerate(record_value.get("memos") or []):
            if not isinstance(memo, dict):
                continue
            short_date = str(memo.get("date") or "")
            try:
                month_number, day_number = [int(x) for x in short_date.split("/")[:2]]
                date_value = f"{month_key[:4]}-{month_number:02d}-{day_number:02d}"
            except Exception:
                date_value = f"{month_key}-01"
            replacement_memos.append({
                "id": memo.get("id") or f"memo_online_{student_id}_{month_key}_{index}_{int(time.time()*1000)}",
                "classId": class_id,
                "studentId": student_id,
                "date": date_value,
                "createdAt": memo.get("createdAt") or iso_now(),
                "pinned": bool(memo.get("pinned")),
                "content": memo.get("text", ""),
            })
    merged["studentMemos"] = preserved_memos + replacement_memos

    # 3) Attendance. Remove every active student's current attendance state,
    # then rebuild it from the UI payload. This makes unchecked/deleted dates
    # disappear instead of being kept by a merge.
    attendance = merged.setdefault("attendance", {})
    for date_key, class_map in list(attendance.items()):
        if not isinstance(class_map, dict):
            continue
        for class_id, student_map in list(class_map.items()):
            if not isinstance(student_map, dict):
                continue
            for student_id in list(student_map.keys()):
                if student_id in active_student_ids:
                    del student_map[student_id]
            if not student_map:
                del class_map[class_id]
        if not class_map:
            del attendance[date_key]

    for key, record_value in records.items():
        student_id, month_key = parse_record_key(key)
        class_id = student_class.get(student_id)
        if student_id not in active_student_ids or not class_id or not isinstance(record_value, dict):
            continue
        for day_text, attendance_value in (record_value.get("attendance") or {}).items():
            if not isinstance(attendance_value, dict):
                continue
            try:
                date_key = f"{month_key}-{int(day_text):02d}"
            except Exception:
                continue
            text = str(attendance_value.get("text") or "").strip()
            item = {
                "absent": bool(attendance_value.get("absent")),
                "homeworkMissing": bool(attendance_value.get("homework")),
                "off": bool(attendance_value.get("off")),
                "lateAcknowledged": False,
            }
            if item["absent"]:
                item["checkedAt"] = None
            elif text:
                hhmm = text if len(text) == 5 and text[2] == ":" else "00:00"
                item["checkedAt"] = f"{date_key}T{hhmm}:00"
            else:
                item["checkedAt"] = None
            attendance.setdefault(date_key, {}).setdefault(class_id, {})[student_id] = item

    # 4) Todos and free memo are complete replacement datasets.
    merged["todos"] = [{
        "id": todo.get("id") or f"todo_online_{index}_{int(time.time()*1000)}",
        "content": todo.get("text", ""),
        "dueDate": todo.get("date", ""),
        "completed": bool(todo.get("done")),
        "createdAt": todo.get("createdAt") or iso_now(),
    } for index, todo in enumerate(view.get("todos") or []) if isinstance(todo, dict)]
    merged["quickMemoPad"] = view.get("pad", "")

    if view.get("activeClassId"):
        merged["activeClassId"] = view["activeClassId"]
    return merged


@app.get("/")
def root():
    return redirect("/yeop")


@app.get("/<user>")
def index(user):
    if user not in USERS:
        return "Not Found", 404
    return render_template("index.html", user=user)


@app.get("/<user>/health")
def health(user):
    if user not in USERS:
        return jsonify(error="not found"), 404
    raw = read_raw(user)
    classes = active_classes(raw)
    students = sum(len(c["students"]) for c in classes)
    return jsonify(ok=True, user=user, data_dir=str(DATA_DIR), classes=len(classes), students=students, version=int(raw.get("version") or 0), updated_at=raw.get("updated_at", ""), format="academy_data", time=int(time.time()))


# 현재 온라인 UI 전용 API: 화면 형식으로 읽고, 저장 시 원본 academy_data 구조에 병합한다.
@app.get("/<user>/api/data")
def get_view_data(user):
    if user not in USERS:
        return jsonify(error="not found"), 404
    if not authorized():
        return jsonify(error="unauthorized"), 401
    with lock:
        raw = read_raw(user)
        data = raw_to_view(raw)
    return jsonify(
        data=data,
        user=user,
        version=int(raw.get("version") or 0),
        updated_at=raw.get("updated_at", ""),
    )


@app.post("/<user>/api/data")
def save_view_data(user):
    if user not in USERS:
        return jsonify(error="not found"), 404
    if not authorized():
        return jsonify(error="unauthorized"), 401
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("data"), dict):
        return jsonify(error="invalid data"), 400
    with lock:
        current = read_raw(user)
        merged = merge_view_into_raw(current, body["data"])
        saved = write_raw(user, merged, bump=True)
    return jsonify(ok=True, user=user, version=saved.get("version"), updated_at=saved.get("updated_at"), saved_at=int(time.time()))


# 로컬 프로그램과 기존 정상 온라인 버전이 사용하던 공용 원본 API.
@app.get("/api/<user>/load")
def compat_load(user):
    if user not in USERS:
        return jsonify(ok=False, error="not found"), 404
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    with lock:
        data = read_raw(user)
    return jsonify(ok=True, tenant=user, data=data)


@app.post("/api/<user>/save")
def compat_save(user):
    if user not in USERS:
        return jsonify(ok=False, error="not found"), 404
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="invalid data"), 400
    with lock:
        saved = write_raw(user, payload, bump=True)
    return jsonify(ok=True, tenant=user, version=saved.get("version"), updated_at=saved.get("updated_at"))


@app.get("/api/<user>/meta")
def compat_meta(user):
    if user not in USERS:
        return jsonify(ok=False, error="not found"), 404
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    raw = read_raw(user)
    return jsonify(ok=True, meta={"tenant": user, "exists": True, "version": int(raw.get("version") or 0), "updated_at": raw.get("updated_at", "")})


@app.post("/<user>/api/reset")
def reset_data(user):
    if user not in USERS:
        return jsonify(error="not found"), 404
    if not authorized():
        return jsonify(error="unauthorized"), 401
    with lock:
        data = initial_raw(user)
        atomic_write(data_file(user), data)
    classes = active_classes(data)
    students = sum(len(c["students"]) for c in classes)
    return jsonify(ok=True, user=user, classes=len(classes), students=students)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
