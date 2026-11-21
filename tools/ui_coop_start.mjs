// Browser-level checks for cooperation submission; no GPU requests leave these checks.
export const COOP_START_CHECKS = [
  ['合作零权重传入真实提交体', `(async () => {
    const ew=document.querySelector('#coop-env-w'), cw=document.querySelector('#coop-char-w');
    if(!ew || !cw || coopNumber('0',0.7)!==0) return false;
    const prevE=ew.value,prevC=cw.value,originalFetch=window.fetch; let sent=null;
    try {
      ew.value='0';cw.value='0';
      window.fetch=async(url,opt)=>{
        if(String(url)==='/api/coop' && opt?.method==='POST') {
          sent=JSON.parse(opt.body);return new Response(JSON.stringify({ok:false,note:'smoke intercepted'}),{status:200,headers:{'Content-Type':'application/json'}});
        }
        return originalFetch(url,opt);
      };
      await coopStartReal();
      return !!sent && sent.env_weight===0 && sent.char_weight===0;
    } finally {
      window.fetch=originalFetch;ew.value=prevE;cw.value=prevC;
      if(coopTimer){clearInterval(coopTimer);coopTimer=null;}
    }
  })()`],
  ['合作失败保留具体原因且旧轮询不覆盖', `(async () => {
    const originalFetch=window.fetch;let replyOld=null;
    if(coopTimer){clearInterval(coopTimer);coopTimer=null;}
    CoopLaunch.error='';CoopLaunch.jobId='';CoopLaunch.pending=false;
    try {
      window.fetch=async(url,opt)=>{
        if(String(url)==='/api/coop/status') return new Promise(resolve=>{replyOld=resolve;});
        if(String(url)==='/api/coop/client-error') return new Response(JSON.stringify({ok:true}),{status:200,headers:{'Content-Type':'application/json'}});
        if(String(url)==='/api/coop' && opt?.method==='POST') return new Response(JSON.stringify({detail:[{loc:['body','extra_loras'],msg:'smoke incompatible artist'}]}),{status:422,headers:{'Content-Type':'application/json'}});
        return originalFetch(url,opt);
      };
      coopPoll();
      await coopStartReal();
      if(replyOld) replyOld(new Response(JSON.stringify({id:'',status:'idle',progress:0}),{status:200,headers:{'Content-Type':'application/json'}}));
      await new Promise(r=>setTimeout(r,80));
      const message=document.querySelector('#run-status').textContent;
      return message.includes('body.extra_loras') && message.includes('smoke incompatible artist') && !document.querySelector('#run-btn').disabled && coopTimer===null;
    } finally {
      window.fetch=originalFetch;
      if(coopTimer){clearInterval(coopTimer);coopTimer=null;}
      CoopLaunch.pending=false;CoopLaunch.error='';CoopLaunch.jobId='';CoopLaunch.epoch++;
    }
  })()`],
];
