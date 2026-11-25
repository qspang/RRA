const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(url,body){
  const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  const data=await r.json();
  if(!r.ok)throw Error(data.error||'报告读取失败');
  return data;
}
export async function reader(host,jid,agent){
  let kind=agent==='compliance'?'upper':agent,section=0,doc,sections,seq=0;
  const base=()=>'/api/kml-jobs/'+jid+'/document/'+kind+'/';
  function img(name,label){
    const src=base()+'image?name='+encodeURIComponent(name);
    return '<a class="plate-image" target="_blank" rel="noopener" href="'+src+'" title="查看原图"><img loading="lazy" alt="'+esc(label||'报告图件')+'" src="'+src+'"></a>';
  }
  function editLink(b){
    return kind!=='assembly'&&b?.id?'<button class="margin-edit" data-edit="'+esc(b.id)+'">编辑此段</button>':'';
  }
  function grid(title,headers,rows,source){
    const cells=(row)=>row.map((value,i)=>'<td class="'+(/^(K?\d+(\.\d+)?)(～K?\d+(\.\d+)?)?$/.test(value)?'measure':'')+'">'+esc(value).replace(/；(?=\S)/g,'；<wbr>')+'</td>').join('');
    const extra=rows.length>8;
    return '<section class="data-panel"><div class="table-scroll"><table><caption>'+esc(title||'数据明细')+editLink(source)+'</caption><thead><tr>'+headers.map(h=>'<th scope="col">'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map((row,i)=>'<tr'+(extra&&i>=6?' hidden':'')+'>'+cells(row)+'</tr>').join('')+'</tbody></table></div>'+
      (extra?'<button class="more-rows" aria-expanded="false" data-rows="'+rows.length+'">展开全部 '+rows.length+' 行 ↓</button>':'')+'</section>';
  }
  function sentences(text){
    const lines=text.match(/[^。！？\n]+[。！？]?|[。！？]/g)||[text];
    const parts=lines.map(line=>{
      // Only promote a sentence to a table when every field matches the source format.
      const village=line.match(/^按村级界图层，从起点沿线路依次经过以下区段：(.+)。$/);
      if(village){
        const rows=village[1].split('，').map(s=>s.match(/^(K[\d.]+)～(K[\d.]+) (.+)$/));
        if(rows.every(Boolean))return grid('村级区域分段',['起始里程','结束里程','村级区域'],rows.map(r=>r.slice(1)));
      }
      const area=line.match(/^线路自(.+)境内起步，在该(县区|乡镇)范围内走线约([\d.]+)公里，(.+)。$/);
      if(area){
        const rows=area[4].split(/，(?=至K)/).map(s=>s.match(/^至(K[\d.]+)进入(.+)，境内走线约([\d.]+)公里$/));
        if(rows.every(Boolean))return grid(area[2]+'分段里程',['进入里程','行政区划','长度 / km'],[['K0.000',area[1],area[3]],...rows.map(r=>r.slice(1))]);
      }
      return '<p>'+esc(line)+'</p>';
    });
    if(parts.length>5 && !parts.some(p=>p.includes('data-panel'))){
      return parts.slice(0,3).join('')+'<details class="para-details"><summary>展开其余 '+(parts.length-3)+' 句</summary>'+parts.slice(3).join('')+'</details>';
    }
    return parts.join('');
  }
  function theme(text){
    if(/^需复核的具体冲突/.test(text))return '需复核事项';
    if(/^线路自|^按村级界/.test(text))return '沿线行政区划';
    if(/^线路部分区段/.test(text))return '并行区段';
    if(/方案线路长度约/.test(text))return '线路指标';
    if(/方案从|^随后向/.test(text))return '线路走向与跨越';
    return '';
  }
  function layout(blocks){
    const html=[];
    for(let i=0;i<blocks.length;i++){
      const b=blocks[i],next=blocks[i+1];
      if(b.type==='table'||(next?.type==='table'&&['paragraph','caption'].includes(b.type)&&b.text.length<85&&!/[。！？]$/.test(b.text))){
        const hasTitle=b.type!=='table',table=hasTitle?blocks[++i]:b;
        const cells=table.rows.flat();
        if(cells.some(c=>c.images.length)&&cells.every(c=>c.images.length||!c.text.trim())){
          const caption=blocks[i+1]?.type==='caption'?blocks[++i].text:'';
          html.push('<section class="gallery-panel"><h3>'+esc(caption||'沿线图件')+'</h3><div class="plate-grid">'+cells.filter(c=>c.images.length).map(c=>'<figure>'+c.images.map(n=>img(n,c.text)).join('')+'<figcaption>'+esc(c.text.trim())+'</figcaption></figure>').join('')+'</div></section>');
        }else if(cells.some(c=>c.images.length)){
          html.push('<div class="paper-table"><table>'+table.rows.map(row=>'<tr>'+row.map(c=>'<td>'+c.images.map(n=>img(n,c.text)).join('')+esc(c.text)+'</td>').join('')+'</tr>').join('')+'</table></div>');
        }else if(table.rows.length){
          html.push(grid(hasTitle?b.text:'',table.rows[0].map(c=>c.text),table.rows.slice(1).map(r=>r.map(c=>c.text)),hasTitle&&b.type==='paragraph'?b:null));
        }
      }else if(b.type==='image'){
        const caption=next?.type==='caption'?blocks[++i].text:'图件';
        html.push('<figure class="plate-single">'+img(b.file,caption)+'<figcaption>'+esc(caption)+'<small>点击缩略图查看原图 ↗</small></figcaption></figure>');
      }else if(b.type==='caption'){
        html.push('<p class="paper-caption">'+esc(b.text)+'</p>');
      }else{
        const group=[b],label=theme(b.text);
        while(blocks[i+1]?.type==='paragraph'&&blocks[i+2]?.type!=='table'&&theme(blocks[i+1].text)===label)group.push(blocks[++i]);
        html.push('<section class="prose-panel'+(label==='需复核事项'?' review-panel':'')+'">'+(label?'<h3>'+label+'</h3>':'')+group.map(item=>'<div class="prose-item">'+sentences(item.text)+editLink(item)+'</div>').join('')+'</section>');
      }
    }
    return html.join('');
  }
  function paint(){
    const current=sections[section];
    host.innerHTML='<div class="rd-reader"><aside><h3>章节目录</h3>'+ (agent==='compliance'?'<div class="scheme-tabs">'+['upper','lower'].map((k,i)=>'<button data-kind="'+k+'" aria-pressed="'+(kind===k)+'">'+(i?'南方案':'北方案')+'</button>').join('')+'</div>':'')+
      sections.map((s,i)=>'<button class="toc-entry" aria-current="'+(section===i)+'" data-sec="'+i+'">'+esc(s.title)+'</button>').join('')+
      '</aside><article class="rd-paper"><div class="paper-top"><span>报告正文</span><span>'+ (doc.version?'审校版 · 第 '+doc.version+' 版':'生成稿')+'</span>'+ (doc.version?'<a href="'+base()+'docx">审校 Word ↓</a><a href="'+base()+'pdf">审校 PDF ↓</a>':'')+ (kind!=='assembly'&&current.blocks.some(b=>b.type==='paragraph')?'<button class="edit-open" data-start>智能审校</button>':'')+'</div><h2>'+esc(current.title)+'</h2>'+layout(current.blocks)+
      '<nav class="chapter-nav" aria-label="章节翻页">'+
      (section>0?'<button class="prev-section" data-sec="'+(section-1)+'"><small>← 上一节</small><b>'+esc(sections[section-1].title)+'</b></button>':'')+
      (section+1<sections.length?'<button class="next-section" data-sec="'+(section+1)+'"><small>下一节 →</small><b>'+esc(sections[section+1].title)+'</b></button>':'')+'</nav>'+

      (doc.version?'<div class="rd-actions"><a href="'+base()+'docx">下载审校 Word</a><a href="'+base()+'pdf">下载审校 PDF</a></div>':'')+'</article></div>';
  }
  async function load(){
    const ticket=++seq;host.textContent='正在读取章节和图件…';
    try{
      const data=await api(base()+'read');if(ticket!==seq)return;doc=data;sections=[];
      for(const b of doc.blocks){
        if(b.type==='heading'){sections.push({title:b.text,blocks:[]});continue;}
        if(!sections.length)sections.push({title:'核查依据与范围',blocks:[]});
        sections.at(-1).blocks.push(b);
      }
      if(agent==='compliance')section=Math.max(0,sections.findIndex(s=>s.title.startsWith('3.4.8.1')));
      paint();
    }catch(e){host.textContent=e.message;}
  }
  function edit(b){
    const d=document.createElement('dialog');d.className='rd-editor';
    d.innerHTML='<form><header><div><small>'+esc(sections[section].title)+'</small><h2>段落审校</h2></div><button type="button" data-close aria-label="关闭">关闭</button></header><label>编辑正文<textarea required maxlength="16000" rows="6"></textarea></label><div class="edit-instruction"><label>交给智能体修改<input maxlength="1500" placeholder="例如：按走向拆成两句，保留村名和里程"></label><button type="button" data-suggest>生成建议</button></div><section hidden><h3>智能体建议</h3><p></p><button type="button" data-use>采用到编辑框</button></section><div role="status"></div><footer><button class="primary" type="submit">保存审校稿</button></footer></form>';
    document.body.append(d);const find=s=>d.querySelector(s),text=find('textarea'),msg=find('[role=status]');text.value=b.text;
    d.onclose=()=>d.remove();find('[data-close]').onclick=()=>d.close();
    const payload=()=>({version:doc.version,source:doc.source,id:b.id,text:text.value});
    find('[data-suggest]').onclick=async e=>{
      if(!find('input').value.trim()){msg.textContent='请先填写修改要求。';return;}
      const btn=e.currentTarget;btn.disabled=true;msg.textContent='智能体正在修改此段…';find('section').hidden=true;
      try{const result=await api(base()+'suggest',{...payload(),instruction:find('input').value});find('section p').textContent=result.text;find('section').hidden=false;msg.textContent='请核对数值与专名后采用建议。';}catch(err){msg.textContent=err.message;}finally{btn.disabled=false;}
    };
    find('[data-use]').onclick=()=>{text.value=find('section p').textContent;find('section').hidden=true;text.focus();};
    find('form').onsubmit=async e=>{e.preventDefault();const btn=find('[type=submit]');btn.disabled=true;try{const result=await api(base()+'save',payload());doc.version=result.version;b.text=text.value.trim();d.close();paint();}catch(err){msg.textContent=err.message;}finally{btn.disabled=false;}};
    const label=document.createElement('label');label.textContent='所在段落';
    const select=document.createElement('select');
    for(const para of sections[section].blocks.filter(x=>x.type==='paragraph')){
      const opt=document.createElement('option');opt.value=para.id;opt.textContent=para.text.slice(0,46);select.append(opt);
    }
    select.value=b.id;select.onchange=()=>{
      if(text.value!==b.text&&!window.confirm('放弃当前段落尚未保存的修改？')){select.value=b.id;return;}
      d.close();edit(sections[section].blocks.find(x=>x.id===select.value));
    };
    label.append(select);find('header').after(label);d.showModal();
  }
  host.onclick=e=>{const btn=e.target.closest('button');if(!btn)return;
    if(btn.dataset.rows){
      const expanded=btn.getAttribute('aria-expanded')!=='true';
      btn.closest('.data-panel').querySelectorAll('tbody tr:nth-child(n+7)').forEach(tr=>{tr.hidden=!expanded;});
      btn.setAttribute('aria-expanded',String(expanded));btn.textContent=expanded?'收起明细 ↑':'展开全部 '+btn.dataset.rows+' 行 ↓';
    }
    if(btn.dataset.kind){kind=btn.dataset.kind;section=0;load();}
    if(btn.dataset.sec!==undefined){section=Number(btn.dataset.sec);paint();host.scrollIntoView({block:'start'});}
    if(btn.hasAttribute('data-start'))edit(sections[section].blocks.find(b=>b.type==='paragraph'));
    if(btn.dataset.edit)edit(sections[section].blocks.find(b=>b.id===btn.dataset.edit));
  };
  await load();
}
