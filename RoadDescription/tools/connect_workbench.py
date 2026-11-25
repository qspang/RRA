"""Add the report entry and same-origin proxy to the local external frontend."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
frontend = root/'frontend_integration/route-planning-agent'
server = frontend/'frontend.mjs'
index = frontend/'dist/index.html'
js = server.read_text()
html = index.read_text()
hook = "try{if(!['GET','HEAD']"
if 'reportProxy(req,res)' not in js:
    if hook not in js:
        raise SystemExit('前端静态服务器版本不匹配，请使用报告服务的 /workbench/ 入口')
    js = ("import {reportProxy} from '../../road_description/workbench/proxy.mjs';\n"
          + js.replace(hook,"try{if(reportProxy(req,res))return;if(!['GET','HEAD']",1))
if '/report-ui/routes.mjs' not in html:
    if '</head>' not in html or '</body>' not in html:
        raise SystemExit('前端模板缺少资源挂载位置')
    html = html.replace('</head>','<link rel="stylesheet" href="/report-ui/style.css"></head>',1)
    html = html.replace('</body>','<script type="module" src="/report-ui/routes.mjs"></script></body>',1)
for file, updated in [(server,js),(index,html)]:
    if file.read_text()!=updated:
        file.write_text(updated)
print('工作台已接入 KML 报告服务')
