/* Same production Interface and GPU. Hand pixels differ from affine/centre-depth. */
(async function(){
  const report={status:'FAIL',errors:[],checks:[],sourceScope:'engineering',originalDynamic:false};
  const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],keys=['walk','idle','normal_attack','hurt','special_attack','special_move'];
  const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:.5,far:100};
  const canvas=document.getElementById('readback'),ctx=canvas.getContext('2d');let prepared;
  function check(name,condition,actual){report.checks.push({name,passed:!!condition,actual});if(!condition)throw new Error(name+': '+JSON.stringify(actual));}
  function raw(world){return world.flatMap(([x,y,z])=>[z,-x,-y]);}
  function unit(world,texture,uv=[0,0,1,0,0,1]){
    const positions=raw(world),normals=[0,0,1,0,0,1,0,0,1],clips={};
    for(const key of keys)clips[key]={kind:'static',duration:1,loop:true,sampleTimes:[0],frames:[{positions,normals}]};
    return {positions,normals,uvs:uv,groups:[{indices:[0,1,2],texture}],clips,anchor:[0,0,0],scaleFactor:1,rootMatrix:I,rootPolicy:'engineering-fixed-S-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-bind-ground-pivot-v1',frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false};
  }
  function triangle(z){return [[-z*.1,-z*.1,z],[z*.1,-z*.1,z],[0,z*.1,z]];}
  function mesh(z,texture){return {positions:triangle(z).flat(),normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture}]};}
  function record(id,unitId){return {id,unitId,clip:'walk',frame:0,positionYup:[0,0,0],headingRadians:0,posePolicy:'engine-pose-v1',sourceScope:'engineering',rootPolicy:'engineering-fixed-S-v1',anchorPolicy:'raw-bind-ground-pivot-v1'};}
  const grid=[];for(let y=0;y<4;y++)for(let x=0;x<4;x++)grid.push(...(x===1&&y===3?[200,0,0,255]:x===1&&y===2?[0,200,0,255]:[0,0,200,255]));
  // Half-pixel centroid (320.5,320.5): equal screen weights, z1/2/4 -> UV2/7,1/7.
  const uvTriangle=[[.0025,.0075,1],[-.015,-.015,2],[.05,-.03,4]];
  const assets={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{
    near:unit(triangle(10),'red'),far:unit(triangle(20),'red'),transparent:unit(triangle(5),'transparent'),uv:unit(uvTriangle,'grid'),
    tooNear:unit(triangle(.25),'red'),tooFar:unit(triangle(101),'red'),crossNear:unit([[-1,-1,.25],[1,-1,2],[0,1,2]],'red'),rolled:unit([[2,-1,10],[4,-1,10],[3,1,10]],'red')},
    worlds:{near:{basisVersion:'loaded-yup-v1',meshes:[mesh(10,'green')]},far:{basisVersion:'loaded-yup-v1',meshes:[mesh(20,'green')]},farFace:{basisVersion:'loaded-yup-v1',meshes:[mesh(100,'green')]},background:{basisVersion:'loaded-yup-v1',meshes:[mesh(50,'blue')]}},
    textures:{red:{width:1,height:1,pixels:[200,0,0,255]},green:{width:1,height:1,pixels:[0,200,0,255]},blue:{width:1,height:1,pixels:[0,0,200,255]},transparent:{width:1,height:1,pixels:[200,0,0,0]},grid:{width:4,height:4,pixels:grid}}};
  function frame(worldId,drawRecords){const frame=prepared.renderFrame({snapshot:{tick:3},worldId,drawRecords,dpr:1});ctx.clearRect(0,0,640,640);ctx.drawImage(frame.canvas,0,0);return {frame,pixel:Array.from(ctx.getImageData(320,320,1,1).data)};}
  function rgb(expected,actual){return expected.every((x,i)=>Math.abs(x-actual[i])<=1);}
  try {
    prepared=await BugBitsMeshScene.prepareMeshScene({assets,projection,worldId:'background'});
    let f=frame('near',[record(1,'far')]);check('terrain near beats later unit far',rgb([40,90,40,255],f.pixel),f.pixel);
    f=frame('far',[record(1,'near')]);check('later unit near beats terrain far',rgb([90,40,40,255],f.pixel),f.pixel);
    f=frame('background',[record(1,'transparent'),record(2,'far')]);check('alpha0 front does not write depth',rgb([90,40,40,255],f.pixel),f.pixel);
    f=frame('background',[record(1,'tooNear'),record(2,'tooFar')]);check('whole near/far rejection',rgb([40,40,90,255],f.pixel),f.pixel);
    f=frame('background',[record(1,'uv')]);check('perspective UV literal beats affine competitor',rgb([90,40,40,255],f.pixel),f.pixel);
    f=frame('background',[record(1,'near')]);check('camera before uniform change',rgb([90,40,40,255],f.pixel),f.pixel);
    const next={...projection,cameraPosition:[1,0,0]};prepared.setProjection(next);next.cameraPosition[0]=100;
    f=frame('background',[record(1,'near')]);check('camera uniform changes real pixels and copies input',rgb([40,40,90,255],f.pixel),f.pixel);
    let rejected=false;try{prepared.setProjection({...projection,near:100,far:1});}catch(error){rejected=true;}
    f=frame('background',[record(1,'near')]);check('invalid camera preserves committed view',rejected&&rgb([40,40,90,255],f.pixel),f.pixel);
    prepared.setProjection(projection);
    f=frame('farFace',[]);check('inclusive far face remains visible',rgb([40,90,40,255],f.pixel),f.pixel);
    f=frame('background',[record(1,'crossNear')]);check('triangle crossing near clips instead of centre cull',rgb([90,40,40,255],f.pixel),f.pixel);
    prepared.dispose();prepared=await BugBitsMeshScene.prepareMeshScene({assets,projection:{...projection,basis9:[0,-1,0,1,0,0,0,0,1]},worldId:'background'});
    frame('background',[record(1,'rolled')]);const rollPixel=Array.from(ctx.getImageData(320,260,1,1).data);check('nonzero roll uses full camera rows',rgb([90,40,40,255],rollPixel),rollPixel);
    const clips=Object.keys(assets.units.near.clips);check('all six slots',clips.length===6,clips);
    report.status='PASS';
  }catch(error){report.errors.push(String(error));}
  finally{try{prepared?.dispose();report.cleanupComplete=true;}catch(error){report.errors.push('cleanup '+error);report.status='FAIL';}}
  window.meshGPUReport=report;document.getElementById('result').textContent=JSON.stringify(report,null,2);document.body.dataset.status=report.status;
})();
