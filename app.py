from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'oliveland-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///oliveland.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models
class Listener(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    country = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Routes
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
    return jsonify(session.get('user'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)