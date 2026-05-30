const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const products = JSON.parse(fs.readFileSync('/tmp/products.json', 'utf8'));
const UPLOAD_DIR = path.join(__dirname, 'static', 'uploads');
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36';

function extEfrom(url) {
  const m = (url.split('?')[0].match(/\.(jpg|jpeg|png|webp|gif)$/i));
  return m ? m[1].toLowerCase() : 'jpg';
}

async function scrapeSantehnika(page, p) {
  await page.goto(p.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  // wait for servicepipe JS challenge to resolve
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(2500);
    const t = await page.title().catch(() => '');
    if (t && !/servicepipe|загрузк|loading/i.test(t) && t.length > 5) break;
  }
  const title = await page.title().catch(() => '');
  const og = await page.getAttribute('meta[property="og:image"]', 'content').catch(() => null);
  let price = null;
  // price often in title: "купить по цене 10650 рублей"
  let m = title.match(/по цене\s+([\d\s]+)\s*руб/i);
  if (m) price = m[1].replace(/\s/g, '').trim();
  if (!price) {
    // try meta / itemprop / json-ld
    price = await page.evaluate(() => {
      const meta = document.querySelector('meta[itemprop="price"], meta[property="product:price:amount"]');
      if (meta && meta.content) return meta.content.replace(/[^\d]/g, '');
      for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
        try {
          const d = JSON.parse(s.textContent);
          const arr = Array.isArray(d) ? d : [d];
          for (const o of arr) {
            const offers = o.offers && (Array.isArray(o.offers) ? o.offers[0] : o.offers);
            if (offers && offers.price) return String(offers.price).replace(/[^\d]/g, '');
          }
        } catch (e) {}
      }
      return null;
    }).catch(() => null);
  }
  return { og, price: price ? price + ' ₽' : '' };
}

async function scrapeOzon(page, p) {
  let og = null, price = null;
  for (let attempt = 0; attempt < 4; attempt++) {
    await page.goto(p.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(6000);
    const title = await page.title().catch(() => '');
    if (!og) og = await page.getAttribute('meta[property="og:image"]', 'content').catch(() => null);
    if (!/antibot|captcha/i.test(title)) {
      // try to read price from JSON-LD or DOM
      price = await page.evaluate(() => {
        for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
          try {
            const d = JSON.parse(s.textContent);
            const arr = Array.isArray(d) ? d : [d];
            for (const o of arr) {
              const offers = o.offers && (Array.isArray(o.offers) ? o.offers[0] : o.offers);
              if (offers && offers.price) return String(offers.price).replace(/[^\d]/g, '');
            }
          } catch (e) {}
        }
        // ozon price spans often contain "₽"
        const el = [...document.querySelectorAll('span,div')].find(e => /\d[\d\s]*₽/.test(e.textContent) && e.children.length === 0);
        if (el) { const mm = el.textContent.match(/([\d\s]+)₽/); if (mm) return mm[1].replace(/\s/g, ''); }
        return null;
      }).catch(() => null);
      if (price) break;
    }
    await page.waitForTimeout(2000);
  }
  return { og, price: price ? price + ' ₽' : '' };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ userAgent: UA, locale: 'ru-RU', viewport: { width: 1366, height: 900 } });
  await ctx.addInitScript(() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); });
  const results = [];
  for (const p of products) {
    const page = await ctx.newPage();
    let r = { og: null, price: '' };
    try {
      if (p.url.includes('ozon.ru')) r = await scrapeOzon(page, p);
      else r = await scrapeSantehnika(page, p);
    } catch (e) {
      console.error('SCRAPE ERR', p.id, e.message);
    }
    let localPath = '';
    if (r.og) {
      try {
        const resp = await ctx.request.get(r.og, { headers: { 'User-Agent': UA, 'Referer': p.url }, timeout: 60000 });
        if (resp.ok()) {
          const buf = await resp.body();
          const ext = extEfrom(r.og);
          const fname = `prod_${p.id}.${ext}`;
          fs.writeFileSync(path.join(UPLOAD_DIR, fname), buf);
          localPath = `/static/uploads/${fname}`;
        }
      } catch (e) { console.error('DL ERR', p.id, e.message); }
    }
    results.push({ id: p.id, image_url: localPath, price: r.price, og: r.og });
    console.log(`#${p.id} price="${r.price}" img=${localPath ? 'OK' : 'FAIL'} ${p.name.slice(0, 30)}`);
    await page.close();
  }
  await browser.close();
  fs.writeFileSync('/tmp/results.json', JSON.stringify(results, null, 2));
  console.log('DONE');
})();
