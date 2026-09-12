from flask import Flask, render_template
from matcher import get_top_matches

app = Flask(__name__)

@app.route("/")
def home():
    return "Server Running"

@app.route("/results/<int:user_id>")
def results(user_id):
    matches = get_top_matches(user_id)

    formatted = []
    for name, score, reasons in matches:
        formatted.append({
            "name": name,
            "score": score,
            "reasons": reasons
        })

    return render_template("results.html", matches=formatted)


if __name__ == "__main__":
    app.run(debug=True)