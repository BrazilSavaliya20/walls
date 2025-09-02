import os
import json
import logging
from typing import List, Dict, Any, Tuple
from flask import Flask, render_template, request, session, flash, redirect, url_for
from datetime import datetime
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import requests

# ---------------------------------------------------------------------
# Load env
# ---------------------------------------------------------------------
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_DIR = os.path.join(BASE_DIR, "private")
os.makedirs(PRIVATE_DIR, exist_ok=True)

UPLOAD_FOLDER = os.path.join(BASE_DIR, "public", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder="public", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "8141@#Kaswala")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ---------------------------------------------------------------------
# Files & Logging
# ---------------------------------------------------------------------
products_file = os.path.join(PRIVATE_DIR, "products.json")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wallcraft")

# ---------------------------------------------------------------------
# Firestore
# ---------------------------------------------------------------------
def init_firestore():
    firebase_key_json = os.environ.get("FIREBASE_KEY")
    if not firebase_key_json:
        raise Exception("FIREBASE_KEY not set")
    firebase_key_dict = json.loads(firebase_key_json)
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = None
try:
    db = init_firestore()
except Exception as e:
    logger.error(f"Firestore init failed: {e}")

# ---------------------------------------------------------------------
# ImgBB
# ---------------------------------------------------------------------
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "")

def upload_to_imgbb(file):
    try:
        resp = requests.post(
            "https://api.imgbb.com/1/upload",
            params={"key": IMGBB_API_KEY},
            files={"image": (file.filename, file.stream, file.content_type)}
        )
        result = resp.json()
        if result.get("success"):
            return result["data"]["url"]
        else:
            logger.error(f"ImgBB failed: {result}")
            return None
    except Exception as e:
        logger.error(f"ImgBB upload error: {e}")
        return None

# ---------------------------------------------------------------------
# Products helpers
# ---------------------------------------------------------------------
def money_to_int(val: str) -> int:
    if not val:
        return 0
    return int(val.replace("₹", "").replace(",", "").strip() or 0)

def get_price_by_size(product: dict, size: str) -> int:
    key = f"price_{size.lower()}"
    return money_to_int(product.get(key))

def save_products(data: List[Dict[str, Any]]) -> None:
    try:
        with open(products_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Write products failed: {e}")

def load_products() -> List[Dict[str, Any]]:
    if os.path.exists(products_file):
        try:
            return json.load(open(products_file, "r", encoding="utf-8"))
        except Exception as e:
            logger.error(f"Read products failed: {e}")

    # seed default
    seed = [
        {
            "id": 1,
            "imgs": ["product1.jpg"],
            "name": "Golden Glow Panel",
            "desc": "Handcrafted golden-accent Wall Craft panel.",
            "price_small": "₹7,999",
            "price_medium": "₹9,499",
            "price_large": "₹12,999"
        }
    ]
    save_products(seed)
    return seed

def get_cart_items_and_total(cart: Dict[str, Tuple[str, int]], products: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    items = []
    total = 0
    for key, value in cart.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue
        size, qty = value
        product_id = key.rsplit("_", 1)[0]
        product = next((p for p in products if p["id"] == int(product_id)), None)
        if not product:
            continue
        price = get_price_by_size(product, size)
        subtotal = price * qty
        total += subtotal
        items.append({
            "id": product["id"],
            "name": product["name"],
            "img": product["imgs"][0] if product.get("imgs") else "",
            "price": price,
            "qty": qty,
            "size": size,
            "subtotal": subtotal
        })
    return items, total

products = load_products()

@app.context_processor
def inject_request():
    return dict(request=request)

# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@app.route("/")
def home():
    reviews_list = []
    if db:
        try:
            reviews_ref = db.collection("reviews").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
            for r in reviews_ref:
                reviews_list.append({
                    "customer_name": r.get("customer_name") or "Anonymous",
                    "review_text": r.get("review_text") or "",
                    "rating": int(r.get("rating") or 0)
                })
        except Exception as e:
            logger.error(f"Fetch reviews failed: {e}")
    return render_template("home.html", products=products, reviews=reviews_list)

@app.route("/shop")
def shop():
    return render_template("shop.html", products=products)

@app.route("/cart")
def cart():
    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict):
        cart_data = {}
    items, total = get_cart_items_and_total(cart_data, products)
    return render_template("cart.html", cart_items=items, total=total)

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    pid = str(request.form.get("product_id"))
    size = request.form.get("size")
    qty = int(request.form.get("quantity", 1))
    if not pid or not size:
        return ("", 400)
    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict):
        cart_data = {}
    key = f"{pid}_{size}"
    if key in cart_data:
        _, current_qty = cart_data[key]
        cart_data[key] = (size, current_qty + qty)
    else:
        cart_data[key] = (size, qty)
    session["cart"] = cart_data
    return ("", 204)

@app.route("/update-cart", methods=["POST"])
def update_cart():
    key = str(request.form.get("key"))
    action = request.form.get("action")
    cart_data = session.get("cart", {})
    if key in cart_data:
        size, qty = cart_data[key]
        if action == "increase":
            cart_data[key] = (size, qty + 1)
        elif action == "decrease":
            cart_data[key] = (size, max(1, qty - 1))
        elif action == "remove":
            cart_data.pop(key, None)
    session["cart"] = cart_data
    return redirect(url_for("cart"))

@app.route("/checkout")
def checkout():
    cart_data = session.get("cart", {})
    if not cart_data:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("shop"))
    items, total = get_cart_items_and_total(cart_data, products)
    return render_template("checkout.html", cart_items=items, total=total)

@app.route("/process_order", methods=["POST"])
def process_order():
    if not db:
        flash("Firestore not available", "danger")
        return redirect(url_for("checkout"))
    cart_data = session.get("cart", {})
    if not cart_data:
        flash("Cart empty.", "warning")
        return redirect(url_for("shop"))
    order = {
        "name": request.form.get("name"),
        "mobile": request.form.get("mobile"),
        "email": request.form.get("email"),
        "address": request.form.get("address"),
        "items": [],
        "total": 0,
        "timestamp": datetime.utcnow()
    }
    items, total = get_cart_items_and_total(cart_data, products)
    order["items"] = items
    order["total"] = total
    try:
        db.collection("orders").add(order)
        session.pop("cart", None)
        return render_template("order_success.html", order_items=items, total=total)
    except Exception as e:
        logger.error(f"Save order failed: {e}")
        flash("Order failed", "danger")
        return redirect(url_for("checkout"))

@app.route("/submit-review", methods=["POST"])
def submit_review():
    if not db:
        flash("Firestore not available", "danger")
        return redirect(url_for("home"))
    name = request.form.get("name")
    review = request.form.get("review")
    rating = request.form.get("rating")
    if not name or not review or not rating:
        flash("Fill all fields", "warning")
        return redirect(url_for("home"))
    try:
        db.collection("reviews").add({
            "customer_name": name,
            "review_text": review,
            "rating": int(rating),
            "timestamp": datetime.utcnow()
        })
        flash("Review added")
    except Exception as e:
        logger.error(f"Save review failed: {e}")
        flash("Review failed", "danger")
    return redirect(url_for("home"))

# ---------------------------------------------------------------------
# Admin Panel
# ---------------------------------------------------------------------
@app.route("/secret-admin", methods=["GET", "POST"])
def secret_admin():
    global products
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            files = request.files.getlist("img_file")
            urls = [upload_to_imgbb(f) for f in files if f and f.filename]
            urls = [u for u in urls if u]
            if not urls:
                flash("Image upload failed", "danger")
                return redirect(url_for("secret_admin"))
            new_id = max([p["id"] for p in products], default=0) + 1
            products.append({
                "id": new_id,
                "imgs": urls,
                "name": request.form.get("name"),
                "desc": request.form.get("desc"),
                "price_small": request.form.get("price_small"),
                "price_medium": request.form.get("price_medium"),
                "price_large": request.form.get("price_large")
            })
            save_products(products)
            flash("Product added", "success")
        elif action == "update":
            pid = int(request.form.get("id"))
            product = next((p for p in products if p["id"] == pid), None)
            if not product:
                flash("Product not found", "danger")
                return redirect(url_for("secret_admin"))
            product["name"] = request.form.get("name")
            product["desc"] = request.form.get("desc")
            product["price_small"] = request.form.get("price_small")
            product["price_medium"] = request.form.get("price_medium")
            product["price_large"] = request.form.get("price_large")
            files = request.files.getlist("img_file")
            new_urls = [upload_to_imgbb(f) for f in files if f and f.filename]
            new_urls = [u for u in new_urls if u]
            if new_urls:
                product["imgs"] = new_urls
            save_products(products)
            flash("Product updated", "success")
        elif action == "delete":
            pid = int(request.form.get("id"))
            products = [p for p in products if p["id"] != pid]
            save_products(products)
            flash("Product deleted", "success")
        return redirect(url_for("secret_admin"))
    return render_template("admin_panel.html", products=products)

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
