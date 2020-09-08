import flask
from flask import request, jsonify

app = flask.Flask(__name__)
app.config['DEBUG'] = True

@app.route('/', methods=['GET'])
def home():
    op = request.args.get('op', 'no op value provided')
    ref = request.args.get('ref', 'no ref value provided')
    i = request.args.get('i', 'no i value provided')


    return ("<h1>Audit Engine Compute Service</h1>"
        f"<p>op = {op}</p>"
        f"<p>ref = {ref}</p>"
        f"<p>i = {i}</p>")
    
    
app.run()
