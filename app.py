import os
import json
import logging
from typing import List, Dict, Any, Tuple
from flask import Flask, render_template, request, session, flash, redirect, url_for
from datetime import datetime
from werkzeug.utils import secure_filename
from dotenv import load_dotenv  # <-- this is missing

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------------------------------------------------------
# App & Config
# ---------------------------------------------------------------------
# Load .env
import os
import json
import logging
from typing import List, Dict, Any, Tuple
from flask import Flask, request
import firebase_admin
from firebase_admin import credentials, firestore, storage
from dotenv import load_dotenv

# -------------------------------------------------------------------
# Load environment variables
# -------------------------------------------------------------------
load_dotenv()

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_DIR = os.path.join(BASE_DIR, "private")
os.makedirs(PRIVATE_DIR, exist_ok=True)

# Flask app
app = Flask(__name__, static_folder="public", static_url_path="/static")

# Flask secret key
app.secret_key = os.environ.get("SECRET_KEY", "8141@#Kaswala")

# Upload folder
UPLOAD_FOLDER = os.path.join(BASE_DIR, "public", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Products file path
products_file = os.path.join(PRIVATE_DIR, "products.json")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wallcraft")

# Allowed image types
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -------------------------------------------------------------------
# Firebase Init (from environment variable)
# -------------------------------------------------------------------
def init_firestore():
    firebase_key_json = os.environ.get("FIREBASE_KEY")
    if not firebase_key_json:
        raise Exception("FIREBASE_KEY environment variable not set!")
    firebase_key_dict = json.loads(firebase_key_json)
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_key_dict)
        firebase_admin.initialize_app(cred, {
            "storageBucket": "project-7527910338923540672.appspot.com"
        })
    return firestore.client(), storage.bucket()

db, bucket = init_firestore()
def upload_image_to_storage(file, filename):
    """Uploads a file object to Firebase storage. Returns the public URL."""
    blob = bucket.blob(f"product_images/{filename}")
    blob.upload_from_file(file, content_type=file.content_type)
    blob.make_public()  # Make the file public (or set ACL if needed)
    return blob.public_url


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def money_to_int(val: str) -> int:
    if not val:
        return 0
    return int(val.replace("₹", "").replace(",", "").strip() or 0)

def save_products(data: List[Dict[str, Any]]) -> None:
    try:
        with open(products_file, 'w', encoding='utf-8') as f:
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

    # Seed default product if file missing
    products_seed = [
        {
            'id': 1, 'img': 'product1.jpg', 'name': 'Golden Glow Panel',
            'desc': 'Handcrafted golden-accent Wall Craft panel.',
            'old': '₹12,999', 'new': '₹9,999'
        }
    ]
    save_products(products_seed)
    return products_seed

def get_cart_items_and_total(cart: Dict[str, int], products: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    items = []
    total = 0
    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if not product:
            continue
        price = money_to_int(product.get("new"))
        subtotal = price * qty
        total += subtotal
        items.append({
            "id": product["id"], "name": product["name"],
            "img": product["img"], "price": price,
            "qty": qty, "subtotal": subtotal
        })
    return items, total

# Load products
products = load_products()

# -------------------------------------------------------------------
# Context
# -------------------------------------------------------------------
@app.context_processor
def inject_request():
    return dict(request=request)

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.route('/')
def home():
    return render_template('home.html', products=products)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        flash('Thank you for connecting with us! We will get back to you soon.')
        return redirect(url_for('contact'))
    return render_template('contact.html')

@app.route('/process_contact', methods=['POST'])
def process_contact():
    if db is None:
        flash("⚠️ Firestore is not initialized.", "danger")
        return redirect(url_for("contact"))

    name = request.form.get('name')
    email = request.form.get('email')
    mobile = request.form.get('mobile')
    address = request.form.get('address')
    message = request.form.get('message')

    if not name or not email or not mobile:
        flash("⚠️ Please fill in all required fields.")
        return redirect(url_for('contact'))

    try:
        db.collection("contacts").add({
            "name": name,
            "email": email,
            "mobile": mobile,
            "address": address,
            "message": message,
            "timestamp": datetime.utcnow()
        })
        flash("✅ Thank you! Your message has been sent successfully.")
        return render_template("success.html", name=name)
    except Exception as e:
        logger.error(f"Failed to save contact: {e}")
        flash("⚠️ Failed to send message.", "danger")
        return redirect(url_for("contact"))

@app.route('/shop')
def shop():
    return render_template('shop.html', products=products)

@app.route('/cart')
def cart():
    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict):
        cart_data = {}
        session["cart"] = cart_data

    cart_items, total = get_cart_items_and_total(cart_data, products)
    return render_template("cart.html", cart_items=cart_items, total=total)

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    product_id = str(request.form.get('product_id'))
    quantity = int(request.form.get('quantity', 1))

    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict):
        cart_data = {}

    cart_data[product_id] = cart_data.get(product_id, 0) + quantity
    session["cart"] = cart_data
    return ("", 204)

@app.route('/update-cart', methods=['POST'])
def update_cart():
    pid = str(request.form.get("product_id"))
    action = request.form.get("action")

    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict):
        cart_data = {}

    if pid in cart_data:
        if action == "increase":
            cart_data[pid] += 1
        elif action == "decrease":
            cart_data[pid] = max(1, cart_data[pid] - 1)
        elif action == "remove":
            cart_data.pop(pid, None)

    session["cart"] = cart_data
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["GET"])
def checkout():
    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict) or not cart_data:
        flash("Your cart is empty. Please add items before checkout.", "warning")
        return redirect(url_for("shop"))

    cart_items, total = get_cart_items_and_total(cart_data, products)
    return render_template("checkout.html", cart_items=cart_items, total=total)

@app.route("/process_order", methods=["POST"])
def process_order():
    if db is None:
        flash("⚠️ Firestore is not initialized.", "danger")
        return redirect(url_for("checkout"))

    order_data = {
        "name": request.form.get("name"),
        "mobile": request.form.get("mobile"),
        "email": request.form.get("email"),
        "address": request.form.get("address"),
        "items": [],
        "total": 0,
        "timestamp": datetime.utcnow()
    }

    cart_data = session.get("cart", {})

    try:
        for pid, qty in cart_data.items():
            product = next((p for p in products if p["id"] == int(pid)), None)
            if product:
                price = money_to_int(product.get("new"))
                subtotal = price * qty
                order_data["total"] += subtotal
                order_data["items"].append({
                    "product_id": product["id"],
                    "name": product["name"],
                    "img": product["img"],
                    "price": price,
                    "quantity": qty,
                    "subtotal": subtotal
                })

        db.collection("orders").add(order_data)
        session.pop("cart", None)

        return render_template("order_success.html", order_items=order_data["items"], total=order_data["total"])

    except Exception as e:
        logger.error(f"Failed to save order data: {e}")
        flash("Failed to process your order. Please try again later.", "danger")
        return redirect(url_for("checkout"))

# -------------------------------------------------------------------
# Admin Panel (basic, NOT authenticated!)
# -------------------------------------------------------------------
@app.route('/secret-admin', methods=['GET', 'POST'])
def secret_admin():
    global products

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            file = request.files.get('img_file')
            if not file or not allowed_file(file.filename):
                flash('Invalid or no image uploaded for new product!', "danger")
                return redirect(url_for('secret_admin'))
            filename = secure_filename(file.filename)
            # upload to firebase storage
            image_url = upload_image_to_storage(file, filename)
            new_id = max([p['id'] for p in products], default=0) + 1
            products.append({
                'id': new_id,
                'img': image_url,  # Store the URL, not the filename
                'name': request.form.get('name'),
                'desc': request.form.get('desc'),
                'old': request.form.get('old'),
                'new': request.form.get('new')
            })
            save_products(products)
            flash('Product added successfully.', "success")

        elif action == 'update':
            pid = int(request.form.get('id'))
            product = next((p for p in products if p['id'] == pid), None)
            if not product:
                flash('Product not found.', "danger")
                return redirect(url_for('secret_admin'))
            product['name'] = request.form.get('name')
            product['desc'] = request.form.get('desc')
            product['old'] = request.form.get('old')
            product['new'] = request.form.get('new')
            file = request.files.get('img_file')
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                image_url = upload_image_to_storage(file, filename)
                product['img'] = image_url  # Update with new image URL
            save_products(products)
            flash('Product updated successfully.', "success")

        elif action == 'delete':
            pid = int(request.form.get('id'))
            products = [p for p in products if p['id'] != pid]
            save_products(products)
            flash('Product deleted successfully.', "success")
        return redirect(url_for('secret_admin'))

    return render_template('admin_panel.html', products=products)


# -------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

