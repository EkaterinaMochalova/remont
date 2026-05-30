const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const all = JSON.parse(fs.readFileSync('/tmp/products.json', 'utf8'));
const ids = JSON.parse(process.argv[2] || '[20,21]');
const targets = all.filter(p => ids.includes(p.id));
const UPLOAD_DIR = path.join(__dirname, 'static', 'uploads');
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36';
const ext = u => { const m = u.split('?')[0].match(/\.(jpg|jpeg|png|webp|gif)$/i); return m ? m[1].toLowerCase() : 'jpg'; };

async function priceFrom(page) {
  return page.evaluate(() => {
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(s.textContent); const arr = Array.isArray(d) ? d : [d];
        for (const o of arr) { const of_ = o.offers && (Array.isArray(o.offers) ? o.offers[0] : o.offers); if (of_ && of_.price) return String(of_.price).replace(/[^\d]/g, ''); }
      } catch (e) {}
    }
    const el = [...document.querySelectorAll('span,div')].find(e => /\d[\d\s]*₽/.test(e.textContent) && e.children.length === 0);
    if (el) { const mm = el.textContent.match(/([\d\s]+)₽/); if (mm) return mm[1].replace(/\s/g, ''); }
    return null;
  }).catch(() => null);
}

(async () => {
  const out = [];
  for (const p of targets) {
    let og = null, price = null;
    for (let attempt = 0; attempt < 6 && !(og && price); attempt++) {
      const browser = await chromium.launch({ headless: true });
      const ctx = await browser.newContext({ userAgent: UA, locale: 'ru-RU', viewport: { width: 1366, height: 900 } });
      await ctx.addInitScript(() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); });
      const page = await ctx.newPage();
      try {
        await page.goto(p.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
        for (let i = 0; i < 5; i++) {
          await page.waitForTimeout(4000);
          if (!og) og = await page.getAttribute('meta[property="og:image"]', 'content').catch(() => null);
          const title = await page.title().catch(() => '');
          if (!/antibot|captcha/i.test(title) && title.length > 3) {
            const pr = await priceFrom(page); if (pr) { price = pr; }
            if (!og) og = await page.getAttribute('meta[property="og:image"]', 'content').catch(() => null);
            if (price) break;
          }
        }
      } catch (e) { console.error('ERR', p.id, e.message); }
      console.error(`#${p.id} attempt ${attempt}: og=${!!og} price=${price}`);
      await browser.close();
    }
    let localPath = '';
    if (og) {
      const browser = await chromium.launch({ headless: true });
      const ctx = await browser.newContext({ userAgent: UA });
      try {
        const resp = await ctx.request.get(og, { headers: { 'User-Agent': UA, 'Referer': p.url }, timeout: 60000 });
        if (resp.ok()) { fs.writeFileSync(path.join(UPLOAD_DIR, `prod_${p.id}.${ext(og)}`), await resp.body()); localPath = `/static/uploads/prod_${p.id}.${ext(og)}`; }
      } catch (e) { console.error('DL ERR', e.message); }
      await browser.close();
    }
    const rec = { id: p.id, image_url: localPath, price: price ? price + ' ₽' : '', og };
    out.push(rec);
    fs.writeFileSync(`/tmp/result_${p.id}.json`, JSON.stringify(rec));
    console.log(`#${p.id} price="${price || ''}" img=${localPath ? 'OK' : 'FAIL'}`);
  }
  console.log('DONE');
})();
