from flask import Flask, render_template, request, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from app.models import db, User, Assignment
from decorators import admin_required
import requests

app = Flask(__name__)
app.secret_key = 'key'


URL = 'http://127.0.0.1:8000'


# app db configs
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///./users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# sets up db with pip install flask_sqlalchemyapp
db.init_app(app) 
with app.app_context():
    db.create_all()

# set up login manager for aid with...logging in
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'error'


"""
    LOGIN STUFF
"""
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 3 routes -- login, logout, register
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method=="POST":
        username = request.form["username"]
        password = request.form["password"]
        is_admin = request.form.get('is_admin') == 'on' # on means it is checked

        print(username)

        # check if they exist
        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "error")
            return redirect(url_for('register'))
        
        new_user = User(username=username, is_admin = is_admin)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully!", "success")
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username=request.form['username']
        password=request.form['password']

        # does this user exist in the db?
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash("User logged in successfully!", "success")
            return redirect(url_for('seeker_index'))

        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# Home page
@app.route('/')
def index():
    response = requests.get(f'{URL}/assignments/')
    assignments = response.json()
    return render_template('index.html', assignments=assignments)


if __name__ == '__main__':
    app.run(debug=True)