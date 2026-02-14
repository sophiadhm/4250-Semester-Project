from flask import Flask, render_template, request, flash, redirect, url_for
import requests

app = Flask(__name__)
app.secret_key = 'key'


URL = ''



if __name__ == '__main__':
    app.run(debug=True)