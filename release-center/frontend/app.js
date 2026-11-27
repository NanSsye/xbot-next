const $=id=>document.getElementById(id);
const pages={overview:'运行总览',framework:'框架版本',plugin:'插件管理',skill:'技能管理',instances:'运行实例'};
const kinds={framework:'框架',plugin:'插件',skill:'技能'};
let items=[],devices={online:0,registered:0,ids:[]},ready=false;
const view=()=>Object.hasOwn(pages,location.hash.slice(1))?location.hash.slice(1):'overview';
const el=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n};
async function api(path,options){const r=await fetch('/api/'+path,options);if(!r.ok)throw Error(r.status===401?'登录已失效，请重新登录。':await r.text());return r.json()}
function report(e){$('message').textContent=e.message}
async function load(){[items,devices]=await Promise.all([api('catalog'),api('instances')]);ready=true;render()}
const nav=document.querySelector('nav');for(const [key,name] of Object.entries(pages)){const a=el('a',name);a.href='#'+key;nav.append(a)}
function render(){
  const key=view(),isKind=Object.hasOwn(kinds,key),instance=key==='instances';
  $('position').textContent=$('title').textContent=pages[key];$('summary').textContent=instance?'最近 5 分钟收到心跳的实例计为在线。':isKind?'官方发行记录':'发行目录与实例运行状态';
  for(const a of nav.children){if(a.hash==='#'+key)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')}
  $('action').hidden=key==='overview'||!ready;$('action').textContent=instance?'登记实例':`发布${kinds[key]||''}`;
  const m=$('metrics');m.replaceChildren();if(!ready){$('rows').textContent='正在读取后台数据…';return}
  if(key==='overview')for(const [dest,label,value] of [['instances','在线实例',devices.online],...Object.keys(kinds).map(k=>[k,kinds[k]+'发行版',items.filter(i=>i.Kind===k).length])]){
    const a=el('a');a.className='metric';a.href='#'+dest;a.append(el('span',label),el('strong',value));m.append(a);
  }
  $('listTitle').textContent=instance?`已登记实例 · ${devices.registered}`:isKind?'版本记录':'最近发布';
  const q=$('search').value.trim().toLowerCase();$('search').placeholder=instance?'搜索实例编号':'搜索名称或版本';
  const rows=instance?devices.ids.filter(id=>id.includes(q)).map(id=>{
    const b=el('button','撤销接入');b.className='secondary';b.onclick=async()=>{if(!confirm(`撤销实例 ${id.slice(0,12)}？`))return;try{await api(`instances/${id}/revoke`,{method:'POST'});await load()}catch(e){report(e)}};return [id.slice(0,12),b];
  }):items.slice().reverse().filter(i=>(!isKind||i.Kind===key)&&`${i.Name} ${i.Version}`.toLowerCase().includes(q)).map(i=>[i.Name,kinds[i.Kind],i.Version,i.Notes||'—']);
  const box=$('rows');box.replaceChildren();if(!rows.length){const p=el('p',q?'没有匹配的记录':instance?'暂无登记实例':'暂无发行记录');p.className='empty';box.append(p);return}
  const table=el('table'),head=table.createTHead().insertRow(),body=table.createTBody();for(const t of instance?['实例编号','操作']:['名称','类别','版本','更新说明'])head.append(el('th',t));for(const row of rows){const tr=body.insertRow();for(const v of row)tr.insertCell().append(v)}box.append(table);
}
async function screen(){const ok=await api('session');$('console').hidden=!ok;$('login').hidden=ok;if(ok){render();await load()}else{ready=false;items=[];devices={online:0,registered:0,ids:[]}}}
window.onhashchange=()=>{$('search').value='';$('message').textContent='';if($('drawer').open)$('drawer').close();render()};$('search').oninput=render;
$('signin').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{await api('login',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});e.target.reset();$('message').textContent='';await screen()}catch(err){report(err)}finally{b.disabled=false}};
$('logout').onclick=async()=>{try{await api('logout',{method:'POST'});$('message').textContent='';await screen()}catch(e){report(e)}};
$('action').onclick=async()=>{if(view()==='instances'){if(!confirm('为一套新部署生成独立的接入码？'))return;try{const {token}=await api('instances',{method:'POST'});window.prompt('仅显示一次：此实例的环境变量',`XBOT_INSTANCE_TOKEN=${token}`);await load()}catch(e){report(e)}return} $('drawerTitle').textContent=`发布${kinds[view()]}`;$('publishError').textContent='';$('drawer').showModal()};
$('close').onclick=()=>$('drawer').close();$('publish').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const d=new FormData(e.target),file=d.get('file');d.delete('file');d.set('kind',view());await api('publish?'+new URLSearchParams(d),{method:'POST',body:file});$('drawer').close();e.target.reset();$('message').textContent='已发布到官方目录';await load()}catch(err){$('publishError').textContent=err.message}finally{b.disabled=false}};
setInterval(()=>{if(ready&&!document.hidden&&!$('console').hidden)load().catch(report)},60000);screen().catch(report);
