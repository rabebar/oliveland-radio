from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import os
import requests

app = Flask(__name__)
app.config['SECRET_KEY'] = 'oliveland-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///oliveland.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

@app.before_request
def make_session_permanent():
    session.permanent = True

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'rabe.bar.a74@gmail.com')
DAILY_API_KEY = os.environ.get('DAILY_API_KEY', '')

speak_requests = {}
request_counter = 0


class Listener(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    country = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listener_id = db.Column(db.Integer, db.ForeignKey('listener.id'))
    name = db.Column(db.String(100), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    deleted = db.Column(db.Boolean, default=False)


@app.route('/')
def home():
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(x in user_agent for x in ['android', 'iphone', 'ipad', 'mobile'])
    if is_mobile:
        return redirect(url_for('mobile'))
    return render_template('index.html', user=session.get('user'))

@app.route('/mobile')
def mobile():
    return render_template('mobile.html', user=session.get('user'))
@app.route('/sw.js')
def service_worker():
    from flask import send_from_directory
    return send_from_directory('.', 'sw.js')

@app.route('/manifest.json')
def manifest():
    from flask import send_from_directory
    return send_from_directory('.', 'manifest.json')

@app.route('/icon-<size>.png')
def icon(size):
    from flask import send_from_directory
    return send_from_directory('.', f'icon-{size}.png')

@app.route('/admin')
def admin():
    user = session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return "Access denied. Sign in as admin first.", 403
    return render_template('admin.html', user=user)

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    country = data.get('country', '').strip()
    if not name or not email:
        return jsonify({'error': 'Name and email required'}), 400
    existing = Listener.query.filter_by(email=email).first()
    if existing:
        session['user'] = {'id': existing.id, 'name': existing.name, 'email': existing.email}
        return jsonify({'success': True, 'user': session['user']})
    listener = Listener(name=name, email=email, country=country)
    db.session.add(listener)
    db.session.commit()
    session['user'] = {'id': listener.id, 'name': listener.name, 'email': listener.email}
    return jsonify({'success': True, 'user': session['user']})

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({'success': True})

@app.route('/me')
def me():
    user = session.get('user')
    if user:
        user['is_admin'] = (user.get('email') == ADMIN_EMAIL)
    return jsonify(user)


@app.route('/chat/messages')
def chat_messages():
    msgs = ChatMessage.query.filter_by(deleted=False).order_by(ChatMessage.created_at.desc()).limit(50).all()
    msgs.reverse()
    return jsonify([{
        'id': m.id, 'name': m.name, 'message': m.message,
        'time': m.created_at.strftime('%H:%M')
    } for m in msgs])

@socketio.on('send_message')
def handle_message(data):
    user = session.get('user')
    if not user:
        emit('error', {'msg': 'Please sign in to chat'})
        return
    text = (data.get('message') or '').strip()
    if not text or len(text) > 500:
        return
    msg = ChatMessage(listener_id=user['id'], name=user['name'], message=text)
    db.session.add(msg)
    db.session.commit()
    emit('new_message', {
        'id': msg.id, 'name': msg.name, 'message': msg.message,
        'time': msg.created_at.strftime('%H:%M')
    }, broadcast=True)

@socketio.on('delete_message')
def handle_delete(data):
    user = session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return
    msg = ChatMessage.query.get(data.get('id'))
    if msg:
        msg.deleted = True
        db.session.commit()
        emit('message_deleted', {'id': msg.id}, broadcast=True)


def create_daily_room(room_name):
    if not DAILY_API_KEY:
        return None
    headers = {'Authorization': f'Bearer {DAILY_API_KEY}', 'Content-Type': 'application/json'}
    expiry = int((datetime.utcnow() + timedelta(hours=1)).timestamp())
    payload = {
        'name': room_name,
        'properties': {
            'exp': expiry,
            'enable_chat': False,
            'enable_screenshare': False,
            'start_video_off': True,
            'max_participants': 2
        }
    }
    try:
        r = requests.post('https://api.daily.co/v1/rooms', json=payload, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            return r.json().get('url')
        print('Daily.co error:', r.status_code, r.text)
    except Exception as e:
        print('Daily.co exception:', e)
    return None


@socketio.on('request_speak')
def handle_request_speak(data):
    global request_counter
    user = session.get('user')
    if not user:
        emit('speak_error', {'msg': 'Please sign in first'})
        return
    for req in speak_requests.values():
        if req['email'] == user['email'] and req['status'] in ('pending', 'accepted'):
            emit('speak_error', {'msg': 'You already have an active request'})
            return
    request_counter += 1
    rid = request_counter
    speak_requests[rid] = {
        'id': rid,
        'name': user['name'],
        'email': user['email'],
        'listener_id': user['id'],
        'status': 'pending',
        'room_url': None,
        'created_at': datetime.utcnow().strftime('%H:%M')
    }
    emit('speak_request_sent', {'id': rid})
    socketio.emit('new_speak_request', speak_requests[rid])


@socketio.on('get_speak_requests')
def handle_get_requests():
    user = session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return
    pending = [r for r in speak_requests.values() if r['status'] == 'pending']
    emit('speak_requests_list', pending)


@socketio.on('accept_speak')
def handle_accept(data):
    user = session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return
    rid = data.get('id')
    req = speak_requests.get(rid)
    if not req or req['status'] != 'pending':
        return
    room_url = create_daily_room(f'oliveland-speak-{rid}')
    if not room_url:
        emit('speak_error', {'msg': 'Failed to create room'})
        return
    req['status'] = 'accepted'
    req['room_url'] = room_url
    socketio.emit('speak_accepted', {
        'id': rid, 'email': req['email'], 'room_url': room_url
    })
    emit('speak_request_updated', req)


@socketio.on('reject_speak')
def handle_reject(data):
    user = session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return
    rid = data.get('id')
    req = speak_requests.get(rid)
    if not req:
        return
    req['status'] = 'rejected'
    socketio.emit('speak_rejected', {'id': rid, 'email': req['email']})
    emit('speak_request_updated', req)


@socketio.on('end_speak')
def handle_end(data):
    rid = data.get('id')
    req = speak_requests.get(rid)
    if not req:
        return
    req['status'] = 'ended'
    socketio.emit('speak_ended', {'id': rid, 'email': req['email']})


with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)