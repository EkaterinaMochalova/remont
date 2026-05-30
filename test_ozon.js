const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: false, channel: 'chrome',
    args: ['--disable-blink-features=AutomationControlled'] });
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    locale: 'ru-RU', viewport: { width: 1366, height: 900 },
  });
  await ctx.addInitScript(() => { Object.defineProperty(navigator, 'webdriver', {get:()=>undefined}); });
  const page = await ctx.newPage();
  const u = 'https://www.ozon.ru/product/mideon-zerkalo-nastennoe-s-podsvetkoy-v-vannuyu-asimmetrichnoe-3000k-d-80-1-sht-2007477506/';
  await page.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 });
  for (let i=0;i<6;i++){
    await page.waitForTimeout(5000);
    const t = await page.title();
    const og = await page.getAttribute('meta[property="og:image"]','content').catch(()=>null);
    console.log('iter',i,'title:',t.slice(0,60),'og:',og?og.slice(0,70):null);
    if (og || !/antibot|captcha/i.test(t)) break;
  }
  await browser.close();
})();
