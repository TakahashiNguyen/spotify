import base64
from datetime import datetime
from io import BytesIO
import sqlite3
from PIL import Image
import requests
from base64 import b64encode
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    redirect,
    session,
)
from random import randint
from os import getenv
from dotenv import find_dotenv, load_dotenv
import urllib.parse
import ngrok
from flask_cors import CORS

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


def generate_bars(
    bar_count,
    rainbow,
    spectrum=["#FF99C8", "#FCF6BD", "#D0F4DE", "#A9DEF9", "#E4C1F9"],
):
    """Build the HTML/CSS snippets for the EQ bars to be injected"""
    bars = "".join(["<div class='bar'></div>" for _ in range(bar_count)])
    css = "<style>"
    if rainbow and rainbow != "false" and rainbow != "0":
        css += ".bar-container { animation-duration: 2s; }"

    for i in range(bar_count):
        css += f""".bar:nth-child({i + 1}) {{
                animation-duration: {randint(500, 750)}ms;
                background: {spectrum[(i,randint(0,99))%len(spectrum)]};
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


def decode_base64_image(base64_string):
    """Decodes a base64 encoded string into a PIL Image object."""
    image_data = base64.b64decode(base64_string)
    image_file = BytesIO(image_data)
    return Image.open(image_file)


def extract_prominent_colors_pillow(base64_string, num_colors=5):
    """Extracts prominent colors using Pillow's quantize method."""
    img = decode_base64_image(base64_string)
    resized_img = img.resize((200, 200))  # Adjust dimensions as needed
    palette_img = resized_img.quantize(num_colors)
    colors = palette_img.getpalette()
    return [
        f"#{colors[i]:02x}{colors[i+1]:02x}{colors[i+2]:02x}"
        for i in range(0, num_colors * 3, 3)
    ]


def make_svg(spin, scan, theme, rainbow, id):
    """Render the HTML template with variables"""
    data = spotify_request("me/player/currently-playing", id)
    if data:
        item = data["item"]
        artists = " & ".join([artist["name"] for artist in item["artists"]])
    else:
        item = {"name": "User offline", "album": {"images": []}}
        artists = ""

    # for artist in item["artists"]:
    #     artists_list = #f'{artist["name"]} & '

    if item["album"]["images"] == []:
        image = B64_PLACEHOLDER_IMAGE
    else:
        image = load_image_base64(item["album"]["images"][1]["url"])

    if scan and scan != "false" and scan != "0" and artists:
        bar_count = 15
        scan_code = get_scan_code(item["uri"])
    else:
        bar_count = 17
        scan_code = None

    return render_template(
        "index.html",
        **{
            "bars": (
                generate_bars(bar_count, True)
                if not artists
                else generate_bars(
                    bar_count, rainbow, extract_prominent_colors_pillow(image, 8)
                )
            ),
            "artist": artists,  # .replace("&", "&amp;"),
            "song": item["name"],  # .replace("&", "&amp;"),
            "image": image,
            "scan_code": scan_code if scan_code != "" else B64_PLACEHOLDER_SCAN_CODE,
            "theme": theme,
            "spin": spin,
        },
    )


app = Flask(__name__)
CORS(app, origins=["takahashinguyen.github.io", "localhost:5173"])
app.secret_key = CLIENT_ID + CLIENT_SECRET


@app.route("/", defaults={"path": ""})
@app.route("/api", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    if not "id" in request.args:
        return redirect("/login")

    if not "prep" in request.args:
        session["spin"] = request.args.get("spin")
        session["scan"] = request.args.get("scan")
        session["theme"] = request.args.get("theme")
        session["rainbow"] = request.args.get("rainbow")

    user: User = find(request.args.get("id"))
    if not user:
        return redirect("/login")
    if datetime.now().timestamp() > user.expat:
        return redirect(f"/refresh-token?id={user.id}")

    resp = Response(
        make_svg(
            session["spin"] if "prep" in request.args else request.args.get("spin"),
            session["scan"] if "prep" in request.args else request.args.get("scan"),
            session["theme"] if "prep" in request.args else request.args.get("theme"),
            (
                session["rainbow"]
                if "prep" in request.args
                else request.args.get("rainbow")
            ),
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

        user.id = requests.get(
            f"https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {user.acsTk}"},
        ).json()["id"]
        append(user)

        return redirect(f"/api?id={user.id}&prep=true")


def refreshUser(user: User):
    req_body = {
        "grant_type": "refresh_token",
        "refresh_token": user.rfsTk,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    user.fromInfo(requests.post(TOKEN_URL, data=req_body).json())
    update(user.id, user.acsTk, user.rfsTk, user.expat)


@app.route("/refresh-token")
def refreshToken():
    user: User = find(request.args["id"])

    refreshUser(user)

    return redirect(f"/api?id={user.id}&prep=true")


if __name__ == "__main__":
    listener = ngrok.forward(
        addr="192.168.1.62:5000",
        authtoken_from_env=True,
        domain="moving-thrush-physically.ngrok-free.app",
    )

    print(f"Ingress established at {listener.url()}")
    app.run(host=HOST_URL, port=PORT)
