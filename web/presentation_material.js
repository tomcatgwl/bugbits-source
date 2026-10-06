/* Original arithmetic with finite world01 material evidence; engineering tick scope is explicit. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BugBitsPresentationMaterial=api;})(globalThis,function(){
 'use strict';
 const POLICY='world01-finite-material-v1';
 function vector(a,n,label){if(!Array.isArray(a)||a.length!==n||Array.from(a).some(x=>typeof x!=='number'||!Number.isFinite(x)||!Number.isFinite(Math.fround(x))))throw TypeError(label);return [...a];}
 function frameLight(snapshot){
  const s=snapshot?.presentation?.lightState;
  if(!s||s.version!=='setlight-state-v1'||s.scope!=='fixed-20hz-static-setlight-v1'||!Number.isSafeInteger(s.tick)||s.tick<0||s.tick!==snapshot.tick||!Number.isSafeInteger(s.requestTick)||s.requestTick<0||s.requestTick>s.tick)throw TypeError('explicit same-tick setlight state');
  if(!Array.isArray(s.sourceTokens)||s.sourceTokens.length!==9||Array.from(s.sourceTokens).some(x=>typeof x!=='string'||!x||x.split(/\s+/).length!==1)||!['level','script'].includes(s.source))throw TypeError('setlight source');
  for(const p of [s.current,s.target]){
   vector(p?.colors,3,'packed setlight colors');if(p.colors.some(x=>!Number.isInteger(x)||x<0||x>0xffffffff))throw TypeError('packed setlight DWORD');
   vector(p.scalars,2,'setlight scalar slots');vector(p.anglesDegrees,3,'setlight angle slots');
  }
  for(const k of ['duration','requestedDuration','transitionElapsed'])if(typeof s[k]!=='number'||!Number.isFinite(s[k])||s[k]<0)throw TypeError('setlight transition');
  if(typeof s.transitionActive!=='boolean'||s.transitionActive!==(s.duration>0)||s.transitionElapsed>s.duration||!s.transitionActive&&s.transitionElapsed!==0)throw TypeError('setlight transition identity');
  const c=s.current,rad=.01745329238474369;
  // The world01 source domain has middle angle zero. Its captured positive
  // direction is (−cos(pitch)sin(yaw), cos(pitch)cos(yaw), sin(pitch)).
  // Other angle domains require the original matrix consumer to be closed.
  if(c.anglesDegrees[1]!==0)throw TypeError('unverified world01 middle angle');
  const pitch=c.anglesDegrees[0]*rad,yaw=c.anglesDegrees[2]*rad;
  const raw=[-Math.cos(pitch)*Math.sin(yaw),Math.cos(pitch)*Math.cos(yaw),Math.sin(pitch)];
  const rgb=p=>[16,8,0].map(shift=>(p>>>shift&255)/255);
  return {ambientBytes:[16,8,0].map(shift=>c.colors[1]>>>shift&255),light:rgb(c.colors[2]).map(v=>v*c.scalars[0]*.5),
   direction:[raw[1],raw[2],-raw[0]],fogColor:rgb(c.colors[0]),fogStart:316.0359191894531,fogEnd:839.71630859375,
   scope:s.scope,requestTick:s.requestTick,materialScope:'captured-r344-world01-v1',fogDistanceScope:'captured-r344-distance-v1'};
 }
 function group(name,index){
  const counts={clods:1,ground:1,flower_a:2,dandelion_a:2,grass:3,grass_pieces_a_01:1,grass_pieces_a_2:1,pebbles_a:1,schamrock_a:1,schamrock_b:1};
  if(!Number.isInteger(index)||index<0||index>=(counts[name]??0))return null;
  const ground=['clods','ground'].includes(name),unlit=name==='dandelion_a'&&index===0,dim=name==='schamrock_b';
  return {lighting:!unlit,diffuse:ground?[.9000000357627869,.9000000357627869,.9000000357627869]:dim?[.10000000149011612,.10000000149011612,.10000000149011612]:[1,1,1],
   ambientScale:ground?.75:dim?2.25:1,factor:unlit?1:2,alphaRef:(ground||unlit?1:64)/255,diffuseAlpha:1,alphaBlend:!ground,
   passes:(ground?[3]:[2,3]).map(cull=>({cull,dstBlend:unlit?2:6,zWrite:unlit?0:1}))};
 }
 // R361: exact ant group0 indices/full UV/color and current FFP state.
 // One Cull3 draw observed; other passes, instance/clip and camera fog updates
 // are unverified. Never select this policy using a plant material name.
 function unitGroup(unit,index){
  const b=unit?.groups?.[index]?.unitMaterial;
  if(unit?.unitId!=='ant'||unit.modelSHA!=='7296121d8f72f588d1591acfdafa7e48fad599322a26fc2ac467673a5bf61067'||index!==0||b?.groupIndex!==0||b.name!=='SYSTEM/lightedbright'||b.source!=='scripts/bugs/ant.vsc'||b.sourceSHA256!=='35fcdadaeff1db148abc9e4495caf6fdbd3e7d8c397ded47be6cb5269b35f4ad'||b.bindingScope!=='script-unit-material-v1')return null;
  return {lighting:true,color1:true,diffuse:[1,1,1],ambientScale:1,factor:2,alphaRef:1/255,diffuseAlpha:1,alphaBlend:false,
   passes:[{cull:3,dstBlend:6,zWrite:1}],fogStart:139.92567443847656,fogEnd:735.642822265625,
   scope:'captured-r361-ant-group0-conditional-v1',fogDistanceScope:'captured-r361-distance-v1'};
 }
 function owner(direction){
  let f=vector(direction,3,'flower raw direction'),length=Math.hypot(...f);if(!length||!Number.isFinite(length))throw TypeError('nonzero finite flower direction');f=f.map(v=>v/length);
  let c=[f[1],-f[0],0],cl=Math.hypot(...c);if(!cl)throw TypeError('unsupported up-parallel flower direction');c=c.map(v=>v/cl);
  const u=[f[1]*c[2]-f[2]*c[1],f[2]*c[0]-f[0]*c[2],f[0]*c[1]-f[1]*c[0]],raw=[c,f,u.map(v=>-v)];
  const Q=[[0,0,1],[-1,0,0],[0,-1,0]],mul=(a,b)=>a.map(row=>[0,1,2].map(j=>row.reduce((sum,v,k)=>sum+v*b[k][j],0)));
  const result=mul(mul(Q[0].map((_,i)=>Q.map(row=>row[i])),raw),Q);
  return [...result.flatMap(row=>[...row,0]),0,0,0,1];
 }
 return {POLICY,frameLight,group,unitGroup,owner};
});
