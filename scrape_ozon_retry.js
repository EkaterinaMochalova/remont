const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const all = JSON.parse(fs.readFileSync('/tmp/products.json', 'utf8'));
const ids = JSON.parse(process.argv[2] || '[20,21]');
const targets = all.filter(p => ids.includes(p.id));
const UPLOAD_DIR = path.join(__dirname, 'static', 'uploads');
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36';

function extEfrom(url) {
  const m = (url.split('?')[0].match(/\.(jpg|jpeg|png|webp|gif)$/i));
  return m ? m[1].toLowerCase() : 'jpg';
}

async function extract(page) {
  return page.evaluate(() => {
    let og = null, price = null;
    const m = document.querySelector('meta[property="og:image"]');
    if (m) og = m.content;
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(s.textContent);
        const arr = Array.isArray(d) ? d : [d];
        for (const o of arr) {
          const offers = o.offers && (Array.isArray(o.offers) ? o.offers[0] : o.offers);
          if (offers && offers.price) price = String(offers.price).replace(/[^\d]/g, '');
          if (!og && o.image) og = Array.isArray(o.image) ? o.image[0] : o.image;
        }
      } catch (e) {}
    }
    if (!price) {
      const el = [...document.querySelectorAll('span,div')].find(e => /\d[\d\s]*₽/.test(e.textContent) && e.children.length === 0);
      if (el) { const mm = el.textContent.match(/([\d\s]+)₽/); if (mm) price = mm[1].replace(/\s/g, ''); }
    }
    return { og, price };
  }).catch(() => ({ og: null, price: null }));
}

(async () => {
  const out = [];
  for (const p of targets) {
    let og = null, price = null;
    for (let attempt = 0; attempt < 8 && !(og && price); attempt++) {
      let browser;
      try {
        browser = await chromium.launch({ headless: false, channel: 'chrome',
          args: ['--disable-blink-features=AutomationControlled'] });
        const ctx = await browser.newContext({ userAgent: UA, locale: 'ru-RU', viewport: { width: 1366, height: 900 } });
        await ctx.addInitScript(() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); });
        const page = await ctx.newPage();
        await page.goto(p.url, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
        for (let i = 0; i < 6; i++) {
          await page.waitForTimeout(4000).catch(() => {});
          await page.mouse.move(300 + i * 50, 300 + i * 30).catch(() => {});
          const title = await page.title().catch(() => '');
          if (!/antibot|captcha|ozon/i.test(title) || title.length > 25) {
            const r = await extract(page);
            if (r.og) og = r.og;
            if (r.price) price = r.price;
            if (og && price) break;
          }
        }
      } catch (e) { console.error('ERR', p.id, e.message); }
      try { if (browser) await browser.close(); } catch (e) {}
      console.error(`#${p.id} attempt ${attempt}: og=${!!og} price=${price}`);
    }
    let localPath = '';
    if (og) {
      let b2;
      try {
        b2 = await chromium.launch({ headless: true });
        const c2 = await b2.newContext({ userAgent: UA });
        const resp = await c2.request.get(og, { headers: { 'User-Agent': UA, 'Referer': p.url }, timeout: 60000 });
        if (resp.ok()) {
          const fname = `prod_${p.id}.${extEfrom(og)}`;
          fs.writeFileSync(path.join(UPLOAD_DIR, fname), await resp.body());
          localPath = `/static/uploads/${fname}`;
        }
      } catch (e) { console.error('DL ERR', p.id, e.message); }
      try { if (b2) await b2.close(); } catch (e) {}
    }
    const rec = { id: p.id, image_url: localPath, price: price ? price + ' ₽' : '', og };
    out.push(rec);
    fs.writeFileSync(`/tmp/result_${p.id}.json`, JSON.stringify(rec));
    console.log(`#${p.id} price="${price || ''}" img=${localPath ? 'OK' : 'FAIL'}`);
  }
  fs.writeFileSync('/tmp/results_ozon.json', JSON.stringify(out, null, 2));
  console.log('DONE');
})();
