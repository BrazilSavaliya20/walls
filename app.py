import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, session, flash, redirect, url_for, abort
from dotenv import load_dotenv
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import razorpay
import base64

# Load environment variables
load_dotenv()

# Paths and setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_DIR = os.path.join(BASE_DIR, "private")
os.makedirs(PRIVATE_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(BASE_DIR, "public", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder="public", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "8141@#Kaswala")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wallcraft")

# Razorpay config
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_RGHzf24TfjfbAy")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "xPSpg6R2zzdWf85Pn5gGfOyQ")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ImgBB API Key
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "4daaf1a5f4db5099ddf6cc4035486275")  # Replace with your key

# Initialize Firestore
def init_firestore():
    firebase_key_json = os.environ.get("FIREBASE_KEY")
    if not firebase_key_json:
        raise Exception("FIREBASE_KEY env var not set")
    try:
        firebase_key_dict = json.loads(firebase_key_json)
    except Exception as e:
        raise Exception(f"Invalid FIREBASE_KEY JSON: {e}")
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

try:
    db = init_firestore()
    logger.info("Firestore initialized successfully")
except Exception as e:
    db = None
    logger.error(f"Failed to init Firestore: {e}")

# --- ImgBB upload ---
def upload_file_to_imgbb(file_storage) -> str | None:
    try:
        file_storage.stream.seek(0)
        img_bytes = file_storage.read()
        encoded_image = base64.b64encode(img_bytes).decode('utf-8')
        url = "https://api.imgbb.com/1/upload"
        payload = {
            "key": "4daaf1a5f4db5099ddf6cc4035486275",
            "image": encoded_image,
            "name": file_storage.filename,
            "expiration": "0"  # no auto delete
        }
        response = requests.post(url, data=payload)
        result = response.json()
        if response.status_code == 200 and result.get("success"):
            return result["data"]["url"]
        else:
            logger.error(f"ImgBB failed: {result}")
    except Exception as e:
        logger.error(f"Error uploading to ImgBB: {e}")
    return None

# --- Product data in Firestore ---
def load_products():
    if not db:
        # fallback local data (not ideal, but prevents crash)
        logger.warning("Firestore not available, loading fallback products")
        return fallback_products()
    try:
        products = []
        for doc in db.collection("products").stream():
            p = doc.to_dict()
            try:
                p['id'] = int(doc.id)
            except:
                p['id'] = doc.id
            products.append(p)
        if not products:
            return fallback_products()
        return products
    except Exception:
        return fallback_products()

def fallback_products():
    # default seed product
    seed = [{
        "id": 1,
        "imgs": ["https://i.ibb.co/DfdkKCgk/about2-jpg.jpg"],
        "name": "Golden Glow Panel",
        "desc": "Handcrafted golden-accent Wall Craft panel.",
        "price_small": "₹9,999",
        "price_medium": "₹12,999",
        "price_large": "₹15,999",
        "features": []
    }]
    return seed

def save_product(product: dict):
    if not db:
        return False # not supported without firestore
    try:
        doc_id = str(product.get("id") or datetime.utcnow().timestamp())
        db.collection("products").document(doc_id).set(product)
        return True
    except Exception as e:
        logger.error(f"Failed to save product {product.get('name')}: {e}")
        return False



ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

def allowed_file(filename):
    return (
        "." in filename and 
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )

def money_to_int(val: str) -> int:
    if not val:
        return 0
    try:
        return int(val.replace("₹", "").replace(",", "").strip())
    except Exception:
        return 0


def delete_product(pid):
    if not db:
        return False
    try:
        db.collection("products").document(str(pid)).delete()
        return True
    except Exception:
        return False

# --- Cart Utilities ---
def get_cart_items_and_total(cart, products):
    items = []
    total = 0
    for key, data in cart.items():
        try:
            pid, size = key.split(":")
            qty = data.get("qty", 0)
            if qty <= 0:
                continue
            product = next((p for p in products if str(p["id"]) == pid), None)
            if not product:
                continue
            price = money_to_int(product.get(f"price_{size}", "0"))
            subtotal = price * qty
            total += subtotal
            items.append({
                "id": product["id"],
                "name": product["name"],
                "img": product.get("imgs", [""])[0],
                "size": size,
                "price": price,
                "qty": qty,
                "subtotal": subtotal
            })
        except Exception as e:
            logger.error(f"Error processing cart item {key}: {e}")
    return items, total

# ==================== Routes ====================

@app.route("/")
def home():
    products = load_products()
    reviews = []
    if db:
        try:
            for r in db.collection("reviews").order_by("timestamp", direction=firestore.Query.DESCENDING).stream():
                review = r.to_dict()
                reviews.append({
                    "customer_name": review.get("customer_name", "Anonymous"),
                    "review_text": review.get("review_text", ""),
                    "rating": int(review.get("rating", 0))
                })
        except:
            pass
    return render_template("home.html", products=products, reviews=reviews)

@app.route("/shop")
def shop():
    return render_template("shop.html", products=load_products())

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    products = load_products()
    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        abort(404)
    return render_template("product_detail.html", product=product)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        flash("Thank you for connecting with us! We will get back to you soon.")
        return redirect(url_for("contact"))
    return render_template("contact.html")


@app.route('/cart')
def cart():
    cart = session.get('cart', {})
    products = load_products()
    items, total = get_cart_items_and_total(cart, products)
    return render_template('cart.html', cart_items=items, total=total)


@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    product_id = request.form.get('product_id')
    size = request.form.get('size')
    quantity = int(request.form.get('quantity', 1))
    cart = session.get('cart', {})

    key = f"{product_id}:{size}"
    if key not in cart:
        cart[key] = {'qty': 0}
    cart[key]['qty'] += quantity
    session['cart'] = cart

    return redirect(url_for('cart'))


@app.route("/update-cart", methods=["POST"])
def update_cart():
    pid = request.form.get("product_id")
    size = request.form.get("size", "small")
    action = request.form.get("action")
    key = f"{pid}:{size}"
    cart = session.get("cart", {})
    if key in cart:
        if action == "increase":
            cart[key]["qty"] += 1
        elif action == "decrease":
            cart[key]["qty"] = max(1, cart[key]["qty"] - 1)
        elif action == "remove":
            cart.pop(key, None)
    session["cart"] = cart
    return redirect(url_for("cart"))

@app.route("/checkout")
def checkout():
    cart = session.get("cart", {})
    products = load_products()
    items, total = get_cart_items_and_total(cart, products)

    amount_paise = total * 100
    try:
        razorpay_order = razorpay_client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "payment_capture": "1"
        })
    except:
        razorpay_order = {"id": None}

    return render_template("checkout.html", cart_items=items, total=total, razorpay_order_id=razorpay_order.get("id"), razorpay_key_id=RAZORPAY_KEY_ID)

@app.route("/process_order", methods=["POST"])
def process_order():
    try:
        cart = session.get("cart")
        if not cart:
            flash("Your cart is empty.")
            return redirect(url_for("shop"))

        payment_id = request.form.get('razorpay_payment_id')
        order_id = request.form.get('razorpay_order_id')
        signature = request.form.get('razorpay_signature')

        if not all([payment_id, order_id, signature]):
            flash("Payment info missing")
            return redirect(url_for("checkout"))

        # Verify signature
        params_dict = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }
        try:
            razorpay_client.utility.verify_payment_signature(params_dict)
        except razorpay.errors.SignatureVerificationError:
            flash("Payment verification failed")
            return redirect(url_for("checkout"))
        
        products = load_products()
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
            "timestamp": datetime.utcnow()
        }

        # Fill order items
        total_amount = 0
        for key, data in cart.items():
            try:
                pid, size = key.split(":")
                qty = data.get("qty", 0)
                product = next((p for p in products if str(p["id"]) == pid), None)
                if not product:
                    continue
                price = money_to_int(product.get(f"price_{size}", "0"))
                subtotal = price * qty
                total_amount += subtotal
                order_data["items"].append({
                    "product_id": product["id"],
                    "name": product["name"],
                    "img": product.get("imgs", [""])[0],
                    "size": size,
                    "price": price,
                    "quantity": qty,
                    "subtotal": subtotal
                })
            except:
                continue
        order_data["total"] = total_amount

        # Save order to Firestore
        if db:
            db.collection("orders").add(order_data)
            logger.info("Order saved in Firestore")
        else:
            logger.warning("Firestore not initialized, order not saved")

        session.pop("cart", None)
        return render_template("order_success.html", order_items=order_data["items"], total=order_data["total"])

    except Exception as e:
        logger.error(f"Order processing error: {e}")
        flash("Order processing error.")
        return redirect(url_for("checkout"))
    


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
        flash("⚠️ Please fill in all required fields.", "danger")
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
        flash("✅ Thank you! Your message has been sent successfully.", "success")
        return redirect(url_for("contact"))
    except Exception as e:
        logger.error(f"Failed to save contact: {e}")
        flash("⚠️ Failed to send message.", "danger")
        return redirect(url_for("contact"))



@app.route("/submit-review", methods=["POST"])
def submit_review():
    if not db:
        flash("Database not initialized", "danger")
        return redirect(url_for("home"))
    name = request.form.get("name")
    review_text = request.form.get("review")
    rating = request.form.get("rating")
    try:
        db.collection("reviews").add({
            "customer_name": name,
            "review_text": review_text,
            "rating": int(rating),
            "timestamp": datetime.utcnow()
        })
        flash("Review submitted.")
    except:
        flash("Failed to submit review.")
    return redirect(url_for("home"))
from datetime import datetime

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow}


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


# ----------- Admin Panel -----------

@app.route("/secret-admin", methods=["GET", "POST"])
def secret_admin():
    products = load_products()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            files = request.files.getlist("img_file")
            img_urls = [upload_file_to_imgbb(f) for f in files if f and f.filename and allowed_file(f.filename)]
            img_urls = [u for u in img_urls if u]
            features = request.form.get("features", "")
            features_list = [f.strip() for f in features.split(",") if f.strip()]
            new_id = int(datetime.utcnow().timestamp())
            product = {
                "id": new_id,
                "imgs": img_urls,
                "name": request.form.get("name"),
                "desc": request.form.get("desc"),
                "price_small": request.form.get("price_small"),
                "price_medium": request.form.get("price_medium"),
                "price_large": request.form.get("price_large"),
                "features": features_list
            }
            save_product(product)
            flash("Product added.")
            return redirect(url_for("secret_admin"))

        elif action == "update":
            pid = request.form.get("id")
            product_doc = db.collection("products").document(str(pid))
            if not product_doc.get().exists:
                flash("Product not found")
                return redirect(url_for("secret_admin"))
            product = product_doc.get().to_dict()
            product["name"] = request.form.get("name")
            product["desc"] = request.form.get("desc")
            product["price_small"] = request.form.get("price_small")
            product["price_medium"] = request.form.get("price_medium")
            product["price_large"] = request.form.get("price_large")
            features = request.form.get("features", "")
            product["features"] = [f.strip() for f in features.split(",") if f.strip()]
            # handle images
            files = request.files.getlist("img_file")
            img_urls = [upload_file_to_imgbb(f) for f in files if f and f.filename and allowed_file(f.filename)]
            img_urls = [u for u in img_urls if u]
            imgs = product.get("imgs", [])
            if isinstance(imgs, str):
                imgs = [imgs]
            imgs.extend(img_urls)
            product["imgs"] = imgs
            # Save updated
            try:
                product_doc.set(product)
                flash("Product updated.")
            except:
                flash("Failed to update product.")
            return redirect(url_for("secret_admin"))

        elif action == "delete":
            pid = request.form.get("id")
            db.collection("products").document(str(pid)).delete()
            flash("Product deleted.")
            return redirect(url_for("secret_admin"))

        elif action == "remove_image":
            pid = request.form.get("id")
            img_url = request.form.get("img_url")
            doc_ref = db.collection("products").document(str(pid))
            if not doc_ref.get().exists:
                flash("Product not found")
                return redirect(url_for("secret_admin"))
            product = doc_ref.get().to_dict()
            product["imgs"] = [img for img in product.get("imgs", []) if img != img_url]
            try:
                doc_ref.set(product)
                flash("Image removed.")
            except:
                flash("Failed to remove image.")
            return redirect(url_for("secret_admin"))

        elif action == "replace_image":
            pid = request.form.get("id")
            img_url = request.form.get("img_url")
            doc_ref = db.collection("products").document(str(pid))
            if not doc_ref.get().exists:
                flash("Product not found")
                return redirect(url_for("secret_admin"))
            product = doc_ref.get().to_dict()
            files = request.files.getlist("replace_img")
            if not files or not files[0].filename:
                flash("No replacement image")
                return redirect(url_for("secret_admin"))
            new_img = upload_file_to_imgbb(files[0])
            if not new_img:
                flash("Image upload failed")
                return redirect(url_for("secret_admin"))

            imgs = product.get("imgs", [])
            if isinstance(imgs, str):
                imgs = [imgs]
            if img_url in imgs:
                idx = imgs.index(img_url)
                imgs[idx] = new_img
                product["imgs"] = imgs
                try:
                    doc_ref.set(product)
                    flash("Image replaced.")
                except:
                    flash("Failed to replace image.")
            else:
                flash("Original image not found.")
            return redirect(url_for("secret_admin"))

    return render_template("admin_panel.html", products=load_products())

# Run the app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
