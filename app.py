from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'oliveland-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///oliveland.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Admin email — only this user can delete chat messages
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'rabe.bar.a74@gmail.com')

# ── Models ──
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

# ── Routes ──
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

# ── Chat ──
@app.route('/chat/messages')
def chat_messages():
    msgs = ChatMessage.query.filter_by(deleted=False).order_by(ChatMessage.created_at.desc()).limit(50).all()
    msgs.reverse()
    return jsonify([{
        'id': m.id,
        'name': m.name,
        'message': m.message,
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

    msg = ChatMessage(
        listener_id=user['id'],
        name=user['name'],
        message=text
    )
    db.session.add(msg)
    db.session.commit()

    emit('new_message', {
        'id': msg.id,
        'name': msg.name,
        'message': msg.message,
        'time': msg.created_at.strftime('%H:%M')
    }, broadcast=True)

@socketio.on('delete_message')
def handle_delete(data):
    user = session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return

    msg_id = data.get('id')
    msg = ChatMessage.query.get(msg_id)
    if msg:
        msg.deleted = True
        db.session.commit()
        emit('message_deleted', {'id': msg_id}, broadcast=True)

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)