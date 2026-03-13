import sys
import os

# Automatically find the project root (the folder containing both 'app' and 'flask_application')
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Add it to Python's module search path
if project_root not in sys.path:
    sys.path.append(project_root)


from flask import Flask, render_template, request, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from app.models import db, User, Assignment
from flask_application.decorators import admin_required
import requests
from sync import sync_assignments

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
@login_required
def index():
    #response = requests.get(f'{URL}/assignments/')
    #assignments = response.json()
    return render_template('index.html')#, assignments=assignments)

# Calendar page route
@app.route("/calendar/")
@login_required
def about():
    return render_template("calendar.html")


#connect calendar route
@app.route("/connect-calendar/", methods=["GET", "POST"])
@login_required
def connect_calendar():
    ics_url = request.form.get["ics_url"]
    current_user.ics_url = ics_url
    db.session.commit()
    flash("Calendar connected successfully!", "success")
    return redirect(url_for("about"))

#sync stuff
@app.route("/sync/")
@login_required
def sync():
    sync_assignments(current_user)
    flash("Assignments synced successfully!", "success")
    return redirect(url_for("assignment"))


# Assignment page route
@app.route("/assignments/")
@login_required
def assignment():
    assignments = Assignment.queryfilter_by(
        user_id=current_user.id
    ).order_by(Assignment.due_date).all()
    return render_template("assignments.html", assignments=assignments)

if __name__ == '__main__':
    app.run(debug=True)