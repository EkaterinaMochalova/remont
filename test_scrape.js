const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    locale: 'ru-RU',
    viewport: { width: 1280, height: 900 },
  });
  const urls = [
    'https://santehnika-online.ru/product/konsol_s_rakovinoy_diwo_elista_60/1082256/',
    'https://www.ozon.ru/product/mideon-zerkalo-nastennoe-s-podsvetkoy-v-vannuyu-asimmetrichnoe-3000k-d-80-1-sht-2007477506/',
  ];
  for (const u of urls) {
    const page = await ctx.newPage();
    try {
      await page.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForTimeout(8000);
      const ogImage = await page.getAttribute('meta[property="og:image"]', 'content').catch(()=>null);
      const title = await page.title();
      const bodyLen = (await page.content()).length;
      console.log('URL:', u.slice(0,60));
      console.log('  title:', title.slice(0,80));
      console.log('  bodyLen:', bodyLen);
      console.log('  ogImage:', ogImage);
    } catch (e) {
      console.log('URL:', u.slice(0,60), 'ERR', e.message);
    }
    await page.close();
  }
  await browser.close();
})();
