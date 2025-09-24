import os
import json
import logging
import base64
from typing import List, Dict, Any, Tuple
from flask import Flask, render_template, request, session, flash, redirect, url_for, abort
from datetime import datetime
from dotenv import load_dotenv
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import razorpay


# Load environment variables
load_dotenv()

# Paths and setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_DIR = os.path.join(BASE_DIR, "private")
os.makedirs(PRIVATE_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(BASE_DIR, "public", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
products_file = os.path.join(PRIVATE_DIR, "products.json")

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
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "debd1d013910003d49c0b4dbec779e64")  # Replace with your key

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
import base64
import requests

IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "49c929b174cd1008c4379f46285ac846")  # Replace with actual key

def upload_file_to_imgbb_and_get_url(file_storage) -> str | None:
    try:
        file_storage.seek(0)
        img_bytes = file_storage.read()
        encoded_image = base64.b64encode(img_bytes).decode('utf-8')
        url = "https://api.imgbb.com/1/upload"
        payload = {
            "key": IMGBB_API_KEY,
            "image": encoded_image,
            "name": file_storage.filename,
            "expiration": "0"
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(url, data=payload, headers=headers)
        result = response.json()
        if response.status_code == 200 and result.get("success"):
            direct_url = result["data"]["url"]
            return direct_url
        else:
            logger.error(f"ImgBB upload failed: {result}")
            return None
    except Exception as e:
        logger.error(f"Exception during ImgBB upload: {e}")
        return None



def add_product_to_firestore(data):
    try:
        db.collection("products").document(str(data["id"])).set(data)
        logger.info(f"Product {data['id']} saved to Firestore")
        return True
    except Exception as e:
        logger.error(f"Error saving product to Firestore: {e}")
        return False






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
        logger.info("products.json saved with %d products", len(data))
    except Exception as e:
        logger.error(f"Failed to write products file: {e}")

def load_products_from_firestore() -> List[Dict[str, Any]]:
    if not db:
        logger.warning("Firestore DB not initialized.")
        return []

    products = []
    try:
        docs = db.collection("products").order_by("id").stream()
        for doc in docs:
            product = doc.to_dict()
            # Ensure 'id' is int for sorting & comparisons if stored as string
            if "id" in product:
                product["id"] = int(product["id"])
            products.append(product)
    except Exception as e:
        logger.error(f"Error loading products from Firestore: {e}")
    return products


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

# ==================== Routes ====================

@app.route("/")
def home():
    products = load_products_from_firestore()
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
    products = load_products_from_firestore()
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
    products = load_products_from_firestore()
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
    products = load_products_from_firestore()
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
        
        products = load_products_from_firestore()
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
    products = load_products_from_firestore()

    def upload_image_and_save_to_firestore(file_storage, product_id):
        try:
            file_storage.seek(0)
            img_bytes = file_storage.read()
            encoded_image = base64.b64encode(img_bytes).decode('utf-8')
            url = "https://api.imgbb.com/1/upload"
            payload = {
                "key": "49c929b174cd1008c4379f46285ac846",
                "image": encoded_image,
                "name": file_storage.filename,
                "expiration": "0"  # no auto-delete
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            response = requests.post(url, data=payload, headers=headers)
            result = response.json()
            if response.status_code == 200 and result.get("success"):
                direct_url = result["data"]["url"]
                if direct_url:
                    if db and product_id is not None:
                        product_ref = db.collection("products").document(str(product_id))
                        product_doc = product_ref.get()
                        if product_doc.exists:
                            product_data = product_doc.to_dict()
                            imgs = product_data.get("imgs", [])
                            if isinstance(imgs, str):
                                imgs = [imgs]
                            imgs.append(direct_url)
                            try:
                                product_ref.update({"imgs": imgs})
                                logger.info(f"Image URL saved to Firestore for product {product_id}")
                            except Exception as e:
                                logger.error(f"Error updating Firestore product images: {e}")
                        else:
                            try:
                                product_ref.set({"imgs": [direct_url]})
                                logger.info(f"Firestore product document created with image for product {product_id}")
                            except Exception as e:
                                logger.error(f"Error creating Firestore product document: {e}")
                    return direct_url
            logger.error(f"ImgBB upload failed or invalid direct_url: {result}")
            return None
        except Exception as e:
            logger.error(f"Exception during ImgBB upload and Firestore save: {e}")
            return None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            files = request.files.getlist("img_file")
            img_urls = []
            for f in files:
                if f and f.filename and allowed_file(f.filename):
                    url = upload_file_to_imgbb(f)
                    if url:
                        img_urls.append(url)

            features = request.form.get("features", "")
            features_list = [f.strip() for f in features.split(",") if f.strip()]
            new_id = max([p.get("id", 0) for p in products], default=0) + 1

            new_product = {
                "id": new_id,
                "imgs": img_urls,
                "name": request.form.get("name"),
                "desc": request.form.get("desc"),
                "price_small": request.form.get("price_small"),
                "price_medium": request.form.get("price_medium"),
                "price_large": request.form.get("price_large"),
                "features": features_list,
            }
            try:
                db.collection("products").document(str(new_id)).set(new_product)
                logger.info("Product synced to Firestore")
                flash("Product added successfully.", "success")
            except Exception as e:
                logger.error(f"Could not save product to Firestore: {e}")
                flash("Failed to add product.", "danger")
            return redirect(url_for("secret_admin"))

        elif action == "update":
            try:
                pid = int(request.form.get("id"))
            except (ValueError, TypeError):
                flash("Invalid product ID.", "danger")
                return redirect(url_for("secret_admin"))
            product = next((p for p in products if p.get("id") == pid), None)
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
            img_urls = []
            for f in files:
                if f and f.filename and allowed_file(f.filename):
                    url = upload_image_and_save_to_firestore(f, pid)
                    if url:
                        img_urls.append(url)
            imgs = product.get("imgs") or []
            if isinstance(imgs, str):
                imgs = [imgs]
            if img_urls:
                imgs.extend(img_urls)
            product["imgs"] = imgs
            try:
                db.collection("products").document(str(pid)).set(product)
                logger.info("Product updated in Firestore")
                flash("Product updated successfully.", "success")
            except Exception as e:
                logger.error(f"Could not update product in Firestore: {e}")
                flash("Failed to update product.", "danger")
            return redirect(url_for("secret_admin"))

        elif action == "delete":
            try:
                pid = int(request.form.get("id"))
            except (ValueError, TypeError):
                flash("Invalid product ID.", "danger")
                return redirect(url_for("secret_admin"))
            try:
                db.collection("products").document(str(pid)).delete()
                logger.info("Product deleted from Firestore")
                flash("Product deleted successfully.", "success")
            except Exception as e:
                logger.error(f"Could not delete product from Firestore: {e}")
                flash("Failed to delete product.", "danger")
            return redirect(url_for("secret_admin"))

        elif action == "remove_image":
            try:
                pid = int(request.form.get("id"))
            except (ValueError, TypeError):
                flash("Invalid product ID.", "danger")
                return redirect(url_for("secret_admin"))
            img_url = request.form.get("img_url")
            product = next((p for p in products if p.get("id") == pid), None)
            if product and img_url in product.get("imgs", []):
                product["imgs"] = [img for img in product.get("imgs", []) if img != img_url]
                try:
                    db.collection("products").document(str(pid)).set(product)
                    logger.info("Product image removed and product updated in Firestore")
                    flash("Image removed successfully.", "success")
                except Exception as e:
                    logger.error(f"Could not update product image in Firestore: {e}")
                    flash("Failed to remove image.", "danger")
            else:
                flash("Image or product not found.", "danger")
            return redirect(url_for("secret_admin"))

        elif action == "replace_image":
            try:
                pid = int(request.form.get("id"))
            except (ValueError, TypeError):
                flash("Invalid product ID.", "danger")
                return redirect(url_for("secret_admin"))
            img_url = request.form.get("img_url")
            product = next((p for p in products if p.get("id") == pid), None)
            if not product:
                flash("Product not found for image replacement.", "danger")
                return redirect(url_for("secret_admin"))
            files = request.files.getlist("replace_img")
            if files and files[0] and files[0].filename and allowed_file(files[0].filename):
                new_img_url = upload_image_and_save_to_firestore(files[0], pid)
                if new_img_url:
                    imgs = product.get("imgs") or []
                    if isinstance(imgs, str):
                        imgs = [imgs]
                    if img_url in imgs:
                        idx = imgs.index(img_url)
                        imgs[idx] = new_img_url
                        product["imgs"] = imgs
                        try:
                            db.collection("products").document(str(pid)).set(product)
                            logger.info("Product image replaced and updated in Firestore")
                            flash("Image replaced successfully.", "success")
                        except Exception as e:
                            logger.error(f"Could not update replaced image in Firestore: {e}")
                            flash("Failed to update image.", "danger")
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
