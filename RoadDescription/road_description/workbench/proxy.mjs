import http from 'node:http';
export function reportProxy(req,res){
  const path=req.url.split('?')[0];
  const documentRoute=/^\/api\/kml-jobs\/[a-f0-9]{32}\/document\/(?:description|comparison|upper|lower)\/(read|image|docx|pdf|save|suggest)$/.exec(path);
  const read = (documentRoute && ['read','image','docx','pdf'].includes(documentRoute[1])) || path==='/api/kml-jobs/recent' || /^\/api\/kml-jobs\/[a-f0-9]{32}\/map$/.test(path) || /^\/report-ui\/(reader\.mjs|routes\.mjs|style\.css)$/.test(path) ||
    /^\/api\/kml-jobs\/[a-f0-9]{32}$/.test(path) ||
    /^\/api\/reports\/[a-f0-9]{32}\/files\/.+\.(pdf|docx)$/.test(path);
  const write = (documentRoute && ['save','suggest'].includes(documentRoute[1])) || path==='/api/kml-jobs'||/^\/api\/reports\/[a-f0-9]{32}\/cancel$/.test(path);
  if(!read&&!write)return false;
  if(!/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(req.headers.host||'') ||
     (req.headers.origin && req.headers.origin!=='http://'+req.headers.host) ||
     (read? !['GET','HEAD'].includes(req.method):req.method!=='POST')){
    res.writeHead(403);res.end();return true;
  }
  const headers={};
  for(const k of ['content-type','content-length'])if(req.headers[k])headers[k]=req.headers[k];
  const upstream=http.request({hostname:'127.0.0.1',port:5010,path:req.url,method:req.method,headers},r=>{
    res.writeHead(r.statusCode,r.headers);r.pipe(res);
  });
  upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502,{'content-type':'application/json'});
    res.end(JSON.stringify({error:'报告服务未连接，请检查本机 5010 端口。'}));});
  req.pipe(upstream);return true;
}
