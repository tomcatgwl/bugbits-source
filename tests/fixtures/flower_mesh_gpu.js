/* Synthetic independent GPU oracle, not an original-game screenshot. */
(async function(){
  const report={status:'FAIL',errors:[],checks:[],sourceScope:'engineering-bind-owner-v1',originalDynamic:false};
  const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  const projection={kind:'matrix-yup-v1',basis9:[1,0,0,0,1,0,0,0,1],cameraPosition:[0,0,0],size:400,cot:1,aspect:1.6,near:.5,far:100};
  // Same NDC footprint at every depth, centred far from triangle boundaries.
  const triangle=z=>[[-z*.2,-z*.2,z],[z*.2,-z*.2,z],[0,z*.2,z]];
  function mesh(z,texture){return {positions:triangle(z).flat(),normals:[0,0,1,0,0,1,0,0,1],uvs:[0,0,1,0,0,1],groups:[{indices:[0,1,2],texture}]};}
  function prop(z,texture){
    const m=mesh(z,texture);
    // Independent Q^-1 and division by scale2.5: [z/2.5,-x/2.5,-y/2.5].
    m.positions=triangle(z).flatMap(([x,y,z])=>[z/2.5,-x/2.5,-y/2.5]);
    return {...m,frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,rootMatrix:I,rootPolicy:'engineering-prop-bind-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-model-origin-v1'};
  }
  const assets={schema:'engine-mesh-v1',posePolicy:'engine-pose-v1',units:{},
    worlds:{near:{basisVersion:'loaded-yup-v1',meshes:[mesh(10,'green')]},far:{basisVersion:'loaded-yup-v1',meshes:[mesh(20,'green')]},background:{basisVersion:'loaded-yup-v1',meshes:[mesh(50,'blue')]}},
    props:{near:prop(10,'red'),far:prop(20,'red'),green:prop(15,'green'),transparent:prop(5,'transparent'),tooNear:prop(.25,'red'),tooFar:prop(101,'red')},
    textures:{red:{width:1,height:1,pixels:[200,0,0,255]},green:{width:1,height:1,pixels:[0,200,0,255]},blue:{width:1,height:1,pixels:[0,0,200,255]},transparent:{width:1,height:1,pixels:[200,0,0,0]}}};
  // Independent row oracle: v=.25 selects yellow without flip, green with flip.
  assets.textures.asymmetric={width:1,height:2,pixels:[200,160,0,255,0,200,0,255]};
  for(const [id,flip] of [['forward',false],['legacy',true],['unverified',undefined]]){
    const m=prop(10,'asymmetric');m.uvs=[.25,.25,.25,.25,.25,.25];
    if(flip!==undefined){m.textureVFlip=flip;m.textureUvScope='engineering-explicit-v1';}assets.props[id]=m;
  }
  const asymTerrain=mesh(50,'asymmetric');asymTerrain.uvs=[.25,.25,.25,.25,.25,.25];
  assets.worlds.asymmetric={basisVersion:'loaded-yup-v1',meshes:[asymTerrain]};
  const unit=mesh(10,'asymmetric');unit.positions=triangle(10).flatMap(([x,y,z])=>[z,-x,-y]);unit.uvs=[.25,.25,.25,.25,.25,.25];
  Object.assign(unit,{anchor:[0,0,0],rootMatrix:I,scaleFactor:1,rootPolicy:'engineering-fixed-S-v1',coordinatePolicy:'raw-to-engine-yup-Q-v1',anchorPolicy:'raw-bind-ground-pivot-v1',frameBasis:'raw-model-v1',rootApplied:false,scaleApplied:false,clips:{}});
  for(const key of ['walk','idle','normal_attack','hurt','special_attack','special_move'])unit.clips[key]={kind:'static',duration:0,loop:false,sampleTimes:[0],frames:[{positions:[...unit.positions],normals:[...unit.normals]}]};
  assets.units.synthetic=unit;
  const record=assetId=>({id:assetId,assetId,positionYup:[0,0,0],scaleFactor:2.5,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'});
  let prepared;
  function check(name,condition,actual){report.checks.push({name,passed:!!condition,actual});if(!condition)throw new Error(name+': '+JSON.stringify(actual));}
  function frame(name,worldId,propRecords,dpr,drawRecords=[]){
    const f=prepared.renderFrame({snapshot:{tick:42},worldId,propRecords,drawRecords,dpr});
    const card=document.createElement('section'),title=document.createElement('p'),canvas=document.createElement('canvas');
    title.textContent=name;canvas.width=f.canvas.width;canvas.height=f.canvas.height;card.append(title,canvas);document.getElementById('cards').append(card);
    const ctx=canvas.getContext('2d');ctx.drawImage(f.canvas,0,0);const c=canvas.width/2;
    return {pixel:Array.from(ctx.getImageData(c,c,1,1).data),bar:Array.from(ctx.getImageData(c,0,1,1).data),width:canvas.width,propDraws:f.propDraws};
  }
  const rgb=(expected,actual)=>expected.every((v,i)=>Math.abs(v-actual[i])<=1);
  try{
    prepared=await BugBitsMeshScene.prepareMeshScene({assets,projection,worldId:'background'});
    for(const dpr of [1,2]){
      let f=frame('near flower / far ground DPR'+dpr,'far',[record('near')],dpr);
      check('near flower wins '+dpr,rgb([90,40,40,255],f.pixel),f);
      check('DPR letterbox '+dpr,f.width===640*dpr&&rgb([12,14,16,255],f.bar),{width:f.width,bar:f.bar});
      f=frame('near ground / far flower DPR'+dpr,'near',[record('far')],dpr);
      check('near terrain wins '+dpr,rgb([40,90,40,255],f.pixel),f);
      f=frame('transparent front / far flower DPR'+dpr,'background',[record('transparent'),record('far')],dpr);
      check('alpha0 does not write depth '+dpr,rgb([90,40,40,255],f.pixel),f);
      const a=frame('near red then far green DPR'+dpr,'background',[record('near'),record('green')],dpr);
      const b=frame('far green then near red DPR'+dpr,'background',[record('green'),record('near')],dpr);
      check('prop order invariant '+dpr,rgb([90,40,40,255],a.pixel)&&rgb(a.pixel,b.pixel),{a:a.pixel,b:b.pixel});
      f=frame('frustum rejects props DPR'+dpr,'background',[record('tooNear'),record('tooFar')],dpr);
      check('near far reject '+dpr,rgb([40,40,90,255],f.pixel),f);
    }
    // One prepared scene and fixed tick/projection/geometry through both DPRs.
    for(const dpr of [1,2]){
      const a=frame('forward yellow DPR'+dpr,'background',[record('forward')],dpr);
      check('textureVFlip false yellow '+dpr,rgb([90,80,40,255],a.pixel),a);
      const b=frame('legacy green DPR'+dpr,'background',[record('legacy')],dpr);
      check('textureVFlip true green '+dpr,rgb([40,90,40,255],b.pixel),b);
      const c=frame('forward again DPR'+dpr,'background',[record('forward')],dpr);
      check('forward legacy forward stable '+dpr,rgb(a.pixel,c.pixel),{a:a.pixel,c:c.pixel});
      const fallback=frame('unverified default green DPR'+dpr,'background',[record('unverified')],dpr);
      check('textureVFlip absent legacy green '+dpr,rgb([40,90,40,255],fallback.pixel),fallback);
      frame('false before terrain DPR'+dpr,'background',[record('forward')],dpr);
      const terrain=frame('terrain after false DPR'+dpr,'asymmetric',[],dpr);
      check('terrain resets default flip '+dpr,rgb([40,90,40,255],terrain.pixel),terrain);
      const behind={...record('forward'),positionYup:[0,0,10]};
      const unitRecord={id:7,unitId:'synthetic',clip:'idle',frame:0,positionYup:[0,0,0],headingRadians:0,scaleFactor:1,posePolicy:'engine-pose-v1',sourceScope:'engineering'};
      const after=frame('unit after false prop DPR'+dpr,'background',[behind],dpr,[unitRecord]);
      check('unit resets default flip after prop '+dpr,rgb([40,90,40,255],after.pixel),after);
    }
    report.status='PASS';
  }catch(error){report.errors.push(String(error));}
  finally{try{prepared?.dispose();report.cleanupComplete=true;}catch(error){report.errors.push('cleanup '+error);report.status='FAIL';}}
  window.flowerGPUReport=report;window.meshGPUReport=report;
  document.getElementById('result').textContent=JSON.stringify(report,null,2);document.body.dataset.status=report.status;
})();
