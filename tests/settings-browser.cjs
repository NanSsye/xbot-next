// Requires an explicitly supplied Playwright installation and local mock preview.
const {chromium}=require(process.env.PLAYWRIGHT_PATH || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
  const url='http://127.0.0.1:15197';
  const browser=await chromium.launch({channel:'chrome'});
  try {
    const p=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
    const errors=[];p.on('pageerror',e=>errors.push(e.message));
    const {data:snapshot}=await (await p.request.get(`${url}/api/v1/config`)).json();
    const fields=new Map(snapshot.sections.flatMap(s=>s.fields).map(f=>[f.path,f]));
    fields.get('agent.llm.api_key').configured=false;
    let writes=[],attempts=0;
    await p.route('**/api/v1/config',async r=>{
      if(r.request().method()==='GET')return r.fulfill({json:{success:true,data:snapshot}});
      const {changes}=r.request().postDataJSON();writes.push(changes.map(c=>c.path));
      for(const c of changes){const f=fields.get(c.path);if(f.secret)f.configured=true;else f.value=c.value;}
      return r.fulfill({json:{success:true,data:{snapshot,applied:writes.at(-1),restart_required:[]}}});
    });
    await p.route('**/llm/models/discover',r=>++attempts===1?r.fulfill({status:503,json:{detail:'模拟服务不可用'}}):r.fulfill({json:{success:true,data:{models:['demo-reasoning']}}}));
    await p.goto(url);await p.getByText('控制台设置',{exact:true}).first().click();
    const button=name=>p.getByRole('button',{name,exact:true});
    const confirm=()=>Promise.all([p.waitForResponse(r=>r.url().endsWith('/api/v1/config')&&r.request().method()==='PUT'),button('确认保存并应用').click()]);
    await button('连接模型服务').click();await p.getByLabel('访问密钥',{exact:true}).fill('mock-only');
    await button('保存连接并获取模型').click();await confirm();await button('重试获取模型').click();await button('选择默认模型 ›').click();
    const input=p.getByRole('combobox',{name:'默认对话模型',exact:true});await input.fill('demo-reasoning');await button('保存并应用').click();await confirm();
    assert.deepEqual(writes,[['agent.llm.api_key'],['agent.llm.model']]);assert.equal(attempts,2);
    await button('检查开关').click();await p.locator('#config-field-agent-llm-enabled-control').click();await button('保存并应用').click();await confirm();await button('去试聊').waitFor();
    await p.locator('.settings-rows button').filter({hasText:'默认对话模型'}).click();await input.fill('new-model');await p.keyboard.press('Escape');await button('继续编辑').click();assert.equal(await input.inputValue(),'new-model');
    await p.keyboard.press('Escape');await p.getByRole('dialog',{name:'放弃未保存的修改？'}).getByText('放弃修改',{exact:true}).click();assert.equal(writes.length,3);
    await p.setViewportSize({width:390,height:844});await p.getByRole('searchbox',{name:'搜索全部设置'}).fill('server.port');await p.locator('.settings-rows button').click();
    const rect=await p.locator('.settings-drawer').boundingBox();assert.equal(rect.width,390);assert.equal(rect.x,0);
    await p.keyboard.press('Escape');await button('控制台偏好').click();await button('跟随系统').waitFor();await button('高级管理').click();await p.getByText('数据库',{exact:true}).last().waitFor();
    await button('AI 对话').click();await button('去试聊').click();await p.locator('.agent-stage').waitFor();assert.deepEqual(errors,[]);console.log('PASS: isolated writes, discovery retry, model switch, enable, discard, search, mobile drawer, preferences, advanced, chat');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
