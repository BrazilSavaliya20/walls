import os
import json
import tempfile
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, firestore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder='public', static_url_path='/static')
app.secret_key = os.environ.get("SECRET_KEY", "change_me_in_hpanel")

UPLOAD_FOLDER = os.path.join(app.static_folder, "images")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

products_file = os.path.join(BASE_DIR, 'products.json')

# Firebase initialization with env var fallback for service account JSON
firebase_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
if firebase_json:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_file:
        temp_file.write(firebase_json.encode())
        key_path = temp_file.name
    cred = credentials.Certificate(key_path)
else:
    key_path = os.path.join(BASE_DIR, "private", "firebase-key.json")
    cred = credentials.Certificate(key_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Load products from JSON file or create default
if os.path.exists(products_file):
    with open(products_file, "r", encoding="utf-8") as f:
        products = json.load(f)
else:
    products = [
        {'id': 1, 'img': 'product1.jpg', 'name': 'Golden Glow Panel',
         'desc': 'A handcrafted golden-accent backlit panel that adds pure luxury to your walls.',
         'old': '₹12,999', 'new': '₹9,999'},
        {'id': 2, 'img': 'product2.jpg', 'name': 'Marble Luxe Sign',
         'desc': 'Premium marble-textured LED sign.',
         'old': '₹15,499', 'new': '₹11,499'},
        {'id': 3, 'img': 'product3.jpg', 'name': 'Crystal Shine Decor',
         'desc': 'Elegant crystal-finished lighting decor.',
         'old': '₹10,999', 'new': '₹7,999'}
    ]
    with open(products_file, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Routes (same as your previous code, with minor changes for products persistence)

@app.route('/')
def home():
    return render_template('home.html', products=products)

@app.context_processor
def inject_request():
    return dict(request=request)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/process_contact', methods=['POST'])
def process_contact():
    contact_data = {
        "name": request.form.get('name'),
        "email": request.form.get('email'),
        "subject": request.form.get('subject'),
        "message": request.form.get('message')
    }
    db.collection("contacts").add(contact_data)
    flash("Thank you for reaching out! We will get back to you shortly.", "success")
    return redirect(url_for('contact'))

@app.route('/shop')
def shop():
    return render_template('shop.html', products=products)

@app.route('/cart')
def cart():
    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}
        session["cart"] = cart
    cart_items, total = [], 0
    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            price = int(product["new"].replace("₹", "").replace(",", "") or 0)
            subtotal = price * qty
            total += subtotal
            cart_items.append({
                "id": product["id"],
                "name": product["name"],
                "img": product["img"],
                "price": price,
                "qty": qty,
                "subtotal": subtotal
            })
    return render_template("cart.html", cart_items=cart_items, total=total)

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
            cart.pop(pid)

    session["cart"] = cart
    return redirect(url_for("cart"))

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

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = session.get("cart", {})
    if not isinstance(cart, dict) or not cart:
        flash("Your cart is empty. Please add items before checkout.", "warning")
        return redirect(url_for("shop"))

    cart_items, total = [], 0
    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            price = int(product["new"].replace("₹", "").replace(",", "") or 0)
            subtotal = price * qty
            total += subtotal
            cart_items.append({
                "id": product["id"],
                "name": product["name"],
                "img": product["img"],
                "price": price,
                "qty": qty,
                "subtotal": subtotal
            })
    return render_template("checkout.html", cart_items=cart_items, total=total)

@app.route("/process_order", methods=["POST"])
def process_order():
    order_data = {
        "name": request.form.get("name"),
        "mobile": request.form.get("mobile"),
        "email": request.form.get("email"),
        "address": request.form.get("address"),
        "items": [],
        "total": 0
    }
    cart = session.get("cart", {})
    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            price = int(product["new"].replace("₹", "").replace(",", "") or 0)
            subtotal = price * qty
            order_data["total"] += subtotal
            order_data["items"].append({
                "product_id": product["id"],
                "name": product["name"],
                "price": price,
                "quantity": qty,
                "subtotal": subtotal
            })
    db.collection("orders").add(order_data)
    flash("Your order has been placed successfully!", "success")
    session.pop("cart", None)
    return redirect(url_for("home"))

@app.route('/secret-admin', methods=['GET', 'POST'])
def secret_admin():
    global products

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            file = request.files.get('img_file')
            if not file or not allowed_file(file.filename):
                flash('Invalid or no image uploaded for new product!')
                return redirect(url_for('secret_admin'))

            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            new_id = max([p['id'] for p in products], default=0) + 1
            products.append({
                'id': new_id,
                'img': filename,
                'name': request.form['name'],
                'desc': request.form['desc'],
                'old': request.form['old'],
                'new': request.form['new']
            })

            # Save products list to JSON file
            with open(products_file, 'w', encoding='utf-8') as f:
                json.dump(products, f, ensure_ascii=False, indent=2)

            flash('Product added successfully.')

        elif action == 'update':
            pid = int(request.form['id'])
            product = next((p for p in products if p['id'] == pid), None)
            if product:
                product['name'] = request.form['name']
                product['desc'] = request.form['desc']
                product['old'] = request.form['old']
                product['new'] = request.form['new']
                file = request.files.get('img_file')
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    product['img'] = filename

                # Save products list to JSON file
                with open(products_file, 'w', encoding='utf-8') as f:
                    json.dump(products, f, ensure_ascii=False, indent=2)

                flash('Product updated successfully.')

        elif action == 'delete':
            pid = int(request.form['id'])
            products = [p for p in products if p['id'] != pid]

            # Save products list to JSON file
            with open(products_file, 'w', encoding='utf-8') as f:
                json.dump(products, f, ensure_ascii=False, indent=2)

            flash('Product deleted successfully.')

        return redirect(url_for('secret_admin'))

    return render_template('admin_panel.html', products=products)


@app.route('/secret-admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=Ture)

