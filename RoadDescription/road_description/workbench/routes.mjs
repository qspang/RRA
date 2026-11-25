import {reader} from './reader.mjs';
const groups = {description:'路径描述',comparison:'方案比选',compliance:'合规分析',assembly:'综合报告'};
const chapters = {description:'3.3.1 北方案 · 3.3.2 南方案',comparison:'3.3 路径方案比选',compliance:'3.4.8–3.4.11 · 3.5',assembly:'三个智能体合册'};
const stages = {queued:'排队中',running:'生成中',loading:'读取地图',extracting_facts:'核查地物与区划',generating_figures:'绘制路径图',writing:'撰写路径描述',rendering:'排版',running_agents:'生成章节',reviewing_reports:'审阅成稿',completed:'生成完成',review_required:'待复核',failed:'生成失败',interrupted:'服务中断',cancelled:'已取消',cancelling:'取消中'};
const slot = 'road-description.kml.jobs.v1';
let ids;
try {ids = JSON.parse(localStorage.getItem(slot)) || [];} catch {ids=[];}
let selected=sessionStorage.getItem('rd-active')||ids[0], job, error='', timer, seq=0;
const escape = t => String(t??'').replace(/[&<>"']/g,k=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[k]));
const section = () => location.hash.slice(1)||'comparison';
const escUrl = name => name.split('/').map(encodeURIComponent).join('/');
async function request(url,options) {
  const response=await fetch(url,options);
  const body=await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(body.error || '服务请求失败（HTTP '+response.status+'）');
  return body;
}
function form() {
  const dialog=document.querySelector('#route-import');
  dialog.querySelector('form').reset();
  dialog.querySelector('[role=alert]').textContent='';
  dialog.showModal();
}
function card(key) {
  const files=job?.groups[key]||[];
  const links=files.map(name=>{
    const ext=name.split('.').pop().toUpperCase();
    const label=key==='compliance'? (name.includes('/upper/')?'北方案 ':'南方案 '):'';
    const url='/api/reports/'+selected+'/files/'+escUrl(name);
    const preview=ext==='PDF'?'<a class="rd-file rd-preview" href="'+url+'?view=1#zoom=page-width" target="_blank" rel="noopener">'+label+'预览 PDF</a>':'';
    return preview+'<a class="rd-file" href="'+url+'" download>'+label+ext+' ↓</a>';
  }).join('');
  return '<article class="rd-card"><h3>'+groups[key]+'</h3><small>'+chapters[key]+'</small><div>'+ (links||'<span>暂无成稿</span>')+'</div></article>';
}
function draw(){
  const main=document.querySelector('#app main');
  const top=document.querySelector('.top-tools');
  if(!main || !top || !(section() in groups || section()==='overview'))return;
  if(!top.querySelector('.rd-import')){
    const b=document.createElement('button');b.className='primary rd-import';b.textContent='导入南北方案';b.onclick=form;top.prepend(b);
  }
  if(!selected)return;
  const key=section();
  const visible=key==='overview'?['description','comparison','compliance','assembly']:[key,'assembly'];
  const status=job?.status==='running'?(stages[job.stage]||'生成中'):(stages[job?.status]||'读取任务');
  const title=job?.title||'南北方案报告';
  const history=ids.map((id,i)=>'<option value="'+escape(id)+'" '+(id===selected?'selected':'')+'>任务 '+escape(id.slice(0,8))+(i===0?' · 最近':'')+'</option>').join('');
  const current=job?.active?.replace('route_','');
  const canCancel=['running','queued'].includes(job?.status);
  const summaries=(job?.summary||[]).map(r=>'<tr><th>'+escape(r.name)+'</th><td>'+r.km.toFixed(3)+' km</td><td>'+r.tortuosity.toFixed(3)+'</td><td>'+escape(r.counties.join('、'))+'</td></tr>').join('');
  const evidence=summaries?'<section class="rd-evidence"><h3>沿线路径</h3><table><thead><tr><th>方案</th><th>长度</th><th>曲折系数</th><th>行经县区</th></tr></thead><tbody>'+summaries+'</tbody></table></section>':'';
  const map=job?.has_map&&['comparison','description','overview'].includes(key)?'<details class="rd-map"><summary>查看南北方案与敏感区叠加图</summary><a href="/api/kml-jobs/'+selected+'/map" target="_blank" rel="noopener"><img loading="lazy" src="/api/kml-jobs/'+selected+'/map" alt="南北方案与沿线敏感区叠加图"></a></details>':'';
  const heads={description:['方案','出线段描述'],comparison:['指标','北方案','南方案'],compliance:['方案','核查结果','冲突事项','正文组织']};
  const previewRows=job?.previews?.[key]||[];
  const preview=previewRows.length?'<section class="rd-evidence"><h3>'+groups[key]+'摘要</h3><table><thead><tr>'+heads[key].map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+previewRows.map(row=>'<tr>'+row.map(cell=>'<td>'+escape(cell)+'</td>').join('')+'</tr>').join('')+'</tbody></table></section>':'';
  const hasReader=key!=='overview'&&job?.groups[key]?.length;
  const metrics=(job?.routes||[]).map(r=>'<div class="route-metric"><small>'+(r.id==='upper'?'北方案':'南方案')+'长度</small><div><b>'+r.km.toFixed(3)+'</b> <span>km</span></div></div>').join('');
  const html='<section class="rd-report"><header><div><p>'+escape(title)+'</p><h1>'+escape(groups[key]||'报告总览')+'</h1></div><select aria-label="切换报告任务" id="rd-history">'+history+'</select></header><div class="rd-status" role="status"><div class="route-status"><small>报告状态</small><strong>'+escape(status)+'</strong>'+escape(groups[current]||'')+'</div>'+metrics+'</div>' + (error||job?.error?'<p role="alert">'+escape(error||job.error)+'</p>':'')+(hasReader?'<div id="rd-reading"></div><details class="rd-files"><summary>生成稿下载与指标摘要</summary>':'')+'<div class="rd-grid">'+visible.map(card).join('')+'</div>'+preview+evidence+map+(hasReader?'</details>':'')+'<div class="rd-actions">'+(canCancel?'<button id="rd-cancel">取消生成</button>':'')+'<button id="rd-demo">返回原工作空间</button></div></section>';
  if(main.dataset.rdContent===html)return;
  main.dataset.rdContent=html;main.innerHTML=html;
  if(hasReader)reader(main.querySelector('#rd-reading'),selected,key);
  const indicator=document.querySelector('.sys-status');if(indicator)indicator.innerHTML='<span class="dot"></span>报告工作空间<small>已接入大埔工程地图</small>';
  document.querySelector('#rd-history').onchange=e=>{selected=e.target.value;sessionStorage.setItem('rd-active',selected);job=null;refresh();};
  document.querySelector('#rd-demo').onclick=()=>{selected=null;sessionStorage.setItem('rd-demo','1');location.reload();};
  const cancel=document.querySelector('#rd-cancel');if(cancel)cancel.onclick=async()=>{try{await request('/api/reports/'+selected+'/cancel',{method:'POST'});refresh();}catch(e){error=e.message;draw();}};
}
async function refresh(){
  clearTimeout(timer);
  const version=++seq;
  if(!selected){draw();return;}
  try {
    const result=await request('/api/kml-jobs/'+selected);
    if(version!==seq)return;
    job=result;error='';
  } catch(e){if(version!==seq)return;error=e.message;}
  draw();
  if(error||['queued','running','cancelling'].includes(job?.status)) timer=setTimeout(refresh,2500);
}
const dialog=document.createElement('dialog');
dialog.id='route-import';dialog.className='modal';
dialog.innerHTML='<form><div class="modal-head"><h2>导入南北方案</h2></div><div class="modal-body"><p>选择同一工程起终点的两条 KML 线路。提交后将生成路径描述、方案比选和合规分析。</p>'+['upper','lower'].map((id,i)=>'<label class="field"><span>'+(i?'南方案':'北方案')+'路径</span><input type="file" required name="'+id+'" accept=".kml"></label>').join('')+'<small>每个文件限一条连续路线，最大 2 MB。使用当前大埔工程地图。</small><p role="alert"></p></div><div class="modal-footer"><button type="button" id="rd-close">关闭</button><button type="submit" class="primary">导入并生成报告</button></div></form>';
document.body.append(dialog);
dialog.querySelector('#rd-close').onclick=()=>dialog.close();
dialog.querySelector('form').onsubmit=async e=>{
  e.preventDefault();const button=dialog.querySelector('[type=submit]');button.disabled=true;
  try {
    const data=await request('/api/kml-jobs',{method:'POST',body:new FormData(e.target)});
    ids=[data.id,...ids].slice(0,30);localStorage.setItem(slot,JSON.stringify(ids));sessionStorage.removeItem('rd-demo');selected=data.id;sessionStorage.setItem('rd-active',selected);job=null;error='';dialog.close();draw();await refresh();
  }catch(err){dialog.querySelector('[role=alert]').textContent=err.message;}finally{button.disabled=false;}
};
if(sessionStorage.getItem('rd-demo'))selected=null;
const app=document.querySelector('#app');
new MutationObserver(()=>{draw();const top=document.querySelector('.top-tools');if(!selected&&ids.length&&top?.querySelector('.rd-import')&&!top.querySelector('.rd-return')){const b=document.createElement('button');b.className='rd-return';b.textContent='查看报告任务';b.onclick=()=>{sessionStorage.removeItem('rd-demo');selected=ids[0];refresh();};top.prepend(b);}
 if(selected && top?.querySelector('.rd-import')){top.querySelector('.rd-return')?.remove();for(const b of top.querySelectorAll('.project-switch,.demo-badge,.header-clock'))b.hidden=true;}
}).observe(app,{childList:true,subtree:true});
async function restore(){
  try{
    const result=await request('/api/kml-jobs/recent');
    ids=result.ids;localStorage.setItem(slot,JSON.stringify(ids));
    if(!ids.includes(selected)&&!sessionStorage.getItem('rd-demo')) selected=ids[0];
  }catch{}
  draw();refresh();
}
restore();
