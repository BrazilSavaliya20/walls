import os
import json
import logging
from typing import List, Dict, Any, Tuple
from flask import Flask, render_template, request, session, flash, redirect, url_for, abort
from datetime import datetime
from dotenv import load_dotenv
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import razorpay

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
# Razorpay configuration
# ---------------------------------------------------------------------
RAZORPAY_KEY_ID = "rzp_test_RGHzf24TfjfbAy"
RAZORPAY_KEY_SECRET = "xPSpg6R2zzdWf85Pn5gGfOyQ"
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ---------------------------------------------------------------------
# Hostinger Upload Integration
# ---------------------------------------------------------------------


import ftplib
import io

# FTP host and credentials (use secure storage in production)
FTP_HOST = "145.79.211.195"
FTP_USER = "u938557122"
FTP_PASS = "8141@#Kaswala"

def upload_file_to_hostinger(file_storage) -> str | None:
    try:
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.cwd('public_html/uploads')
        
        filename = file_storage.filename.replace(" ", "_")
        file_storage.stream.seek(0)  # Reset pointer before reading
        file_bytes = file_storage.read()
        bio = io.BytesIO(file_bytes)
        ftp.storbinary(f"STOR {filename}", bio)
        ftp.quit()

        return f"https://walls-craft.com/uploads/{filename}"
    except Exception as e:
        logger.error(f"FTP upload error: {e}")
        return None







# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def money_to_int(val: str) -> int:
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
# Product Data – Robust Persistence
# ---------------------------------------------------------------------
def save_products(data: List[Dict[str, Any]]) -> None:
    try:
        with open(products_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to write products file: {e}")

def load_products() -> List[Dict[str, Any]]:
    if os.path.exists(products_file):
        try:
            with open(products_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read products file: {e}")
    # Seed product
    products_seed = [
        {
            "id": 1,
            "imgs": ["https://walls-craft.com/uploads/sample.jpg"],
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

def get_products():
    return load_products()

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
    products_list = get_products()
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


@app.route("/cancellation-refund")
def cancellation_refund():
    return render_template("cancellation_refund.html")


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy_policy.html")


@app.route("/terms-conditions")
def terms_conditions():
    return render_template("terms_conditions.html")


@app.route("/shipping-policy")
def shipping_policy():
    return render_template("shipping_policy.html")


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
    return render_template("shop.html", products=get_products())


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = next((p for p in get_products() if p["id"] == product_id), None)
    if not product:
        abort(404)
    return render_template("product_detail.html", product=product)


@app.route("/cart")
def cart():
    cart_data = session.get("cart", {})
    cart_items, total = get_cart_items_and_total(cart_data, get_products())
    return render_template("cart.html", cart_items=cart_items, total=total)


@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    product_id = str(request.form.get('product_id'))
    quantity = int(request.form.get('quantity', 1))
    size = request.form.get('size', 'small')

    cart_data = session.get('cart', {})
    key = f"{product_id}:{size}"
    if key not in cart_data:
        cart_data[key] = {"qty": 0}
    cart_data[key]["qty"] += quantity
    session['cart'] = cart_data

    return redirect(url_for('cart'))


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
    cart_items, total = get_cart_items_and_total(cart_data, get_products())

    amount_in_paise = total * 100  # Convert INR to paise

    # Create order in Razorpay
    razorpay_order = razorpay_client.order.create({
        "amount": amount_in_paise,
        "currency": "INR",
        "payment_capture": "1"
    })

    return render_template("checkout.html",
                           cart_items=cart_items,
                           total=total,
                           razorpay_order_id=razorpay_order['id'],
                           razorpay_key_id=RAZORPAY_KEY_ID)


@app.route("/process_order", methods=["POST"])
def process_order():
    try:
        cart_data = session.get("cart")
        if not cart_data:
            flash("Your cart is empty. Please add items before checkout.")
            return redirect(url_for("shop"))

        # Razorpay payment details (sent from client after payment)
        payment_id = request.form.get('razorpay_payment_id')
        order_id = request.form.get('razorpay_order_id')
        signature = request.form.get('razorpay_signature')

        if not all([payment_id, order_id, signature]):
            flash("Payment information missing or invalid.")
            return redirect(url_for("checkout"))

        # Verify payment signature
        params_dict = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }

        try:
            razorpay_client.utility.verify_payment_signature(params_dict)
        except razorpay.errors.SignatureVerificationError:
            flash("Payment verification failed. Please contact support.")
            return redirect(url_for("checkout"))

        # Create order data object
        order_data = {
            "name": request.form.get("name"),
            "mobile": request.form.get("mobile"),
            "email": request.form.get("email"),
            "address": request.form.get("address"),
            "payment_id": payment_id,
            "order_id": order_id,
            "signature": signature,
            "items": [],
            "total": 0,
            "timestamp": datetime.utcnow(),
        }

        # Fill order items and total
        for key, data in cart_data.items():
            parts = key.split(":")
            if len(parts) != 2:
                continue
            pid, size = parts
            qty = data.get("qty", 0)
            product = next((p for p in get_products() if p["id"] == int(pid)), None)
            if not product:
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

        # Save order in Firestore
        if db:
            db.collection("orders").add(order_data)
            logger.info(f"Order saved with Razorpay payment ID {payment_id}")
        else:
            flash("Payment succeeded but order saving unavailable.")
            logger.error("Firestore not initialized.")

        session.pop("cart", None)

        return render_template("order_success.html", order_items=order_data["items"], total=order_data["total"])

    except Exception as e:
        logger.error("Exception during order processing", exc_info=True)
        flash("An error occurred processing your order.")
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
    products = load_products()  # Always load latest products

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            files = request.files.getlist("img_file")
            img_urls = [upload_file_to_hostinger(f) for f in files if f and f.filename]
            img_urls = [u for u in img_urls if u]  # Filter out None

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
            flash("Product added successfully.", "success")
            return redirect(url_for("secret_admin"))

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

            features = request.form.get("features", "")
            product["features"] = [f.strip() for f in features.split(",") if f.strip()]

            files = request.files.getlist("img_file")
            img_urls = [upload_file_to_hostinger(f) for f in files if f and f.filename]
            img_urls = [u for u in img_urls if u]

            imgs = product.get("imgs")
            if imgs is None:
                imgs = []
            elif isinstance(imgs, str):
                imgs = [imgs]

            if img_urls:
                imgs.extend(img_urls)
            product["imgs"] = imgs
            save_products(products)
            flash("Product updated successfully.", "success")
            return redirect(url_for("secret_admin"))

        elif action == "delete":
            pid = int(request.form.get("id"))
            products = [p for p in products if p["id"] != pid]
            save_products(products)
            flash("Product deleted successfully.", "success")
            return redirect(url_for("secret_admin"))

        elif action == "remove_image":
            pid = int(request.form.get("id"))
            img_url = request.form.get("img_url")
            product = next((p for p in products if p["id"] == pid), None)
            if product and img_url in product.get("imgs", []):
                product["imgs"] = [img for img in product.get("imgs", []) if img != img_url]
                save_products(products)
                flash("Image removed successfully.", "success")
            else:
                flash("Image or product not found.", "danger")
            return redirect(url_for("secret_admin"))

        elif action == "replace_image":
            pid = int(request.form.get("id"))
            img_url = request.form.get("img_url")
            product = next((p for p in products if p["id"] == pid), None)
            if not product:
                flash("Product not found for image replacement.", "danger")
                return redirect(url_for("secret_admin"))

            files = request.files.getlist("replace_img")
            if files and files[0] and files[0].filename:
                new_img_url = upload_file_to_hostinger(files[0])
                if new_img_url:
                    imgs = product.get("imgs")
                    if imgs is None:
                        imgs = []
                    elif isinstance(imgs, str):
                        imgs = [imgs]

                    if img_url in imgs:
                        idx = imgs.index(img_url)
                        imgs[idx] = new_img_url
                        product["imgs"] = imgs
                        save_products(products)
                        flash("Image replaced successfully.", "success")
                    else:
                        flash("Original image not found.", "danger")
                else:
                    flash("Failed to upload replacement image.", "danger")
            else:
                flash("No replacement image selected.", "warning")
            return redirect(url_for("secret_admin"))

    return render_template("admin_panel.html", products=products)


# ---------------------------------------------------------------------
# Run App
# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
