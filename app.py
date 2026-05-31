import sqlite3
import os
import json
import re
import uuid
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'remont-vote-secret-2024')
_db_dir = os.environ.get('DB_DIR', os.path.dirname(os.path.abspath(__file__)))
os.makedirs(_db_dir, exist_ok=True)
DB = os.path.join(_db_dir, 'votes.db')

# If using external volume and DB is empty/missing, seed from bundled DB in repo
_bundled_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'votes.db')
if _db_dir != os.path.dirname(os.path.abspath(__file__)) and not os.path.exists(DB) and os.path.exists(_bundled_db):
    import shutil
    shutil.copy2(_bundled_db, DB)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/124.0 Safari/537.36'
}


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_bundled_db():
    conn = sqlite3.connect(_bundled_db)
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


def clean_text(value):
    if not value:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def format_price(value):
    if not value:
        return ''
    digits = re.sub(r'[^\d]', '', str(value))
    if not digits:
        return clean_text(value)
    return f'{int(digits):,}'.replace(',', ' ') + ' ₽'


def first_meta(soup, selectors):
    for selector, attr in selectors:
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            return clean_text(tag.get(attr))
    return ''


def find_jsonld_price_and_image(soup):
    result = {'price': '', 'image_url': '', 'name': ''}
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
        except (TypeError, json.JSONDecodeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            stack.extend(v for v in item.values() if isinstance(v, dict))
            for value in item.values():
                if isinstance(value, list):
                    stack.extend(value)
            offers = item.get('offers')
            if not result['name'] and item.get('name'):
                result['name'] = clean_text(item.get('name'))
            if not result['image_url'] and item.get('image'):
                image = item.get('image')
                result['image_url'] = clean_text(image[0] if isinstance(image, list) else image)
            if not result['price'] and isinstance(offers, dict) and offers.get('price'):
                result['price'] = format_price(offers.get('price'))
            if not result['price'] and isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict) and offer.get('price'):
                        result['price'] = format_price(offer.get('price'))
                        break
    return result


def fetch_product_info(url):
    if not url:
        return {'name': '', 'price': '', 'image_url': ''}

    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=12)
        resp.raise_for_status()
    except requests.RequestException:
        bundled = fetch_bundled_product_info(url)
        if any(bundled.values()):
            return bundled
        raise

    if 'Forbidden' in resp.text[:1000]:
        bundled = fetch_bundled_product_info(url)
        if any(bundled.values()):
            return bundled

    parsed = parse_product_html(url, resp.text)
    if any(parsed.values()):
        return parsed
    return fetch_bundled_product_info(url)


def parse_product_html(url, html):
    soup = BeautifulSoup(html, 'html.parser')
    jsonld = find_jsonld_price_and_image(soup)

    name = (
        first_meta(soup, [
            ('meta[property="og:title"]', 'content'),
            ('meta[name="twitter:title"]', 'content'),
        ])
        or jsonld['name']
        or clean_text(soup.title.string if soup.title else '')
    )
    price = (
        first_meta(soup, [
            ('meta[itemprop="price"]', 'content'),
            ('meta[property="product:price:amount"]', 'content'),
            ('meta[property="og:price:amount"]', 'content'),
        ])
        or jsonld['price']
    )
    image_url = (
        first_meta(soup, [
            ('meta[property="og:image"]', 'content'),
            ('meta[name="twitter:image"]', 'content'),
            ('meta[itemprop="image"]', 'content'),
        ])
        or jsonld['image_url']
    )

    if price:
        price = format_price(price)
    else:
        match = re.search(r'(\d[\d\s]{2,})\s*(?:₽|руб)', soup.get_text(' ', strip=True), re.IGNORECASE)
        price = format_price(match.group(1)) if match else ''

    return {
        'name': name,
        'price': price,
        'image_url': urljoin(url, image_url) if image_url else '',
    }


def fetch_bundled_product_info(url):
    if not url or not os.path.exists(_bundled_db):
        return {'name': '', 'price': '', 'image_url': ''}
    conn = get_bundled_db()
    row = conn.execute(
        'SELECT name, price, image_url FROM products WHERE url=?',
        (url,)
    ).fetchone()
    conn.close()
    if not row:
        return {'name': '', 'price': '', 'image_url': ''}
    return {
        'name': row['name'] or '',
        'price': row['price'] or '',
        'image_url': row['image_url'] or '',
    }


def sync_bundled_products():
    if not os.path.exists(_bundled_db) or os.path.abspath(_bundled_db) == os.path.abspath(DB):
        return {'categories': 0, 'inserted': 0, 'updated': 0}

    source = get_bundled_db()
    target = get_db()
    target.execute('PRAGMA busy_timeout = 1000')
    stats = {'categories': 0, 'inserted': 0, 'updated': 0}

    try:
        rows = source.execute('''
            SELECT c.name AS category_name, p.name, p.url, p.price, p.image_url
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE COALESCE(p.url, '') <> ''
            ORDER BY p.id
        ''').fetchall()

        for row in rows:
            category = target.execute(
                'SELECT id FROM categories WHERE name=?',
                (row['category_name'],)
            ).fetchone()
            if category:
                category_id = category['id']
            else:
                category_id = target.execute(
                    'INSERT INTO categories (name) VALUES (?)',
                    (row['category_name'],)
                ).lastrowid
                stats['categories'] += 1

            existing = target.execute(
                'SELECT id FROM products WHERE url=?',
                (row['url'],)
            ).fetchone()
            if existing:
                target.execute('''
                    UPDATE products
                    SET category_id=?,
                        name=?,
                        price=COALESCE(NULLIF(?, ''), price),
                        image_url=COALESCE(NULLIF(?, ''), image_url)
                    WHERE id=?
                ''', (category_id, row['name'], row['price'], row['image_url'], existing['id']))
                stats['updated'] += 1
            else:
                target.execute('''
                    INSERT INTO products (category_id, name, url, price, image_url)
                    VALUES (?, ?, ?, ?, ?)
                ''', (category_id, row['name'], row['url'], row['price'], row['image_url']))
                stats['inserted'] += 1

        target.commit()
        return stats
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()
        source.close()


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
    conn = get_db()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    cats_list = [dict(c) for c in cats]
    conn.close()
    return render_template('admin.html', cats=cats, cats_json=json.dumps(cats_list, ensure_ascii=False))


@app.route('/admin/rename_category/<int:cid>', methods=['POST'])
def rename_category(cid):
    name = request.json.get('name', '').strip()
    if name:
        conn = get_db()
        conn.execute('UPDATE categories SET name=? WHERE id=?', (name, cid))
        conn.commit()
        conn.close()
    return jsonify({'ok': True})


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
    if url and (not price or not image_url or not name):
        try:
            info = fetch_product_info(url)
            name = name or info['name']
            price = price or info['price']
            image_url = image_url or info['image_url']
        except requests.RequestException:
            pass
    if name and cat_id:
        conn = get_db()
        existing = conn.execute('SELECT id FROM products WHERE url=? AND url<>""', (url,)).fetchone() if url else None
        if existing:
            conn.execute('''
                UPDATE products
                SET category_id=?, name=?, url=?, price=?, image_url=?
                WHERE id=?
            ''', (cat_id, name, url, price, image_url, existing['id']))
        else:
            conn.execute('INSERT INTO products (category_id, name, url, price, image_url) VALUES (?,?,?,?,?)',
                         (cat_id, name, url, price, image_url))
        conn.commit()
        conn.close()
    return redirect(url_for('admin'))


@app.route('/admin/fetch_product_info', methods=['POST'])
def fetch_product_info_route():
    url = (request.json or {}).get('url', '').strip()
    if not url:
        return jsonify({'error': 'Добавь ссылку на товар'}), 400
    try:
        info = fetch_product_info(url)
    except requests.RequestException:
        return jsonify({'error': 'Не получилось получить данные по ссылке'}), 502
    if not any(info.values()):
        return jsonify({'error': 'По этой ссылке не нашлись фото или цена'}), 404
    return jsonify({'ok': True, **info})


@app.route('/admin/sync_bundled_products', methods=['POST'])
def sync_bundled_products_route():
    try:
        stats = sync_bundled_products()
    except sqlite3.Error as exc:
        return jsonify({'error': f'Не получилось обновить базу: {exc}'}), 500
    return jsonify({'ok': True, **stats})


@app.route('/admin/edit_product/<int:pid>', methods=['POST'])
def edit_product(pid):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE products SET name=?, url=?, price=?, image_url=? WHERE id=?',
                 (data['name'], data.get('url', ''), data['price'], data['image_url'], pid))
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
