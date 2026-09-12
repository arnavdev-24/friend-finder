from flask import Flask, jsonify
from matcher import get_top_matches

app = Flask(__name__)

@app.route("/")
def home():
    return "Server is running"

@app.route("/matches/<int:user_id>")
def matches(user_id):
    results = get_top_matches(user_id)
    formatted=[]
    for name,score,reasons in results:
        formatted.append({
            "name": name,
            "score": score,
            "reasons": reasons
        })
    return jsonify(formatted)


if __name__ == "__main__":
    app.run(debug=True)