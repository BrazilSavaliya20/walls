import os
import json
import logging
from typing import List, Dict, Any, Tuple
from flask import Flask, render_template, request, session, flash, redirect, url_for
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------------------------------------------------------
# App & Config
# ---------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder="public", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "replace_this_value")

# Private folder
PRIVATE_DIR = os.path.join(BASE_DIR, "private")
os.makedirs(PRIVATE_DIR, exist_ok=True)

# Products file path
products_file = os.path.join(PRIVATE_DIR, "products.json")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wallcraft")

# -------------------------------------------------------------------
# Firebase Init
# -------------------------------------------------------------------
def init_firestore():
    key_path = os.path.join(PRIVATE_DIR, "firebase-key.json")
    if not os.path.exists(key_path):
        logger.error("❌ firebase-key.json missing")
        return None

    cred = credentials.Certificate(key_path)
    if not firebase_admin._apps:  # prevent re-init
        firebase_admin.initialize_app(cred)
        logger.info("🔥 Firebase initialized successfully.")

    return firestore.client()

db = init_firestore()

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def money_to_int(val: str) -> int:
    """Convert '₹9,999' -> 9999"""
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
    """Load products from JSON, or seed if missing"""
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
    """Build cart items + calculate total"""
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

# Load products into memory
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
    name = request.form.get('name')
    email = request.form.get('email')
    subject = request.form.get('subject')
    message = request.form.get('message')

    if not name or not email or not subject or not message:
        flash("⚠️ Please fill in all fields.")
        return redirect(url_for('contact'))

    # Save to Firestore (optional)
    db.collection("contacts").add({
        "name": name,
        "email": email,
        "subject": subject,
        "message": message,
        "timestamp": datetime.utcnow()
    })

    flash("✅ Thank you! Your message has been sent successfully.")
    return render_template("success.html", name=name)

@app.route('/shop')
def shop():
    return render_template('shop.html', products=products)

@app.route('/cart')
def cart():
    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}
        session["cart"] = cart

    cart_items, total = get_cart_items_and_total(cart, products)
    return render_template("cart.html", cart_items=cart_items, total=total)

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    product_id = str(request.form.get('product_id'))
    quantity = int(request.form.get('quantity', 1))

    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}

    cart[product_id] = cart.get(product_id, 0) + quantity
    session["cart"] = cart
    return ("", 204)

@app.route('/update-cart', methods=['POST'])
def update_cart():
    pid = str(request.form.get("product_id"))
    action = request.form.get("action")

    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}

    if pid in cart:
        if action == "increase":
            cart[pid] += 1
        elif action == "decrease":
            cart[pid] = max(1, cart[pid] - 1)
        elif action == "remove":
            cart.pop(pid, None)

    session["cart"] = cart
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["GET"])
def checkout():
    cart = session.get("cart", {})
    if not isinstance(cart, dict) or not cart:
        flash("Your cart is empty. Please add items before checkout.", "warning")
        return redirect(url_for("shop"))

    cart_items, total = get_cart_items_and_total(cart, products)
    return render_template("checkout.html", cart_items=cart_items, total=total)

@app.route("/process_order", methods=["POST"])
def process_order():
    order_data = {
        "name": request.form.get("name"),
        "mobile": request.form.get("mobile"),
        "email": request.form.get("email"),
        "address": request.form.get("address"),
        "items": [],
        "total": 0,
        "timestamp": datetime.utcnow()  # ✅ add timestamp for sorting
    }

    cart = session.get("cart", {})

    try:
        for pid, qty in cart.items():
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

        # Save order to Firestore
        db.collection("orders").add(order_data)

        # Clear cart
        session.pop("cart", None)

        return render_template("order_success.html", order_items=order_data["items"], total=order_data["total"])

    except Exception as e:
        app.logger.error(f"Failed to save order data: {e}")
        flash("Failed to process your order. Please try again later.", "danger")
        return redirect(url_for("checkout"))



# -----------------------------------------------------------------------------
# Admin (simple, not authenticated — protect before production!)
# -----------------------------------------------------------------------------
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
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            new_id = max([p['id'] for p in products], default=0) + 1
            products.append({
                'id': new_id,
                'img': filename,
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
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                product['img'] = filename

            save_products(products)
            flash('Product updated successfully.', "success")

        elif action == 'delete':
            pid = int(request.form.get('id'))
            products = [p for p in products if p['id'] != pid]
            save_products(products)
            flash('Product deleted successfully.', "success")

        return redirect(url_for('secret_admin'))

    return render_template('admin_panel.html', products=products)


# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



