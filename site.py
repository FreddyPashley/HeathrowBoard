import flask

app = flask.Flask(__name__)

test_data = {str(i): [] for i in range(21)}

@app.route("/")
def index():
    return flask.render_template("index.html", data=test_data)

app.run("0.0.0.0", port=6767)
