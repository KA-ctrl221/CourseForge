#!/usr/bin/env python3
"""CourseForge — local Flask + SQLite backend"""
from flask import Flask, jsonify, request, send_from_directory
import sqlite3, os, socket

BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, 'courseforge.db')
app  = Flask(__name__)

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def rows(cur):
    return [dict(r) for r in cur.fetchall()]

def init_db():
    db = get_conn()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS courses (
            id       TEXT PRIMARY KEY,
            name     TEXT NOT NULL,
            emoji    TEXT DEFAULT "📓",
            color    TEXT DEFAULT "#E0FAF0",
            accent   TEXT DEFAULT "#10B981",
            grade    REAL DEFAULT 0,
            complete REAL DEFAULT 0,
            sort_ord INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS units (
            id        TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            name      TEXT NOT NULL,
            complete  REAL DEFAULT 0,
            sort_ord  INTEGER DEFAULT 0,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id          TEXT PRIMARY KEY,
            unit_id     TEXT NOT NULL,
            name        TEXT NOT NULL,
            due         TEXT DEFAULT "",
            status      TEXT DEFAULT "upcoming",
            category    TEXT DEFAULT "Homework",
            earned      REAL DEFAULT 0,
            total       REAL DEFAULT 10,
            description TEXT DEFAULT "",
            sort_ord    INTEGER DEFAULT 0,
            FOREIGN KEY (unit_id) REFERENCES units(id)
        );
    ''')
    db.commit()
    db.close()

init_db()

def migrate_db():
    db = get_conn()
    for col, defn in [('submission_text', 'TEXT DEFAULT ""'), ('submission_link', 'TEXT DEFAULT ""')]:
        try:
            db.execute(f'ALTER TABLE assignments ADD COLUMN {col} {defn}')
        except Exception:
            pass
    db.commit(); db.close()

migrate_db()

# ── Static files ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(BASE, 'index.html')

# ── Load all data ─────────────────────────────────────────────────────────────
@app.route('/api/data')
def get_data():
    db       = get_conn()
    settings = dict(db.execute('SELECT key, value FROM settings').fetchall())
    courses  = []
    for c in rows(db.execute('SELECT * FROM courses ORDER BY sort_ord, rowid')):
        c['units'] = []
        for u in rows(db.execute(
                'SELECT * FROM units WHERE course_id=? ORDER BY sort_ord, rowid', (c['id'],))):
            u['assignments'] = rows(db.execute(
                'SELECT * FROM assignments WHERE unit_id=? ORDER BY sort_ord, rowid', (u['id'],)))
            c['units'].append(u)
        courses.append(c)
    db.close()
    return jsonify(settings=settings, courses=courses)

# ── Settings ──────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['POST'])
def save_settings():
    db = get_conn()
    for k, v in (request.json or {}).items():
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (k, str(v)))
    db.commit(); db.close()
    return jsonify(ok=True)

# ── Courses ───────────────────────────────────────────────────────────────────
@app.route('/api/courses', methods=['POST'])
def create_course():
    d  = request.json
    db = get_conn()
    n  = (db.execute('SELECT COALESCE(MAX(sort_ord),0) FROM courses').fetchone()[0]) + 1
    db.execute('INSERT INTO courses VALUES (?,?,?,?,?,0,0,?)',
               (d['id'], d['name'], d['emoji'], d['color'], d['accent'], n))
    db.commit(); db.close()
    return jsonify(ok=True)

# NOTE: /reorder must be defined before /<cid> so Werkzeug matches it first
@app.route('/api/courses/reorder', methods=['POST'])
def reorder_courses():
    db = get_conn()
    for i, cid in enumerate(request.json.get('ids', [])):
        db.execute('UPDATE courses SET sort_ord=? WHERE id=?', (i, cid))
    db.commit(); db.close()
    return jsonify(ok=True)

@app.route('/api/courses/<cid>', methods=['PUT'])
def update_course(cid):
    d  = request.json or {}
    db = get_conn()
    if d:
        sets = ', '.join(f'"{k}"=?' for k in d)
        db.execute(f'UPDATE courses SET {sets} WHERE id=?', list(d.values()) + [cid])
        db.commit()
    db.close()
    return jsonify(ok=True)

@app.route('/api/courses/<cid>', methods=['DELETE'])
def delete_course(cid):
    db = get_conn()
    for u in rows(db.execute('SELECT id FROM units WHERE course_id=?', (cid,))):
        db.execute('DELETE FROM assignments WHERE unit_id=?', (u['id'],))
    db.execute('DELETE FROM units WHERE course_id=?', (cid,))
    db.execute('DELETE FROM courses WHERE id=?', (cid,))
    db.commit(); db.close()
    return jsonify(ok=True)

# ── Units ─────────────────────────────────────────────────────────────────────
@app.route('/api/units', methods=['POST'])
def create_unit():
    d  = request.json
    db = get_conn()
    n  = (db.execute('SELECT COALESCE(MAX(sort_ord),0) FROM units WHERE course_id=?',
                     (d['course_id'],)).fetchone()[0]) + 1
    db.execute('INSERT INTO units VALUES (?,?,?,0,?)', (d['id'], d['course_id'], d['name'], n))
    db.commit(); db.close()
    return jsonify(ok=True)

@app.route('/api/units/reorder', methods=['POST'])
def reorder_units():
    db = get_conn()
    for i, uid in enumerate(request.json.get('ids', [])):
        db.execute('UPDATE units SET sort_ord=? WHERE id=?', (i, uid))
    db.commit(); db.close()
    return jsonify(ok=True)

@app.route('/api/units/<uid>', methods=['PUT'])
def update_unit(uid):
    d  = request.json or {}
    db = get_conn()
    if d:
        sets = ', '.join(f'"{k}"=?' for k in d)
        db.execute(f'UPDATE units SET {sets} WHERE id=?', list(d.values()) + [uid])
        db.commit()
    db.close()
    return jsonify(ok=True)

@app.route('/api/units/<uid>', methods=['DELETE'])
def delete_unit(uid):
    db = get_conn()
    db.execute('DELETE FROM assignments WHERE unit_id=?', (uid,))
    db.execute('DELETE FROM units WHERE id=?', (uid,))
    db.commit(); db.close()
    return jsonify(ok=True)

# ── Assignments ───────────────────────────────────────────────────────────────
@app.route('/api/assignments', methods=['POST'])
def create_assignment():
    d  = request.json
    db = get_conn()
    n  = (db.execute('SELECT COALESCE(MAX(sort_ord),0) FROM assignments WHERE unit_id=?',
                     (d['unit_id'],)).fetchone()[0]) + 1
    db.execute('INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?,?,?)', (
        d['id'], d['unit_id'], d['name'], d.get('due', ''),
        d.get('status', 'upcoming'), d.get('category', 'Homework'),
        d.get('earned', 0), d.get('total', 10), d.get('description', ''), n
    ))
    db.commit(); db.close()
    return jsonify(ok=True)

@app.route('/api/assignments/reorder', methods=['POST'])
def reorder_assignments():
    db = get_conn()
    for i, aid in enumerate(request.json.get('ids', [])):
        db.execute('UPDATE assignments SET sort_ord=? WHERE id=?', (i, aid))
    db.commit(); db.close()
    return jsonify(ok=True)

@app.route('/api/assignments/<aid>', methods=['PUT'])
def update_assignment(aid):
    d  = request.json or {}
    db = get_conn()
    if d:
        sets = ', '.join(f'"{k}"=?' for k in d)
        db.execute(f'UPDATE assignments SET {sets} WHERE id=?', list(d.values()) + [aid])
        db.commit()
    db.close()
    return jsonify(ok=True)

@app.route('/api/assignments/<aid>', methods=['DELETE'])
def delete_assignment(aid):
    db = get_conn()
    db.execute('DELETE FROM assignments WHERE id=?', (aid,))
    db.commit(); db.close()
    return jsonify(ok=True)

# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = '(unknown)'
    print('\n🟢  CourseForge is running!')
    print(f'   Local:   http://localhost:8787')
    print(f'   Network: http://{ip}:8787')
    print(f'   Database: {DB}')
    print('\nPress Ctrl+C to stop.\n')
    app.run(host='0.0.0.0', port=8787, debug=False)
