import { useEffect, useId, useRef, useState } from 'react';
import { ArrowRight, CircleCheck, RefreshCw } from 'lucide-react';
import { api } from '../api';

const key = 'xbot.framework-update.job';
const labels:Record<string,string> = {queued:'已提交，等待宿主机执行',running:'正在更新并检查服务',succeeded:'已更新，新版服务正常',rolled_back:'更新失败，旧版服务已恢复',failed:'更新失败，请检查宿主机',interrupted:'宿主机任务中断，需要检查',stale:'本地文件已变化，请重新检查更新'};

export function useAvailableUpdate() {
  const [available,setAvailable] = useState(false);
  useEffect(() => {
    let active = true, pending = false;
    async function refresh() {
      if (document.hidden || pending) return;
      pending = true;
      try { const preview = await api.frameworkPreview(); if (active) setAvailable(!!preview.available); }
      catch { if (active) setAvailable(false); }
      finally { pending = false; }
    }
    void refresh(); const timer = window.setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
    return () => { active = false; clearInterval(timer); document.removeEventListener('visibilitychange', refresh); };
  }, []);
  return available;
}

export function FrameworkUpdate({version,available,settings=false}:{version:string;available:boolean;settings?:boolean}) {
  const headingId = useId();
  const dot = available && <span className="update-dot" role="img" aria-label="有可用更新" />;
  const dialog = useRef<HTMLDialogElement>(null);
  const [plan,setPlan] = useState<Awaited<ReturnType<typeof api.frameworkPreview>>>();
  const [job,setJob] = useState(()=>localStorage.getItem(key)||'');
  const [message,setMessage] = useState('');
  const [busy,setBusy] = useState(false);
  const [terminal,setTerminal] = useState(false);
  const [succeeded,setSucceeded] = useState(false);
  useEffect(()=>{
    if(!job)return;
    let closed=false, timer=0;
    async function poll(){
      try {
        const {status,phase}=await api.frameworkJob(job);
        if(closed)return;
        setSucceeded(status==='succeeded');
        const phases:Record<string,string>={verify:'正在校验增量文件',apply:'正在应用文件变更',restart:'正在重启服务',health:'正在检查新版服务',restore:'正在恢复原版本'};
        setMessage((status==='running'&&phase?phases[phase]:undefined)??labels[status]??'未知任务状态');
        if(!['running','queued'].includes(status)){setTerminal(true);return;}
      } catch(e){if(closed)return;if(e instanceof Error && e.message==='任务尚未提交'){setMessage('确认请求没有送达，请重新检查更新。');setTerminal(true);return;}setMessage('未收到任务结果，正在重新连接…');}
      timer=window.setTimeout(()=>void poll(),2000);
    }
    void poll(); return ()=>{closed=true;clearTimeout(timer);};
  },[job]);
  async function check(install=false){
    setBusy(true);setPlan(undefined);setMessage('正在检查更新…');
    try{const next=await api.frameworkPreview();if(install&&next.available&&next.confirmation&&!Object.keys(next.conflicts??{}).length){await submit(next.confirmation);return;}setPlan(next);setMessage(next.available?'请核对本次更新':'暂无适用于本机的待安装更新');}
    catch(e){setMessage(e instanceof Error && e.message==='Not Found'?'此实例尚未启用在线安装。':e instanceof Error?e.message:'无法检查更新');}finally{setBusy(false);}
  }
  async function submit(id=plan?.confirmation){
    if(!id)return;
    setBusy(true);localStorage.setItem(key,id);setTerminal(false);setPlan(undefined);
    setMessage('正在提交更新任务…');try{await api.frameworkSubmit(id);setJob(id);}
    catch(e){
      if(e instanceof TypeError){setJob(id);}else{localStorage.removeItem(key);setMessage(e instanceof Error?e.message:'提交失败');}
    }finally{setBusy(false);}
  }
  function open(){dialog.current?.showModal();if(!job&&!busy)void check(settings);}
  return <>{settings ? <section className="card" aria-label="版本与更新">
    <h2 className="card__title">版本与更新</h2><p>当前前端版本：v{version}</p>
    <button type="button" className="primary-button" onClick={open}><RefreshCw size={14}/>{job?'查看更新结果':'更新'}{dot}</button>
  </section> : <button className="frontend-version sidebar__brand-tag" type="button" title={available?'有可用更新':'检查框架更新'} onClick={open}>v{version}{dot}</button>}
    <dialog ref={dialog} className="config-confirm-dialog framework-dialog" aria-labelledby={headingId}>
      <header className="framework-dialog__header">{succeeded?<CircleCheck size={21} aria-hidden="true"/>:<RefreshCw size={19} aria-hidden="true"/>}<h2 id={headingId}>{succeeded?'更新完成':plan?.available?`更新至 ${plan.version}`:'框架更新'}</h2></header>
      <p role="status">{message}</p>
      {(busy||job&&!terminal)&&<progress aria-label="更新进度" style={{width:'100%'}}/>}
      {plan?.available&&<><p>仅应用本次新增、修改和删除的文件。其他文件保持不变。</p>
        {Object.keys(plan.conflicts??{}).length>0?<details open><summary>以下本地修改将被覆盖</summary><ul style={{maxHeight:'30vh',overflow:'auto',overflowWrap:'anywhere'}}>{Object.entries(plan.conflicts??{}).map(([path,type])=><li key={path}>{({added:'新增',modified:'修改',removed:'删除'} as Record<string,string>)[type]}：{path}</li>)}</ul></details>:<p>未检测到本地代码修改。</p>}</>}
      <div className="config-confirm-dialog__actions"><button autoFocus className="ghost-button" onClick={()=>dialog.current?.close()}>{plan?.available?'取消':'关闭'}</button>
        {plan?.available&&<button disabled={busy} className="primary-button" onClick={()=>void submit()}>应用本次更新</button>}
        {succeeded?<button className="primary-button" onClick={()=>{localStorage.removeItem(key);window.location.reload();}}>进入新版<ArrowRight size={14}/></button>:terminal&&<button className="ghost-button" onClick={()=>{localStorage.removeItem(key);setJob('');setTerminal(false);void check();}}><RefreshCw size={14}/>重新检查</button>}
      </div></dialog></>;
}
