#!/usr/bin/env python3
"""CourseForge — Cloud Run + Firestore Backend"""
from flask import Flask, jsonify, request, send_from_directory
from google.cloud import firestore
import os, socket

BASE = os.path.dirname(os.path.abspath(__file__))
app  = Flask(__name__)

# Initialize Firestore Client (Google automatically detects credentials on Cloud Run)
db = firestore.Client()

# ── Static files ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(BASE, 'index.html')

# ── Load all data ─────────────────────────────────────────────────────────────
@app.route('/api/data')
def get_data():
    try:
        # Load Settings
        settings_ref = db.collection('settings').stream()
        settings = {doc.id: doc.to_dict().get('value') for doc in settings_ref}
        
        # Load Courses, Units, and Assignments
        courses = []
        # Fix: Convert stream to list immediately to prevent nested gRPC deadlock
        courses_docs = list(db.collection('courses').order_by('sort_ord').stream())
        
        for c_doc in courses_docs:
            c = c_doc.to_dict()
            c['id'] = c_doc.id
            c['units'] = []
            
            # Fix: Convert stream to list immediately
            units_docs = list(db.collection('units').where('course_id', '==', c_doc.id).order_by('sort_ord').stream())
            for u_doc in units_docs:
                u = u_doc.to_dict()
                u['id'] = u_doc.id
                
                # Fix: Convert stream to list immediately
                assignments_docs = list(db.collection('assignments').where('unit_id', '==', u_doc.id).order_by('sort_ord').stream())
                u['assignments'] = []
                for a_doc in assignments_docs:
                    a = a_doc.to_dict()
                    a['id'] = a_doc.id
                    u['assignments'].append(a)
                    
                c['units'].append(u)
            courses.append(c)
            
        return jsonify(settings=settings, courses=courses)
    except Exception as e:
        return jsonify(error=str(e)), 500

# ── Settings ──────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json or {}
    for k, v in data.items():
        db.collection('settings').document(k).set({'value': str(v)})
    return jsonify(ok=True)

# ── Courses ───────────────────────────────────────────────────────────────────
@app.route('/api/courses', methods=['POST'])
def create_course():
    d = request.json
    # Basic auto-increment logic for sorting
    existing = db.collection('courses').stream()
    n = len(list(existing)) + 1
    
    db.collection('courses').document(d['id']).set({
        'name': d['name'],
        'emoji': d.get('emoji', '📓'),
        'color': d.get('color', '#E0FAF0'),
        'accent': d.get('accent', '#10B981'),
        'grade': 0,
        'complete': 0,
        'sort_ord': n
    })
    return jsonify(ok=True)

@app.route('/api/courses/reorder', methods=['POST'])
def reorder_courses():
    for i, cid in enumerate(request.json.get('ids', [])):
        db.collection('courses').document(cid).update({'sort_ord': i})
    return jsonify(ok=True)

@app.route('/api/courses/<cid>', methods=['PUT'])
def update_course(cid):
    d = request.json or {}
    if d:
        db.collection('courses').document(cid).update(d)
    return jsonify(ok=True)

@app.route('/api/courses/<cid>', methods=['DELETE'])
def delete_course(cid):
    # Fix: Convert stream to list immediately to prevent deletion deadlocks
    units = list(db.collection('units').where('course_id', '==', cid).stream())
    for u in units:
        assignments = list(db.collection('assignments').where('unit_id', '==', u.id).stream())
        for a in assignments:
            db.collection('assignments').document(a.id).delete()
        db.collection('units').document(u.id).delete()
        
    db.collection('courses').document(cid).delete()
    return jsonify(ok=True)

# ── Units ─────────────────────────────────────────────────────────────────────
@app.route('/api/units', methods=['POST'])
def create_unit():
    d = request.json
    existing = db.collection('units').where('course_id', '==', d['course_id']).stream()
    n = len(list(existing)) + 1
    
    db.collection('units').document(d['id']).set({
        'course_id': d['course_id'],
        'name': d['name'],
        'complete': 0,
        'sort_ord': n
    })
    return jsonify(ok=True)

@app.route('/api/units/reorder', methods=['POST'])
def reorder_units():
    for i, uid in enumerate(request.json.get('ids', [])):
        db.collection('units').document(uid).update({'sort_ord': i})
    return jsonify(ok=True)

@app.route('/api/units/<uid>', methods=['PUT'])
def update_unit(uid):
    d = request.json or {}
    if d:
        db.collection('units').document(uid).update(d)
    return jsonify(ok=True)

@app.route('/api/units/<uid>', methods=['DELETE'])
def delete_unit(uid):
    assignments = list(db.collection('assignments').where('unit_id', '==', uid).stream())
    for a in assignments:
        db.collection('assignments').document(a.id).delete()
    db.collection('units').document(uid).delete()
    return jsonify(ok=True)

# ── Assignments ───────────────────────────────────────────────────────────────
@app.route('/api/assignments', methods=['POST'])
def create_assignment():
    d = request.json
    existing = db.collection('assignments').where('unit_id', '==', d['unit_id']).stream()
    n = len(list(existing)) + 1
    
    db.collection('assignments').document(d['id']).set({
        'unit_id': d['unit_id'],
        'name': d['name'],
        'due': d.get('due', ''),
        'status': d.get('status', 'upcoming'),
        'category': d.get('category', 'Homework'),
        'earned': d.get('earned', 0),
        'total': d.get('total', 10),
        'description': d.get('description', ''),
        'submission_text': '',
        'submission_link': '',
        'sort_ord': n
    })
    return jsonify(ok=True)

@app.route('/api/assignments/reorder', methods=['POST'])
def reorder_assignments():
    for i, aid in enumerate(request.json.get('ids', [])):
        db.collection('assignments').document(aid).update({'sort_ord': i})
    return jsonify(ok=True)

@app.route('/api/assignments/<aid>', methods=['PUT'])
def update_assignment(aid):
    d = request.json or {}
    if d:
        db.collection('assignments').document(aid).update(d)
    return jsonify(ok=True)

@app.route('/api/assignments/<aid>', methods=['DELETE'])
def delete_assignment(aid):
    db.collection('assignments').document(aid).delete()
    return jsonify(ok=True)

# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = '(unknown)'
    print('\n🟢  CourseForge Cloud Version is running!')
    print(f'   Local:   http://localhost:8787')
    print('\nPress Ctrl+C to stop.\n')
    app.run(host='0.0.0.0', port=8787, debug=False)
