from flask import Flask, render_template, request, flash, redirect, url_for
import requests

app = Flask(__name__)
app.secret_key = 'key'


URL = 'http://127.0.0.1:8000'




# Home page
@app.route('/')
def index():
    response = requests.get(f'{URL}/assignments/')
    assignments = response.json()
    return render_template('index.html', assignments=assignments)


if __name__ == '__main__':
    app.run(debug=True)