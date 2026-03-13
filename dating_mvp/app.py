import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dating.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("DATING_APP_SECRET_KEY", "dev-change-me")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*")

os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            age INTEGER NOT NULL CHECK(age >= 18),
            gender TEXT NOT NULL,
            looking_for TEXT NOT NULL,
            city TEXT NOT NULL,
            bio TEXT DEFAULT '',
            avatar_url TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )

    # Мягкая миграция для уже существующей БД
    cols = [row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()]
    if "avatar_url" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT DEFAULT ''")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(from_user_id, to_user_id),
            FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    db.commit()
    db.close()


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def json_login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "unauthorized"}), 401
        return view_func(*args, **kwargs)

    return wrapped


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_avatar(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        return ""

    filename = secure_filename(file_storage.filename)
    if not filename or not allowed_file(filename):
        return ""

    ext = filename.rsplit(".", 1)[1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_DIR, new_name)
    file_storage.save(path)
    return url_for("static", filename=f"uploads/{new_name}")


def room_for_users(user_a: int, user_b: int) -> str:
    lo, hi = sorted([user_a, user_b])
    return f"chat_{lo}_{hi}"


def row_to_user_public(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "age": row["age"],
        "gender": row["gender"],
        "looking_for": row["looking_for"],
        "city": row["city"],
        "bio": row["bio"],
        "avatar_url": row["avatar_url"],
    }


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def is_match(user_a: int, user_b: int) -> bool:
    db = get_db()
    row = db.execute(
        """
        SELECT 1
        FROM likes l1
        JOIN likes l2
          ON l1.from_user_id = l2.to_user_id
         AND l1.to_user_id = l2.from_user_id
        WHERE l1.from_user_id = ? AND l1.to_user_id = ?
        LIMIT 1
        """,
        (user_a, user_b),
    ).fetchone()
    return row is not None


@app.route("/")
@login_required
def index():
    me = current_user()
    db = get_db()

    min_age = request.args.get("min_age", type=int)
    max_age = request.args.get("max_age", type=int)
    city = request.args.get("city", default="", type=str).strip().lower()

    query = """
        SELECT u.*,
               EXISTS(
                   SELECT 1 FROM likes l
                   WHERE l.from_user_id = ? AND l.to_user_id = u.id
               ) AS liked_by_me
        FROM users u
        WHERE u.id != ?
          AND u.gender = ?
    """
    params = [me["id"], me["id"], me["looking_for"]]

    if city:
        query += " AND u.city = ?"
        params.append(city)

    if min_age is not None:
        query += " AND u.age >= ?"
        params.append(min_age)

    if max_age is not None:
        query += " AND u.age <= ?"
        params.append(max_age)

    query += " ORDER BY u.created_at DESC LIMIT 100"

    profiles = db.execute(query, params).fetchall()

    my_matches = db.execute(
        """
        SELECT u.id, u.name, u.age, u.city
        FROM users u
        JOIN likes l1 ON l1.to_user_id = u.id AND l1.from_user_id = ?
        JOIN likes l2 ON l2.from_user_id = u.id AND l2.to_user_id = ?
        ORDER BY u.name
        """,
        (me["id"], me["id"]),
    ).fetchall()

    return render_template("index.html", me=me, profiles=profiles, matches=my_matches)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        age = request.form.get("age", type=int)
        gender = request.form.get("gender", "").strip().lower()
        looking_for = request.form.get("looking_for", "").strip().lower()
        city = request.form.get("city", "").strip().lower()
        bio = request.form.get("bio", "").strip()
        avatar_url = save_avatar(request.files.get("avatar"))

        if not all([email, password, name, age, gender, looking_for, city]):
            flash("Заполните все обязательные поля", "error")
            return render_template("register.html")

        if age < 18:
            flash("Только 18+", "error")
            return render_template("register.html")

        db = get_db()
        try:
            db.execute(
                """
                INSERT INTO users (email, password_hash, name, age, gender, looking_for, city, bio, avatar_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email,
                    generate_password_hash(password),
                    name,
                    age,
                    gender,
                    looking_for,
                    city,
                    bio,
                    avatar_url,
                    datetime.utcnow().isoformat(),
                ),
            )
            db.commit()
            flash("Профиль создан, теперь войдите", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Пользователь с таким email уже существует", "error")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Неверные email или пароль", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        flash("Вы вошли в систему", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы", "success")
    return redirect(url_for("login"))


@app.route("/like/<int:user_id>", methods=["POST"])
@login_required
def like_user(user_id: int):
    me = current_user()

    if me["id"] == user_id:
        flash("Нельзя лайкнуть самого себя", "error")
        return redirect(url_for("index"))

    db = get_db()
    target = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        flash("Пользователь не найден", "error")
        return redirect(url_for("index"))

    db.execute(
        """
        INSERT OR IGNORE INTO likes (from_user_id, to_user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (me["id"], user_id, datetime.utcnow().isoformat()),
    )
    db.commit()

    if is_match(me["id"], user_id):
        flash("Есть мэтч! Теперь можно писать в чат 🎉", "success")
    else:
        flash("Лайк отправлен", "success")

    return redirect(url_for("index"))


@app.route("/upload-avatar", methods=["POST"])
@login_required
def upload_avatar():
    me = current_user()
    avatar_url = save_avatar(request.files.get("avatar"))
    if not avatar_url:
        flash("Не удалось загрузить аватар (поддерживаются png/jpg/jpeg/webp/gif)", "error")
        return redirect(url_for("index"))

    db = get_db()
    db.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (avatar_url, me["id"]))
    db.commit()
    flash("Аватар обновлён", "success")
    return redirect(url_for("index"))


@app.route("/matches")
@login_required
def matches():
    me = current_user()
    db = get_db()

    rows = db.execute(
        """
        SELECT u.id, u.name, u.age, u.city, u.bio, u.avatar_url
        FROM users u
        JOIN likes l1 ON l1.to_user_id = u.id AND l1.from_user_id = ?
        JOIN likes l2 ON l2.from_user_id = u.id AND l2.to_user_id = ?
        ORDER BY u.name
        """,
        (me["id"], me["id"]),
    ).fetchall()

    return render_template("matches.html", matches=rows)


@app.route("/chat/<int:other_user_id>", methods=["GET", "POST"])
@login_required
def chat(other_user_id: int):
    me = current_user()
    db = get_db()

    other = db.execute(
        "SELECT id, name FROM users WHERE id = ?", (other_user_id,)
    ).fetchone()
    if not other:
        flash("Собеседник не найден", "error")
        return redirect(url_for("matches"))

    if not is_match(me["id"], other_user_id):
        flash("Чат доступен только после взаимного лайка", "error")
        return redirect(url_for("matches"))

    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if body:
            db.execute(
                """
                INSERT INTO messages (from_user_id, to_user_id, body, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (me["id"], other_user_id, body, datetime.utcnow().isoformat()),
            )
            db.commit()
            return redirect(url_for("chat", other_user_id=other_user_id))

    messages = db.execute(
        """
        SELECT m.*, u.name AS author_name
        FROM messages m
        JOIN users u ON u.id = m.from_user_id
        WHERE (m.from_user_id = ? AND m.to_user_id = ?)
           OR (m.from_user_id = ? AND m.to_user_id = ?)
        ORDER BY m.created_at ASC
        """,
        (me["id"], other_user_id, other_user_id, me["id"]),
    ).fetchall()

    return render_template("chat.html", other=other, messages=messages, me=me)


@app.route("/integrations/mamba")
@login_required
def mamba_integration_notice():
    return render_template("mamba_notice.html")


@app.route("/api/me", methods=["GET"])
@json_login_required
def api_me():
    me = current_user()
    return jsonify(row_to_user_public(me))


@app.route("/api/profiles", methods=["GET"])
@json_login_required
def api_profiles():
    me = current_user()
    db = get_db()

    min_age = request.args.get("min_age", type=int)
    max_age = request.args.get("max_age", type=int)
    city = request.args.get("city", default="", type=str).strip().lower()

    query = """
        SELECT u.*,
               EXISTS(
                   SELECT 1 FROM likes l
                   WHERE l.from_user_id = ? AND l.to_user_id = u.id
               ) AS liked_by_me
        FROM users u
        WHERE u.id != ?
          AND u.gender = ?
    """
    params = [me["id"], me["id"], me["looking_for"]]

    if city:
        query += " AND u.city = ?"
        params.append(city)
    if min_age is not None:
        query += " AND u.age >= ?"
        params.append(min_age)
    if max_age is not None:
        query += " AND u.age <= ?"
        params.append(max_age)

    query += " ORDER BY u.created_at DESC LIMIT 100"
    rows = db.execute(query, params).fetchall()

    data = []
    for row in rows:
        item = row_to_user_public(row)
        item["liked_by_me"] = bool(row["liked_by_me"])
        data.append(item)
    return jsonify(data)


@app.route("/api/like/<int:user_id>", methods=["POST"])
@json_login_required
def api_like(user_id: int):
    me = current_user()
    if me["id"] == user_id:
        return jsonify({"error": "cannot_like_self"}), 400

    db = get_db()
    target = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "not_found"}), 404

    db.execute(
        """
        INSERT OR IGNORE INTO likes (from_user_id, to_user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (me["id"], user_id, datetime.utcnow().isoformat()),
    )
    db.commit()

    return jsonify({"ok": True, "match": is_match(me["id"], user_id)})


@app.route("/api/matches", methods=["GET"])
@json_login_required
def api_matches():
    me = current_user()
    db = get_db()

    rows = db.execute(
        """
        SELECT u.id, u.name, u.age, u.city, u.bio, u.avatar_url
        FROM users u
        JOIN likes l1 ON l1.to_user_id = u.id AND l1.from_user_id = ?
        JOIN likes l2 ON l2.from_user_id = u.id AND l2.to_user_id = ?
        ORDER BY u.name
        """,
        (me["id"], me["id"]),
    ).fetchall()

    return jsonify([dict(r) for r in rows])


@app.route("/api/messages/<int:other_user_id>", methods=["GET", "POST"])
@json_login_required
def api_messages(other_user_id: int):
    me = current_user()
    db = get_db()

    if not is_match(me["id"], other_user_id):
        return jsonify({"error": "match_required"}), 403

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        body = str(payload.get("body", "")).strip()
        if not body:
            return jsonify({"error": "empty_message"}), 400

        now = datetime.utcnow().isoformat()
        db.execute(
            """
            INSERT INTO messages (from_user_id, to_user_id, body, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (me["id"], other_user_id, body, now),
        )
        db.commit()

        msg = {
            "from_user_id": me["id"],
            "to_user_id": other_user_id,
            "body": body,
            "created_at": now,
        }
        socketio.emit("new_message", msg, room=room_for_users(me["id"], other_user_id))
        return jsonify({"ok": True, "message": msg}), 201

    rows = db.execute(
        """
        SELECT m.*, u.name AS author_name
        FROM messages m
        JOIN users u ON u.id = m.from_user_id
        WHERE (m.from_user_id = ? AND m.to_user_id = ?)
           OR (m.from_user_id = ? AND m.to_user_id = ?)
        ORDER BY m.created_at ASC
        """,
        (me["id"], other_user_id, other_user_id, me["id"]),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@socketio.on("join_chat")
def socket_join_chat(data):
    me = current_user()
    if me is None:
        emit("error_message", {"error": "unauthorized"})
        return

    try:
        other_user_id = int((data or {}).get("other_user_id"))
    except (TypeError, ValueError):
        emit("error_message", {"error": "invalid_other_user_id"})
        return

    if not is_match(me["id"], other_user_id):
        emit("error_message", {"error": "match_required"})
        return

    room = room_for_users(me["id"], other_user_id)
    join_room(room)
    emit("joined", {"room": room})


@socketio.on("send_chat")
def socket_send_chat(data):
    me = current_user()
    if me is None:
        emit("error_message", {"error": "unauthorized"})
        return

    try:
        other_user_id = int((data or {}).get("other_user_id"))
    except (TypeError, ValueError):
        emit("error_message", {"error": "invalid_other_user_id"})
        return

    body = str((data or {}).get("body", "")).strip()
    if not body:
        emit("error_message", {"error": "empty_message"})
        return

    if not is_match(me["id"], other_user_id):
        emit("error_message", {"error": "match_required"})
        return

    db = get_db()
    now = datetime.utcnow().isoformat()
    db.execute(
        """
        INSERT INTO messages (from_user_id, to_user_id, body, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (me["id"], other_user_id, body, now),
    )
    db.commit()

    msg = {
        "from_user_id": me["id"],
        "to_user_id": other_user_id,
        "author_name": me["name"],
        "body": body,
        "created_at": now,
    }
    socketio.emit("new_message", msg, room=room_for_users(me["id"], other_user_id))


if __name__ == "__main__":
    init_db()
    socketio.run(app, debug=True)
