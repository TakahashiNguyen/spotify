from datetime import datetime
import sqlite3
import requests
from base64 import b64encode
from flask import Flask, Response, jsonify, render_template, request, redirect
from random import randint
from os import getenv
from dotenv import find_dotenv, load_dotenv
import urllib.parse

load_dotenv(find_dotenv())

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE_URL = "https://api.spotify.com/v1/"
CLIENT_ID = getenv("CLIENT_ID")
CLIENT_SECRET = getenv("CLIENT_SECRET")
HOST_URL = getenv("HOST_URL")
PORT = getenv("PORT")


class User:
    def __init__(self, info) -> None:
        self.fromInfo(info)

    def fromInfo(self, info):
        if "error" in info:
            raise ("invalid input")

        self.acsTk = info["access_token"]
        self.rfsTk = info["refresh_token"]
        self.expat = datetime.now().timestamp() + float(info["expires_in"])

        self.id = requests.get(
            f"https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {self.acsTk}"},
        ).json()["id"]


def get_db_connection():
    conn = sqlite3.connect("cache.sqlite3")
    conn.row_factory = sqlite3.Row
    return conn


conn = get_db_connection()
conn.execute(
    """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT,
            acsTk TEXT,
            rfsTk TEXT,
            expat TEXT
        )
    """
)
conn.commit()
conn.close()


def append(input: User):
    user = find(input.id)
    if user:
        update(input.id, input.acsTk, input.rfsTk, input.expat)
    else:
        insert_query = (
            """INSERT INTO users (id, acsTk, rfsTk, expat) VALUES (?, ?, ?, ?)"""
        )
        conn = get_db_connection()
        conn.execute(insert_query, (input.id, input.acsTk, input.rfsTk, input.expat))
        conn.commit()
        conn.close()


def find(id):
    select_query = """SELECT * FROM users WHERE id = ?"""
    user = get_db_connection().execute(select_query, (id,)).fetchone()

    if user:
        return User(
            {
                "id": user[0],
                "access_token": user[1],
                "refresh_token": user[2],
                "expires_in": user[3],
            }
        )
    else:
        return None


def update(id, acsTk, rfsTk, expat):
    update_query = """UPDATE users SET acsTk = ?, rfsTk = ?, expat = ? WHERE id = ?"""
    conn = get_db_connection()
    conn.execute(update_query, (acsTk, rfsTk, expat, id))
    conn.commit()
    conn.close()


# Define base-64 encoded images
with open("base64/placeholder_scan_code.txt") as f:
    B64_PLACEHOLDER_SCAN_CODE = f.read()
with open("base64/placeholder_image.txt") as f:
    B64_PLACEHOLDER_IMAGE = f.read()
with open("base64/spotify_logo.txt") as f:
    B64_SPOTIFY_LOGO = f.read()


def get_token(id):
    """Get a new access token"""
    user: User = find(id)
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": user.rfsTk,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    try:
        return r.json()["access_token"]
    except BaseException:
        raise Exception(r.json())


def spotify_request(endpoint, id):
    """Make a request to the specified endpoint"""
    r = requests.get(
        f"https://api.spotify.com/v1/{endpoint}",
        headers={"Authorization": f"Bearer {get_token(id)}"},
    )
    return {} if r.status_code == 204 else r.json()


def generate_bars(bar_count, rainbow):
    """Build the HTML/CSS snippets for the EQ bars to be injected"""
    bars = "".join(["<div class='bar'></div>" for _ in range(bar_count)])
    css = "<style>"
    if rainbow and rainbow != "false" and rainbow != "0":
        css += ".bar-container { animation-duration: 2s; }"
    spectrum = [
        "#ff0000",
        "#ff4000",
        "#ff8000",
        "#ffbf00",
        "#ffff00",
        "#bfff00",
        "#80ff00",
        "#40ff00",
        "#00ff00",
        "#00ff40",
        "#00ff80",
        "#00ffbf",
        "#00ffff",
        "#00bfff",
        "#0080ff",
        "#0040ff",
        "#0000ff",
        "#4000ff",
        "#8000ff",
        "#bf00ff",
        "#ff00ff",
    ]
    for i in range(bar_count):
        css += f""".bar:nth-child({i + 1}) {{
                animation-duration: {randint(500, 750)}ms;
                background: {spectrum[i] if rainbow and rainbow != 'false' and rainbow != '0' else '#24D255'};
            }}"""
    return f"{bars}{css}</style>"


def load_image_base64(url):
    """Get the base-64 encoded image from url"""
    resposne = requests.get(url)
    return b64encode(resposne.content).decode("ascii")


def get_scan_code(spotify_uri):
    """Get the track code for a song"""
    return load_image_base64(
        f"https://scannables.scdn.co/uri/plain/png/000000/white/640/{spotify_uri}"
    )


def make_svg(spin, scan, theme, rainbow, id):
    """Render the HTML template with variables"""
    data = spotify_request("me/player/currently-playing", id)
    if data:
        item = data["item"]
    else:
        item = spotify_request("me/player/recently-played?limit=1", id)["items"][0][
            "track"
        ]

    artists = " & ".join([artist["name"] for artist in item["artists"]])
    # for artist in item["artists"]:
    #     artists_list = #f'{artist["name"]} & '

    if item["album"]["images"] == []:
        image = B64_PLACEHOLDER_IMAGE
    else:
        image = load_image_base64(item["album"]["images"][1]["url"])

    if scan and scan != "false" and scan != "0":
        bar_count = 10
        scan_code = get_scan_code(item["uri"])
    else:
        bar_count = 12
        scan_code = None

    return render_template(
        "index.html",
        **{
            "bars": generate_bars(bar_count, rainbow),
            "artist": artists,  # .replace("&", "&amp;"),
            "song": item["name"],  # .replace("&", "&amp;"),
            "image": image,
            "scan_code": scan_code if scan_code != "" else B64_PLACEHOLDER_SCAN_CODE,
            "theme": theme,
            "spin": spin,
            "logo": B64_SPOTIFY_LOGO,
        },
    )


app = Flask(__name__)


@app.route("/", defaults={"path": ""})
@app.route("/api", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    if not "id" in request.args:
        return redirect("/login")

    user: User = find(request.args.get("id"))
    if not user:
        return redirect("/login")
    elif datetime.now().timestamp() > user.expat:
        return redirect(f"/refresh-token?id={user.id}")

    resp = Response(
        make_svg(
            request.args.get("spin"),
            request.args.get("scan"),
            request.args.get("theme"),
            request.args.get("rainbow"),
            request.args.get("id"),
        ),
        mimetype="image/svg+xml",
    )
    resp.headers["Cache-Control"] = "s-maxage=1"
    return resp


@app.route("/login")
def login():
    scope = "user-read-currently-playing user-read-recently-played user-read-private user-read-email"

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": f"{request.url_root}callback",
    }

    return redirect(f"{AUTH_URL}?{urllib.parse.urlencode(params)}")


@app.route("/callback")
def callback():
    if "error" in request.args:
        return jsonify({"error": request.args["error"]})
    elif "code" in request.args:
        req_body = {
            "code": request.args["code"],
            "grant_type": "authorization_code",
            "redirect_uri": f"{request.url_root}callback",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }

        response = requests.post(TOKEN_URL, data=req_body).json()

        try:
            user = User(response)
        except:
            return redirect("https://takahashinguyen.github.io/")

        append(user)

        return redirect(f"/api?id={user.id}")


@app.route("/refresh-token")
def refreshToken():
    user: User = find(request.args["id"])

    req_body = {
        "grant_type": "refresh_token",
        "refresh_token": user.rfsTk,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    user.fromInfo(requests.post(TOKEN_URL, data=req_body).json())
    update(user.id, user.acsTk, user.rfsTk, user.expat)

    return redirect(f"api?id={user.id}")


if __name__ == "__main__":
    app.run(host=HOST_URL, port=PORT)
