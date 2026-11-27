const {chromium} = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome'});
  try {
    const page = await browser.newPage();
    let available = true, writes = 0;
    await page.route('**/api/v1/**', route => {
      if(route.request().method() !== 'GET') writes++;
      return route.fulfill({json:{success:true,data:route.request().url().endsWith('/framework-update') ? {available} : []}});
    });
    await page.goto(process.env.XBOT_UI_URL || 'http://127.0.0.1:5189');
    const badge = page.locator('.sidebar__brand-name .frontend-version');
    await badge.locator('.update-dot').waitFor();
    available = false; await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
    await badge.locator('.update-dot').waitFor({state:'detached'});
    assert.equal(writes,0);
    await page.route('**/media/wechat869/media/demo.png', route=>route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=','base64')}));
    await page.evaluate(async()=>{
      const {WechatBubble}=await import('/src/ui/WechatBubble.tsx');
      const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;
      const {createElement}=(await import('/node_modules/.vite/deps/react.js')).default;
      const root=document.createElement('main');document.body.prepend(root);
      const image={id:1,kind:'image',url:'/media/wechat869/media/demo.png'};
      createRoot(root).render(createElement('section',{},...[
        {content:'[图片]',attachments:[image]},
        {content:'看看这张图\n[引用图片] filename=example.jpg size=99 status=downloaded',raw:{quote:{sender_name:'测试用户'}},attachments:[{...image,quoted:true}]},
        {type:'image',content:'[图片]',attachments:[]},
      ].map((message,key)=>createElement(WechatBubble,{message,key}))));
    });
    await page.waitForFunction(()=>[...document.querySelectorAll('.wechat-photo')].filter(i=>i.naturalWidth>0).length===2);
    assert.match(await page.locator('.wechat-quote').innerText(),/引用 · 测试用户/);
    assert.equal(await page.getByText(/filename=example/).count(),0);
    await page.getByText('图片暂不可用',{exact:true}).waitFor();
    console.log('PASS: thumbnail decode, quote, fallback, brand badge and read-only update checks');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
