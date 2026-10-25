"""Use browser-scoped Tianditu credentials through the existing planner page."""
import atexit
import base64
import io
from PIL import Image

_clients={}


def tile(planner_url, zoom, x, y, annotations=False):
    if planner_url not in _clients:
        from playwright.sync_api import sync_playwright
        driver=sync_playwright().start()
        browser=driver.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,
                                      args=['--no-sandbox','--disable-dev-shm-usage'])
        page=browser.new_page()
        page.goto(planner_url,wait_until='domcontentloaded',timeout=30000)
        page.wait_for_function('typeof geoMeta!=="undefined" && geoMeta && geoMeta.tianditu_tk',timeout=60000)
        _clients[planner_url]=(driver,browser,page)
    page=_clients[planner_url][2]
    # The URL and key stay inside the actual browser origin; no credential in logs.
    result=page.evaluate('''async ([z,x,y,labels]) => {
      const load=(layer)=>new Promise(resolve=>{const image=new Image();image.crossOrigin='anonymous';
        const timer=setTimeout(()=>resolve(null),15000);
        image.onload=()=>{clearTimeout(timer);resolve(image)};
        image.onerror=()=>{clearTimeout(timer);resolve(null)};image.src=_tileUrl(layer+'_w',layer,z,x,y);});
      const images=await Promise.all((labels?['img','cia']:['img']).map(load));
      if(images.some(x=>!x))return null;
      try{const canvas=document.createElement('canvas');canvas.width=images[0].width;canvas.height=images[0].height;
        for(const image of images)canvas.getContext('2d').drawImage(image,0,0);
        return canvas.toDataURL('image/png');}catch(e){return null;}
    }''',[zoom,x,y,annotations])
    if not result:raise RuntimeError('浏览器影像瓦片加载失败')
    return Image.open(io.BytesIO(base64.b64decode(result.split(',',1)[1]))).convert('RGB')


def close():
    for driver,browser,page in _clients.values():
        try:browser.close();driver.stop()
        except Exception:pass
    _clients.clear()


atexit.register(close)
