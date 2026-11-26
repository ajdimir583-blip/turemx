import os
import sqlite3
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, g
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(APP_DIR, "navigator.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

CATEGORIES = [
    "Археологический памятник", "Музей", "Природный объект",
    "Место отдыха", "Объект бизнеса"
]
SEASONS = ["Круглый год", "Лето", "Зима", "Весна", "Осень"]


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DATABASE)
    # Таблица мест (ваша старая)
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS places
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     name
                     TEXT
                     NOT
                     NULL,
                     category
                     TEXT
                     NOT
                     NULL,
                     description
                     TEXT
                     NOT
                     NULL,
                     address
                     TEXT
                     DEFAULT
                     '',
                     latitude
                     REAL,
                     longitude
                     REAL,
                     photo_url
                     TEXT
                     DEFAULT
                     '',
                     contact
                     TEXT
                     DEFAULT
                     '',
                     price
                     TEXT
                     DEFAULT
                     '',
                     distance_km
                     REAL,
                     family_friendly
                     INTEGER
                     NOT
                     NULL
                     DEFAULT
                     0,
                     season
                     TEXT
                     DEFAULT
                     'Круглый год',
                     website
                     TEXT
                     DEFAULT
                     '',
                     published
                     INTEGER
                     NOT
                     NULL
                     DEFAULT
                     1,
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )
                 """)
    # Таблица админов (ваша старая)
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS admins
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     username
                     TEXT
                     UNIQUE
                     NOT
                     NULL,
                     password_hash
                     TEXT
                     NOT
                     NULL
                 )
                 """)
    # НОВАЯ Таблица обычных пользователей
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS users
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     username
                     TEXT
                     UNIQUE
                     NOT
                     NULL,
                     password_hash
                     TEXT
                     NOT
                     NULL,
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )
                 """)

    admin_user = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "change-me-now")
    exists = conn.execute("SELECT id FROM admins WHERE username=?", (admin_user,)).fetchone()
    if not exists:
        conn.execute("INSERT INTO admins(username,password_hash) VALUES(?,?)",
                     (admin_user, generate_password_hash(admin_password)))

    count = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    if count == 0:
        demo = [
            ("Озеро Абалаах", "Природный объект",
             "Демонстрационная карточка природного объекта. Уточните доступность, состояние подъездных дорог и сведения о лечебных грязях у местных специалистов.",
             "Мегино-Кангаласский улус, координаты требуют проверки", None, None, "", "", "Уточнять", None, 1, "Лето",
             "", 1),
            ("Краеведческий музей (пример)", "Музей",
             "Замените эту запись проверенной информацией о действующем музее: экспозиции, график работы, экскурсии и контакты.",
             "Адрес необходимо уточнить", None, None, "", "", "Уточнять", None, 1, "Круглый год", "", 1),
            ("Историко-археологический объект (пример)", "Археологический памятник",
             "Демонстрационная запись. Не посещайте археологические объекты без проверки режима доступа и рекомендаций местных органов охраны наследия.",
             "Местоположение необходимо уточнить", None, None, "", "", "Уточнять", None, 0, "Лето", "", 1),
        ]
        conn.executemany("""
                         INSERT INTO places(name, category, description, address, latitude, longitude, photo_url,
                                            contact, price, distance_km, family_friendly, season, website, published)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                         """, demo)
    conn.commit()
    conn.close()


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def clean_text(value, limit=2000):
    return (value or "").strip()[:limit]


def parse_float(value):
    if not value or not value.strip():
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


@app.route("/")
def index():
    # ... (код функции index остается без изменений) ...
    query = clean_text(request.args.get("q"), 120)
    category = clean_text(request.args.get("category"), 100)
    season = clean_text(request.args.get("season"), 40)
    family = request.args.get("family", "")
    paid = request.args.get("paid", "")
    max_distance = parse_float(request.args.get("max_distance", ""))
    sql = "SELECT * FROM places WHERE published=1"
    params = []
    if query:
        sql += " AND (name LIKE ? OR description LIKE ? OR address LIKE ?)"
        params += [f"%{query}%"] * 3
    if category in CATEGORIES:
        sql += " AND category=?"
        params.append(category)
    if season in SEASONS:
        sql += " AND (season=? OR season='Круглый год')"
        params.append(season)
    if family == "1":
        sql += " AND family_friendly=1"
    if paid == "free":
        sql += " AND (price LIKE '%бесплат%' OR price='0' OR price='0 ₽')"
    elif paid == "paid":
        sql += " AND price NOT LIKE '%бесплат%' AND price NOT IN ('','0','0 ₽')"
    if max_distance is not None:
        sql += " AND distance_km IS NOT NULL AND distance_km<=?"
        params.append(max_distance)
    sql += " ORDER BY name COLLATE NOCASE"
    places = db().execute(sql, params).fetchall()
    map_places = []
    for p in places:
        if p["latitude"] is not None and p["longitude"] is not None:
            map_places.append(dict(id=p["id"], name=p["name"], category=p["category"],
                                   lat=p["latitude"], lon=p["longitude"]))
    # Передаем в шаблон данные о том, кто вошел (пользователь или админ)
    return render_template("index.html", places=places, map_places=map_places,
                           categories=CATEGORIES, seasons=SEASONS)


@app.route("/place/<int:place_id>")
def place_detail(place_id):
    place = db().execute("SELECT * FROM places WHERE id=? AND published=1", (place_id,)).fetchone()
    if not place:
        abort(404)
    return render_template("detail.html", place=place)


# --- НОВЫЕ МАРШРУТЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ---

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = clean_text(request.form.get("username"), 80)
        password = request.form.get("password", "")

        if not username or len(password) < 4:
            flash("Логин обязателен, а пароль должен быть не короче 4 символов.", "error")
            return redirect(url_for("register"))

        user = db().execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if user:
            flash("Такой логин уже занят. Придумайте другой.", "error")
            return redirect(url_for("register"))

        db().execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     (username, generate_password_hash(password)))
        db().commit()
        flash("Регистрация успешна! Теперь вы можете войти.", "success")
        return redirect(url_for("user_login"))
    return render_template("register.html")


@app.route("/user_login", methods=["GET", "POST"])
def user_login():
    if request.method == "POST":
        username = clean_text(request.form.get("username"), 80)
        password = request.form.get("password", "")

        user = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Вы успешно вошли на сайт!", "success")
            return redirect(url_for("index"))
        else:
            flash("Неверный логин или пароль.", "error")
    return render_template("user_login.html")


@app.route("/user_logout", methods=["POST"])
def user_logout():
    session.pop("user_id", None)
    session.pop("username", None)
    flash("Вы вышли из системы.", "success")
    return redirect(url_for("index"))


# --- МАРШРУТЫ АДМИНИСТРАТОРА (ОСТАЛИСЬ БЕЗ ИЗМЕНЕНИЙ) ---

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = clean_text(request.form.get("username"), 80)
        password = request.form.get("password", "")
        admin = db().execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()  # Очищаем старые сессии пользователя
            session["admin_id"] = admin["id"]
            session["admin_name"] = admin["username"]
            return redirect(request.args.get("next") or url_for("admin"))
        flash("Неверный логин или пароль.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@admin_required
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    places = db().execute("SELECT * FROM places ORDER BY id DESC").fetchall()
    return render_template("admin.html", places=places)


@app.route("/admin/place/new", methods=["GET", "POST"])
@app.route("/admin/place/<int:place_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_place(place_id=None):
    conn = db()
    place = conn.execute("SELECT * FROM places WHERE id=?", (place_id,)).fetchone() if place_id else None
    if place_id and not place:
        abort(404)
    if request.method == "POST":
        name = clean_text(request.form.get("name"), 160)
        category = request.form.get("category", "")
        description = clean_text(request.form.get("description"), 5000)
        if not name or not description or category not in CATEGORIES:
            flash("Заполните название, описание и корректную категорию.", "error")
            return render_template("edit.html", place=place, categories=CATEGORIES, seasons=SEASONS)
        lat = parse_float(request.form.get("latitude"))
        lon = parse_float(request.form.get("longitude"))
        distance = parse_float(request.form.get("distance_km"))
        family = 1 if request.form.get("family_friendly") == "1" else 0
        published = 1 if request.form.get("published") == "1" else 0
        values = (name, category, description, clean_text(request.form.get("address"), 300),
                  lat, lon, clean_text(request.form.get("photo_url"), 1000),
                  clean_text(request.form.get("contact"), 300), clean_text(request.form.get("price"), 100),
                  distance, family,
                  request.form.get("season") if request.form.get("season") in SEASONS else "Круглый год",
                  clean_text(request.form.get("website"), 1000), published)
        if place_id:
            conn.execute("""UPDATE places
                            SET name=?,
                                category=?,
                                description=?,
                                address=?,
                                latitude=?,
                                longitude=?,
                                photo_url=?,
                                contact=?,
                                price=?,
                                distance_km=?,
                                family_friendly=?,
                                season=?,
                                website=?,
                                published=?
                            WHERE id = ?""", values + (place_id,))
        else:
            conn.execute("""INSERT INTO places(name, category, description, address, latitude, longitude, photo_url,
                                               contact, price, distance_km, family_friendly, season, website, published)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values)
        conn.commit()
        flash("Карточка сохранена.", "success")
        return redirect(url_for("admin"))
    return render_template("edit.html", place=place, categories=CATEGORIES, seasons=SEASONS)


@app.route("/admin/place/<int:place_id>/delete", methods=["POST"])
@admin_required
def delete_place(place_id):
    db().execute("DELETE FROM places WHERE id=?", (place_id,))
    db().commit()
    flash("Карточка удалена.", "success")
    return redirect(url_for("admin"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")
