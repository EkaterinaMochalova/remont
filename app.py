import sqlite3
import os
import uuid
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'remont-vote-secret-2024')
_db_dir = os.environ.get('DB_DIR', os.path.dirname(os.path.abspath(__file__)))
os.makedirs(_db_dir, exist_ok=True)
DB = os.path.join(_db_dir, 'votes.db')

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp', 'gif'}


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            url TEXT,
            price TEXT,
            image_url TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            voter TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
    ''')
    conn.commit()
    conn.close()


def seed_data():
    conn = get_db()
    # Only seed if empty
    if conn.execute('SELECT COUNT(*) FROM categories').fetchone()[0] > 0:
        conn.close()
        return

    items = [
        ('Гостевая ванная', [
            ('Консоль с раковиной DIWO Elista 60', 'https://santehnika-online.ru/product/konsol_s_rakovinoy_diwo_elista_60/1082256/', '', ''),
            ('Консоль с раковиной Belux Tempo 50 L (чёрная)', 'https://santehnika-online.ru/product/konsol_s_rakovinoy_belux_tempo_50_l_podvesnaya_tsvet_konsoli_chernyy_sifon_kvadratnyy_chernyy/1086557/', '', ''),
            ('Тумба с раковиной Velvex Edge 60 подвесная белая', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_velvex_edge_60_1y_podvesnaya_belaya/628650/', '', ''),
            ('Тумба с раковиной DIWO Kazan 50', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_diwo_kazan_50/564294/', '', ''),
            ('Столешница с раковиной DIWO Elista 60 чёрный мрамор', 'https://santehnika-online.ru/product/stoleshnitsa_s_rakovinoy_diwo_elista_60_chyernyy_mramor_s_rakovinoy_moduo_40_ring/554733/', '', ''),
            ('Столешница с раковиной Teymi Helmi 60 дуб кашмир', 'https://santehnika-online.ru/product/stoleshnitsa_s_rakovinoy_teymi_helmi_60_dub_kashmir_rakovina_solli_61_s_chernymi_kronshteynami/1133603/', '', ''),
        ]),
        ('Мастер-ванная', [
            ('Тумба с раковиной AM.PM Func 60 дуб крафт', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_am_pm_func_60_dub_kraft_so_stoleshnitsey_rakovina_m8fwcc20561wg/624261/', '', ''),
            ('Тумба с раковиной Teymi Ritta 65 дуб Эврика / граф. (Iva 52)', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_teymi_ritta_65_dub_evrika_matovyy_grafit_rakovina_iva_52/1042402/', '', ''),
            ('Столешница с раковиной Teymi Helmi 70 дуб кашмир', 'https://santehnika-online.ru/product/stoleshnitsa_s_rakovinoy_teymi_helmi_70_dub_kashmir_rakovina_iva_52_s_chernymi_kronshteynami/1133618/', '', ''),
            ('Тумба с раковиной Teymi Ritta 65 граф. (Lori 50)', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_teymi_ritta_65_dub_evrika_matovyy_grafit_rakovina_lori_50/1042401/', '', ''),
            ('Тумба с раковиной Teymi Ritta 65 граф. (Lori 60)', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_teymi_ritta_65_dub_evrika_matovyy_grafit_rakovina_lori_60/1042406/', '', ''),
            ('Тумба с раковиной 1Marka Vortex 60 орех Носе Найт', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_1marka_vortex_60_orekh_noche_nayt/1038584/', '', ''),
            ('Тумба с раковиной Brevita Dakota 60 дуб Галифакс олово', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_brevita_dakota_60_podvesnaya_dub_galifaks_olovo_belyy/722232/', '', ''),
            ('Тумба с раковиной Runo Ницца 60 тёмное дерево (Cuatro 50)', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_runo_nitstsa_60_temnoe_derevo_belaya_rakovina_cuatro_50/669502/', '', ''),
            ('Тумба с раковиной Runo Ницца 60 дуб натуральный / граф. (Cuatro 50)', 'https://santehnika-online.ru/product/tumba_s_rakovinoy_runo_nitstsa_60_dub_naturalnyy_grafit_rakovina_cuatro_50/669431/', '', ''),
        ]),
    ]

    for cat_name, products in items:
        cat_id = conn.execute('INSERT INTO categories (name) VALUES (?)', (cat_name,)).lastrowid
        for name, url, price, image_url in products:
            conn.execute('INSERT INTO products (category_id, name, url, price, image_url) VALUES (?,?,?,?,?)',
                         (cat_id, name, url, price, image_url))
    conn.commit()
    conn.close()


@app.route('/')
def index():
    voter = session.get('voter', '')
    conn = get_db()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    result = []
    for cat in cats:
        products = conn.execute('''
            SELECT p.*, COUNT(v.id) as vote_count,
                   SUM(CASE WHEN v.voter=? THEN 1 ELSE 0 END) as my_vote
            FROM products p
            LEFT JOIN votes v ON v.product_id = p.id
            WHERE p.category_id = ?
            GROUP BY p.id ORDER BY p.id
        ''', (voter, cat['id'])).fetchall()
        result.append({'cat': cat, 'products': products})
    conn.close()
    return render_template('index.html', data=result, voter=voter)


@app.route('/set_voter', methods=['POST'])
def set_voter():
    name = request.form.get('name', '').strip()
    if name:
        session['voter'] = name
    return redirect(url_for('index'))


@app.route('/vote', methods=['POST'])
def vote():
    voter = session.get('voter', '')
    if not voter:
        return jsonify({'error': 'Представься сначала'}), 400
    product_id = int(request.json.get('product_id'))
    conn = get_db()
    existing = conn.execute('SELECT id FROM votes WHERE product_id=? AND voter=?', (product_id, voter)).fetchone()
    if existing:
        conn.execute('DELETE FROM votes WHERE id=?', (existing['id'],))
        voted = False
    else:
        conn.execute('INSERT INTO votes (product_id, voter) VALUES (?,?)', (product_id, voter))
        voted = True
    count = conn.execute('SELECT COUNT(*) FROM votes WHERE product_id=?', (product_id,)).fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'voted': voted, 'count': count})


@app.route('/api/products/<int:cat_id>')
def api_products(cat_id):
    conn = get_db()
    products = conn.execute('SELECT * FROM products WHERE category_id=? ORDER BY id', (cat_id,)).fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])


@app.route('/admin')
def admin():
    import json
    conn = get_db()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    cats_list = [dict(c) for c in cats]
    conn.close()
    return render_template('admin.html', cats=cats, cats_json=json.dumps(cats_list, ensure_ascii=False))


@app.route('/admin/add_category', methods=['POST'])
def add_category():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db()
        conn.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (name,))
        conn.commit()
        conn.close()
    return redirect(url_for('admin'))


@app.route('/admin/add_product', methods=['POST'])
def add_product():
    cat_id = int(request.form.get('category_id'))
    name = request.form.get('name', '').strip()
    url = request.form.get('url', '').strip()
    price = request.form.get('price', '').strip()
    image_url = request.form.get('image_url', '').strip()
    if name and cat_id:
        conn = get_db()
        conn.execute('INSERT INTO products (category_id, name, url, price, image_url) VALUES (?,?,?,?,?)',
                     (cat_id, name, url, price, image_url))
        conn.commit()
        conn.close()
    return redirect(url_for('admin'))


@app.route('/admin/edit_product/<int:pid>', methods=['POST'])
def edit_product(pid):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE products SET name=?, price=?, image_url=? WHERE id=?',
                 (data['name'], data['price'], data['image_url'], pid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/delete_product/<int:pid>', methods=['POST'])
def delete_product(pid):
    conn = get_db()
    conn.execute('DELETE FROM votes WHERE product_id=?', (pid,))
    conn.execute('DELETE FROM products WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/upload_image/<int:pid>', methods=['POST'])
def upload_image(pid):
    f = request.files.get('image')
    if not f:
        return jsonify({'error': 'no file'}), 400
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({'error': 'bad ext'}), 400
    filename = f'{uuid.uuid4().hex}.{ext}'
    f.save(os.path.join(UPLOAD_DIR, filename))
    image_url = url_for('static', filename=f'uploads/{filename}')
    conn = get_db()
    conn.execute('UPDATE products SET image_url=? WHERE id=?', (image_url, pid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'image_url': image_url})


init_db()
seed_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
