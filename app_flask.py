from flask import Flask, request, jsonify
import subprocess
import tempfile
import os

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <h2>CV Tailor App</h2>
    <p>Paste CV + JD below</p>

    <textarea id="cv" placeholder="CV text" rows="10" cols="50"></textarea><br><br>
    <textarea id="jd" placeholder="Job description" rows="10" cols="50"></textarea><br><br>

    <input id="api" type="password" placeholder="API Key"><br><br>

    <button onclick="run()">Run</button>

    <pre id="output"></pre>

    <script>
    async function run() {
        const res = await fetch("/run", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                cv: document.getElementById("cv").value,
                jd: document.getElementById("jd").value,
                api: document.getElementById("api").value
            })
        });

        const data = await res.json();
        document.getElementById("output").innerText = JSON.stringify(data, null, 2);
    }
    </script>
    """
    

@app.route("/run", methods=["POST"])
def run_app():
    data = request.json

    # For now just test response
    return jsonify({
        "status": "working",
        "cv_length": len(data.get("cv", "")),
        "jd_length": len(data.get("jd", "")),
    })


if __name__ == "__main__":
    app.run()