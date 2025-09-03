import os
import json
import logging
from typing import List, Dict, Any, Tuple
from flask import Flask, render_template, request, session, flash, redirect, url_for, abort
from datetime import datetime
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import requests

# ---------------------------------------------------------------------
# Load environment variables
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

products_file = os.path.join(PRIVATE_DIR, "products.json")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wallcraft")

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

def allowed_file(filename: str) -> bool:
    """Check if the filename has an allowed extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def money_to_int(val: str) -> int:
    """
    Converts a money string like '₹9,999' to integer 9999.
    Handles empty or invalid strings gracefully returning 0.
    """
    if not val:
        return 0
    try:
        cleaned = val.replace("₹", "").replace(",", "").strip()
        return int(cleaned) if cleaned else 0
    except ValueError:
        logger.warning(f"money_to_int: Cannot convert value '{val}' to int.")
        return 0

# ---------------------------------------------------------------------
# Firebase Initialization
# ---------------------------------------------------------------------
def init_firestore():
    firebase_key_json = os.environ.get("FIREBASE_KEY")
    if not firebase_key_json:
        raise Exception("FIREBASE_KEY environment variable not set!")
    try:
        firebase_key_dict = json.loads(firebase_key_json)
    except Exception as e:
        raise Exception(f"FIREBASE_KEY is not a valid JSON string: {e}")
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = None
try:
    db = init_firestore()
    logger.info("Firestore initialized successfully.")
except Exception as e:
    logger.error(f"Firestore initialization failed: {e}")

# ---------------------------------------------------------------------
# ImgBB Upload
# ---------------------------------------------------------------------
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "49c929b174cd1008c4379f46285ac846")

def upload_to_imgbb(file) -> str | None:
    """
    Uploads a file object to ImgBB and returns the hosted image direct URL.
    Returns None if upload fails.
    """
    try:
        response = requests.post(
            "https://api.imgbb.com/1/upload",
            params={"key": IMGBB_API_KEY},
            files={"image": (file.filename, file.stream, file.content_type)},
            timeout=30  # Timeout for network robustness
        )
        result = response.json()
        if response.status_code == 200 and result.get("success"):
            return result["data"]["image"]["url"]
        else:
            app.logger.error(f"ImgBB upload failed: {result}")
            return None
    except requests.exceptions.RequestException as req_ex:
        app.logger.error(f"ImgBB upload request error: {req_ex}")
        return None
    except Exception as e:
        app.logger.error(f"ImgBB upload unexpected error: {e}")
        return None

# ---------------------------------------------------------------------
# Product Data
# ---------------------------------------------------------------------
def save_products(data: List[Dict[str, Any]]) -> None:
    """Saves product list as JSON file."""
    try:
        with open(products_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to write products file: {e}")

def load_products() -> List[Dict[str, Any]]:
    """Loads the product list from JSON file or returns a seed product list."""
    if os.path.exists(products_file):
        try:
            with open(products_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read products file: {e}")

    # Seed product with hosted image URL (replace with your hosted image URL)
    products_seed = [
        {
            "id": 1,
            "imgs": ["https://i.ibb.co/DfdkKCgk/about2-jpg.jpg"],  # Replace this URL with actual hosted image URL
            "name": "Golden Glow Panel",
            "desc": "Handcrafted golden-accent Wall Craft panel.",
            "price_small": "₹9,999",
            "price_medium": "₹12,999",
            "price_large": "₹15,999",
        }
    ]
    save_products(products_seed)
    return products_seed

def get_cart_items_and_total(cart: Dict[str, Any], products: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Calculates cart items details and total cost."""
    items = []
    total = 0
    for key, data in cart.items():
        try:
            parts = key.split(":")
            if len(parts) != 2:
                logger.error(f"Invalid cart item key format: {key}")
                continue
            pid, size = parts
            qty = data.get("qty", 0)
            product = next((p for p in products if p["id"] == int(pid)), None)
            if not product or qty <= 0:
                continue
            price = money_to_int(product.get(f"price_{size}", "0"))
            subtotal = price * qty
            total += subtotal
            img_url = product.get("imgs")[0] if product.get("imgs") else ""
            items.append({
                "id": product["id"],
                "name": product["name"],
                "img": img_url,
                "size": size,
                "price": price,
                "qty": qty,
                "subtotal": subtotal,
            })
        except Exception as e:
            logger.error(f"Error processing cart item {key}: {e}")
    return items, total

# Load products once at startup
products = load_products()

@app.context_processor
def inject_request():
    return dict(request=request)

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow}

# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------

@app.route("/")
def home():
    products_list = products
    reviews_list = []
    if db:
        try:
            reviews_ref = db.collection("reviews").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
            for r in reviews_ref:
                reviews_list.append({
                    "customer_name": r.get("customer_name") or "Anonymous",
                    "review_text": r.get("review_text") or "",
                    "rating": int(r.get("rating") or 0),
                })
        except Exception as e:
            logger.error(f"Failed to fetch reviews: {e}")
    return render_template("home.html", products=products_list, reviews=reviews_list)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        flash("Thank you for connecting with us! We will get back to you soon.")
        return redirect(url_for("contact"))
    return render_template("contact.html")

@app.route("/process_contact", methods=["POST"])
def process_contact():
    if db is None:
        flash("⚠️ Firestore is not initialized.", "danger")
        return redirect(url_for("contact"))
    name = request.form.get("name")
    email = request.form.get("email")
    mobile = request.form.get("mobile")
    address = request.form.get("address")
    message = request.form.get("message")
    if not name or not email or not mobile:
        flash("⚠️ Please fill in all required fields.")
        return redirect(url_for("contact"))
    try:
        db.collection("contacts").add({
            "name": name,
            "email": email,
            "mobile": mobile,
            "address": address,
            "message": message,
            "timestamp": datetime.utcnow(),
        })
        flash("✅ Thank you! Your message has been sent successfully.")
        return render_template("success.html", name=name)
    except Exception as e:
        logger.error(f"Failed to save contact: {e}")
        flash("⚠️ Failed to send message.", "danger")
        return redirect(url_for("contact"))

@app.route("/shop")
def shop():
    return render_template("shop.html", products=products)

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        abort(404)
    return render_template("product_detail.html", product=product)

@app.route("/cart")
def cart():
    cart_data = session.get("cart", {})
    cart_items, total = get_cart_items_and_total(cart_data, products)
    return render_template("cart.html", cart_items=cart_items, total=total)

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    pid = str(request.form.get("product_id"))
    size = request.form.get("size", "small")
    quantity = int(request.form.get("quantity", 1))
    cart_data = session.get("cart", {})
    key = f"{pid}:{size}"
    if key not in cart_data:
        cart_data[key] = {"qty": 0}
    cart_data[key]["qty"] += quantity
    session["cart"] = cart_data
    return ("", 204)

@app.route("/update-cart", methods=["POST"])
def update_cart():
    pid = str(request.form.get("product_id"))
    size = request.form.get("size", "small")
    action = request.form.get("action")
    key = f"{pid}:{size}"
    cart_data = session.get("cart", {})
    if key in cart_data:
        if action == "increase":
            cart_data[key]["qty"] += 1
        elif action == "decrease":
            cart_data[key]["qty"] = max(1, cart_data[key]["qty"] - 1)
        elif action == "remove":
            cart_data.pop(key, None)
    session["cart"] = cart_data
    return redirect(url_for("cart"))

@app.route("/checkout")
def checkout():
    cart_data = session.get("cart", {})
    if not cart_data:
        flash("Your cart is empty. Please add items before checkout.", "warning")
        return redirect(url_for("shop"))
    cart_items, total = get_cart_items_and_total(cart_data, products)
    return render_template("checkout.html", cart_items=cart_items, total=total)

@app.route("/process_order", methods=["POST"])
def process_order():
    try:
        cart_data = session.get("cart")
        if not cart_data:
            flash("Your cart is empty. Please add items before checkout.", "warning")
            return redirect(url_for("shop"))

        logger.info(f"Processing order with cart: {cart_data}")

        order_data = {
            "name": request.form.get("name"),
            "mobile": request.form.get("mobile"),
            "email": request.form.get("email"),
            "address": request.form.get("address"),
            "items": [],
            "total": 0,
            "timestamp": datetime.utcnow(),
        }

        for key, data in cart_data.items():
            parts = key.split(":")
            if len(parts) != 2:
                logger.error(f"Invalid cart item key format: {key}")
                continue
            pid, size = parts
            qty = data.get("qty", 0)
            product = next((p for p in products if p["id"] == int(pid)), None)
            if not product:
                logger.warning(f"Product with ID {pid} not found in products list.")
                continue
            price = money_to_int(product.get(f"price_{size}", "0"))
            subtotal = price * qty
            order_data["total"] += subtotal
            order_data["items"].append({
                "product_id": product["id"],
                "name": product["name"],
                "img": product["imgs"][0] if product.get("imgs") else "/static/images/placeholder.png",
                "size": size,
                "price": price,
                "quantity": qty,
                "subtotal": subtotal,
            })

        if db:
            doc_ref = db.collection("orders").add(order_data)
            logger.info(f"Order saved with Firestore Doc ID: {doc_ref[1].id}")
        else:
            logger.error("Firestore not initialized. Cannot save order to Firestore.")
            flash("Order service temporarily unavailable, please try again later.", "danger")
            return redirect(url_for("checkout"))

        session.pop("cart", None)
        flash("Order placed successfully!")
        return render_template("order_success.html", order_items=order_data["items"], total=order_data["total"])
    except Exception as e:
        logger.error(f"Exception in process_order: {e}", exc_info=True)
        flash("Failed to process your order. Please try again.", "danger")
        return redirect(url_for("checkout"))

@app.route("/submit-review", methods=["POST"])
def submit_review():
    if db is None:
        flash("⚠️ Firestore is not initialized.", "danger")
        return redirect(url_for("home"))
    name = request.form.get("name")
    review = request.form.get("review")
    rating = request.form.get("rating")
    if not name or not review or not rating:
        flash("⚠️ Please provide name, review, and rating.", "warning")
        return redirect(request.referrer or url_for("home"))
    try:
        db.collection("reviews").add({
            "customer_name": name,
            "review_text": review,
            "rating": int(rating),
            "timestamp": datetime.utcnow(),
        })
        flash("✅ Thank you for your review!")
    except Exception as e:
        logger.error(f"Failed to save review: {e}")
        flash("⚠️ Failed to submit review.", "danger")
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
            img_urls = [upload_to_imgbb(f) for f in files if f and f.filename]
            img_urls = [u for u in img_urls if u]

            # Process features - split by commas, strip whitespace
            features = request.form.get("features", "")
            features_list = [f.strip() for f in features.split(",") if f.strip()]

            new_id = max([p["id"] for p in products], default=0) + 1
            products.append({
                "id": new_id,
                "imgs": img_urls,
                "name": request.form.get("name"),
                "desc": request.form.get("desc"),
                "price_small": request.form.get("price_small"),
                "price_medium": request.form.get("price_medium"),
                "price_large": request.form.get("price_large"),
                "features": features_list,
            })

            save_products(products)
            products = load_products()  # Reload after save
            flash("Product added successfully.", "success")

        elif action == "update":
            pid = int(request.form.get("id"))
            product = next((p for p in products if p["id"] == pid), None)
            if not product:
                flash("Product not found.", "danger")
                return redirect(url_for("secret_admin"))

            product["name"] = request.form.get("name")
            product["desc"] = request.form.get("desc")
            product["price_small"] = request.form.get("price_small")
            product["price_medium"] = request.form.get("price_medium")
            product["price_large"] = request.form.get("price_large")

            # Features
            features = request.form.get("features", "")
            product["features"] = [f.strip() for f in features.split(",") if f.strip()]

            files = request.files.getlist("img_file")
            img_urls = [upload_to_imgbb(f) for f in files if f and f.filename]
            img_urls = [u for u in img_urls if u]
            if img_urls:
                # Append new images instead of replacing all
                product["imgs"].extend(img_urls)

            save_products(products)
            products = load_products()  # Reload after save
            flash("Product updated successfully.", "success")

        elif action == "delete":
            pid = int(request.form.get("id"))
            products = [p for p in products if p["id"] != pid]
            save_products(products)
            products = load_products()  # Reload after save
            flash("Product deleted successfully.", "success")

        return redirect(url_for("secret_admin"))

    return render_template("admin_panel.html", products=products)


# ---------------------------------------------------------------------
# Run App
# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
