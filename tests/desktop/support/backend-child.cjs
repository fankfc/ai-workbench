const http=require('node:http');
const mode=process.env.TEST_BEHAVIOR;
if(mode==='early-exit')process.exit(13);
const identity=mode==='old-port'?'old-instance':process.env.WORKBENCH_INSTANCE_ID;
const server=http.createServer((request,response)=>{
  if(mode==='health-timeout'&&request.url==='/v1/health')return;
  response.setHeader('Content-Type','application/json');
  if(request.headers.authorization!==`Bearer ${process.env.WORKBENCH_API_TOKEN}`){response.writeHead(401);response.end('{}');return;}
  response.end(JSON.stringify(request.url==='/v1/health'?{instance_id:identity,pid:process.pid,protocol_version:'1.0',provider_mode:'fake'}:{saved:true}));
});
server.listen(0,'127.0.0.1',()=>process.stdout.write(JSON.stringify({kind:'backend.ready',instance_id:identity,pid:process.pid,protocol_version:'1.0',port:server.address().port})+'\n'));
process.on('SIGTERM',()=>server.close(()=>process.exit(0)));
