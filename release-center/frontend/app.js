const by=id=>document.getElementById(id);
const stats=document.createElement('section');
stats.innerHTML='<h2>运行实例</h2><p role="status"></p><button type="button">生成实例接入码</button><output></output>';
by('console').prepend(stats);
const instanceList=document.createElement('ul');stats.append(instanceList);
async function updateInstances(){
  const data=await api('instances');
  stats.querySelector('p').textContent=`当前在线 ${data.online}　·　已登记 ${data.registered}　·　最近 5 分钟`;
  instanceList.replaceChildren(...data.ids.map(id=>{
    const row=document.createElement('li'), button=document.createElement('button');
    row.textContent=`实例 ${id.slice(0,12)}　`;button.textContent='撤销接入';button.type='button';
    button.onclick=async()=>{if(!confirm(`撤销实例 ${id.slice(0,12)} 的接入码？`))return;button.disabled=true;try{await api(`instances/${encodeURIComponent(id)}/revoke`,{method:'POST'});await updateInstances()}catch(e){by('message').textContent=e.message;button.disabled=false}};
    row.append(button);return row;
  }));
}
stats.querySelector('button').onclick=async event=>{const button=event.currentTarget;button.disabled=true;try{const {token}=await api('instances',{method:'POST'});stats.querySelector('output').textContent=`XBOT_INSTANCE_TOKEN=${token}`;await updateInstances()}catch(err){by('message').textContent=err.message}finally{button.disabled=false}};
new MutationObserver(()=>{stats.querySelector('output').textContent='';if(!by('console').hidden)updateInstances().catch(()=>stats.querySelector('p').textContent='统计暂时不可用')}).observe(by('console'),{attributes:true,attributeFilter:['hidden']});
setInterval(()=>{if(!document.hidden&&!by('console').hidden)updateInstances().catch(()=>stats.querySelector('p').textContent='统计暂时不可用')},60000);
async function api(path,options){const r=await fetch('/api/'+path,options);if(!r.ok)throw Error(await r.text());return r.json()}
async function screen(){const ok=await api('session');by('login').hidden=ok;by('console').hidden=!ok;by('logout').hidden=!ok;if(ok){const list=await api('catalog');by('items').replaceChildren(...list.reverse().map(i=>{const li=document.createElement('li');li.textContent=`${i.Name} · ${i.Version} · ${{framework:'框架',plugin:'插件',skill:'技能'}[i.Kind]}　${i.Notes}`;return li}));if(!list.length)by('items').textContent='还没有发布记录。'}}
function submit(id,action){by(id).onsubmit=async e=>{e.preventDefault();const btn=e.submitter;btn.disabled=true;try{await action(new FormData(e.target));e.target.reset();await screen()}catch(err){by('message').textContent=err.message}finally{btn.disabled=false}}}
submit('signin',async d=>{await api('login',{method:'POST',body:JSON.stringify(Object.fromEntries(d))});by('message').textContent=''});
submit('publish',async d=>{const file=d.get('file');d.delete('file');await api('publish?'+new URLSearchParams(d),{method:'POST',body:file});by('message').textContent='版本已发布。'});
by('logout').onclick=async()=>{await api('logout',{method:'POST'});await screen()};screen().catch(e=>by('message').textContent=e.message);
