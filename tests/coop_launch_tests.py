# -*- coding: utf-8 -*-
"""合作提交生命周期：失败可见、请求去重和错误明细。"""
import json
import subprocess
from pathlib import Path


def run(check, root, client):
    def lifecycle():
        code = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const status={textContent:''}, button={disabled:false}, reports=[];
const ctx={Promise,console:{error(){}},coopTimer:123,clearInterval(){},toast(){},
  document:{querySelector:s=>s==='#run-btn'?button:status},
  api:(url,options)=>{reports.push([url,JSON.parse(options.body)]);return Promise.resolve({ok:true});}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';globalThis.launch=CoopLaunch;',ctx);
(async()=>{
  const launch=ctx.launch; let reject, count=0;
  const waiting=new Promise((resolve,fail)=>reject=fail);
  const result=launch.run(()=>{count++;return waiting;});
  const oldEpoch=launch.epoch;
  await launch.run(()=>{count++;});
  assert.equal(count,1);assert.equal(button.disabled,true);
  assert.equal(launch.current(oldEpoch,{id:''}),false);
  reject(new Error('extra_loras: incompatible artist'));
  assert.equal(await result,null);
  assert.match(status.textContent,/incompatible artist/);
  assert.equal(button.disabled,false);assert.equal(ctx.coopTimer,null);
  assert.equal(launch.current(oldEpoch,{status:'idle'}),false);
  assert.equal(reports[0][0],'/api/coop/client-error');
  await launch.run(()=>{launch.accept('new-job');return {ok:true};});
  assert.equal(launch.error,'');
  assert.equal(launch.current(launch.epoch,{id:'old-job'}),false);
  assert.equal(launch.current(launch.epoch,{id:'new-job'}),true);
  await launch.run(()=>{throw new TypeError('broken block');});
  assert.match(status.textContent,/broken block/);assert.equal(launch.pending,false);
  console.log('COOP_LAUNCH_LIFECYCLE_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        path = str(Path(root) / "station/static/js/coop_launch.js")
        result = subprocess.run(["node", "-e", code, path], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
    check("合作启动：请求去重、具体错误保留与过期轮询隔离", lifecycle)

    def error_detail():
        code = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={fetch:async()=>({ok:false,status:422,text:async()=>JSON.stringify({detail:[
  {loc:['body','extra_loras'],msg:'artist is incompatible'}]})})};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';globalThis.request=api;',ctx);
ctx.request('/api/coop').then(()=>{throw new Error('expected rejection');}).catch(error=>{
  assert.equal(error.status,422);assert.match(error.message,/body.extra_loras/);
  assert.match(error.message,/artist is incompatible/);console.log('API_ERROR_DETAIL_OK');
}).catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(["node", "-e", code, str(Path(root) / "station/static/js/util.js")],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
    check("合作启动：422 返回包含字段位置和完整原因", error_detail)

    def diagnostic():
        response = client.post("/api/coop/client-error", json={"message": "test: launch request rejected"})
        assert response.status_code == 200 and response.json()["ok"], response.text
        obs = client.get("/api/observability").json()
        assert any(w["where"] == "coop_client_start" and "launch request rejected" in w["error"]
                   for w in obs["warnings"]["recent"]), json.dumps(obs["warnings"], ensure_ascii=False)
        assert client.post("/api/coop/client-error", json={"message": "x" * 1501}).status_code == 422
    check("合作启动：失败诊断写入可观测性并限制报文大小", diagnostic)
