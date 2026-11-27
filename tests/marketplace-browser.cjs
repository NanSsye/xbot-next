const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = process.env.XBOT_UI_URL || 'http://127.0.0.1:5173';
  const browser = await chromium.launch({channel:'chrome'});
  try {
    const page = await browser.newPage();
    let calls = 0;
    await page.route('**/api/v1/skills/catalog', route => ++calls === 1
      ? route.fulfill({status:503, body:'offline'})
      : route.fulfill({json:{success:true,data:[{Kind:'plugin', Name:'测试插件', Version:'1', Digest:'a'.repeat(64), Notes:''}]}}));
    await page.goto(`${base}/#/extensions`);
    await page.getByRole('button',{name:'本机插件',exact:true}).waitFor();
    assert.equal(calls,0);
    await page.getByText('官方市场',{exact:true}).first().click();
    await page.getByRole('button',{name:'重试',exact:true}).click();
    await page.getByRole('link',{name:'下载发行包'}).waitFor();
    await page.getByRole('button',{name:'技能',exact:true}).click();
    await page.getByText('暂无已发布的官方技能').waitFor();
    await page.reload();
    await page.getByRole('heading',{name:'官方市场',exact:true}).waitFor();
    await page.goBack();
    await page.getByRole('button',{name:'本机插件',exact:true}).waitFor();
    console.log('PASS: separate navigation, local isolation, retry, filtering, refresh and back');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode=1; });
