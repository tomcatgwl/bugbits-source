/* Real geometry consumer. Engineering root/pose/owner policies are explicit. */
(function(root, factory) {
  const api=factory(typeof module==='object'&&module.exports?require('./camera_projection.js'):root.BugBitsCameraProjection,
    typeof module==='object'&&module.exports?require('./presentation_material.js'):root.BugBitsPresentationMaterial,
    typeof module==='object'&&module.exports?require('./flower_pose.js'):root.BugBitsFlowerPose);
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.BugBitsMeshScene=api;
})(typeof globalThis==='object'?globalThis:this,function(camera,material,flowerPose) {
  'use strict';
  const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  function numbers(a,n,label) {
    if(!Array.isArray(a)&&!ArrayBuffer.isView(a))throw new TypeError(label);
    if(a.length!==n||Array.from(a).some(x=>typeof x!=='number'||!Number.isFinite(x)))throw new TypeError(label);
    return Array.from(a);
  }
  function matrix(a) { const m=numbers(a,16,'affine row matrix');if(m[3]!==0||m[7]!==0||m[11]!==0||m[15]!==1)throw new TypeError('affine row matrix');return m; }
  function apply(p,m) {return [0,1,2].map(j=>p[0]*m[j]+p[1]*m[4+j]+p[2]*m[8+j]+m[12+j]);}
  function bodyDirectionOwner(direction) {
    const d=numbers(direction,3,'body direction');
    let f=[d[2],-d[0],-d[1]]; // inverse raw->canonical Q
    if(f.every(v=>v===0))f=[0,1,0]; // 443090 zero-direction substitute
    const length=Math.hypot(...f);
    if(!Number.isFinite(length))throw new TypeError('finite body direction norm');
    f=f.map(v=>v/length);
    // 405560: raw up=(0,0,-1), C=normalize(up cross F), U=F cross C.
    // Parallel up retains the original rank-one basis; no invented side axis.
    const sideLength=Math.hypot(f[0],f[1]);
    const c=sideLength?[f[1]/sideLength,-f[0]/sideLength,0]:[0,0,0];
    const u=[f[1]*c[2]-f[2]*c[1],f[2]*c[0]-f[0]*c[2],f[0]*c[1]-f[1]*c[0]];
    const raw=[c,f,u.map(v=>-v)],Q=[[0,0,1],[-1,0,0],[0,-1,0]];
    const mul=(a,b)=>a.map(row=>[0,1,2].map(j=>row.reduce((sum,v,k)=>sum+v*b[k][j],0)));
    const owner=mul(mul(Q[0].map((_,i)=>Q.map(row=>row[i])),raw),Q);
    return [...owner.flatMap(row=>[...row,0]),0,0,0,1];
  }
  function parameters(unit,draw) {
    if(draw.sourceScope!=='engineering'||draw.posePolicy!=='engine-pose-v1')throw new TypeError('explicit engineering pose required');
    const scale=draw.scaleFactor??unit.scaleFactor;
    let heading=draw.headingRadians??0,owner=draw.ownerMatrix??I;
    const orientationPolicy=draw.orientationPolicy??'legacy-yaw-v1';
    if(orientationPolicy==='normal-body-direction-roll0-v1'){
      if(Object.hasOwn(draw,'ownerMatrix')||Object.hasOwn(draw,'headingRadians'))throw new TypeError('body direction cannot also consume owner or yaw');
      owner=bodyDirectionOwner(draw.directionYup);heading=0;
    }else if(orientationPolicy!=='legacy-yaw-v1'||Object.hasOwn(draw,'directionYup'))throw new TypeError('unit orientation policy');
    if(typeof scale!=='number'||!Number.isFinite(scale)||typeof heading!=='number'||!Number.isFinite(heading))throw new TypeError('finite scale/heading');
    return {anchor:numbers(unit.anchor,3,'anchor'),root:matrix(draw.rootMatrixOverride??unit.rootMatrix),owner:matrix(owner),parent:matrix(draw.parentMatrix??I),position:numbers(draw.positionYup,3,'position'),scale,heading,orientationPolicy};
  }
  function transformVertex(position,unit,draw) {
    const p=numbers(position,3,'vertex'),d=parameters(unit,draw);
    const r=apply(p.map((v,i)=>(v-d.anchor[i])*d.scale),d.root),q=[-r[1],-r[2],r[0]];
    const c=Math.cos(d.heading),s=Math.sin(d.heading),h=[c*q[0]+s*q[2],q[1],-s*q[0]+c*q[2]];
    return apply(apply(h,d.owner),d.parent).map((v,i)=>v+d.position[i]);
  }
  function transformNormal(normal,unit,draw) {
    const d=parameters(unit,draw),vector=(p,m)=>[0,1,2].map(j=>p[0]*m[j]+p[1]*m[4+j]+p[2]*m[8+j]);
    const r=vector(numbers(normal,3,'normal'),d.root),q=[-r[1],-r[2],r[0]];
    const c=Math.cos(d.heading),s=Math.sin(d.heading),h=[c*q[0]+s*q[2],q[1],-s*q[0]+c*q[2]];
    // Match shader w=0; neither position nor scale is applied to normals.
    return vector(vector(h,d.owner),d.parent);
  }
  function propParameters(prop,draw) {
    if(prop.frameBasis!=='raw-model-v1'||prop.rootApplied!==false||prop.scaleApplied!==false||!['engineering-prop-bind-v1','original-load-bind-S-v1'].includes(prop.rootPolicy)||prop.coordinatePolicy!=='raw-to-engine-yup-Q-v1'||prop.anchorPolicy!=='raw-model-origin-v1')throw new TypeError('explicit prop raw basis/policy');
    if(prop.rootPolicy==='original-load-bind-S-v1'){
      const phi=Math.fround(-Math.PI/2),c=Math.cos(phi),s=Math.sin(phi),expected=[1,0,0,0,0,c,s,0,0,-s,c,0,0,0,0,1];
      if(!Array.isArray(prop.rootMatrix)||prop.rootMatrix.length!==16||prop.rootMatrix.some((v,i)=>typeof v!=='number'||!Number.isFinite(v)||Math.abs(v-expected[i])>1e-12))throw new TypeError('original loaded root S required');
    }
    if(draw.transformScope!=='engineering-bind-owner-v1'||draw.transformPolicy!=='engine-prop-v1'||draw.scaleApplied===true||draw.rootApplied===true||Object.hasOwn(draw,'anchor')||Object.hasOwn(draw,'headingRadians'))throw new TypeError('explicit prop transform policy/no duplicate transform');
    if(typeof draw.scaleFactor!=='number'||!Number.isFinite(draw.scaleFactor)||draw.scaleFactor<=0)throw new TypeError('prop scale');
    function rigid(value){const m=matrix(value);for(let i=0;i<3;i++)for(let j=0;j<3;j++){let dot=0;for(let k=0;k<3;k++)dot+=m[4*i+k]*m[4*j+k];if(Math.abs(dot-(i===j?1:0))>1e-6)throw new TypeError('prop rigid orthogonal matrix required');}return m;}
    return {root:rigid(prop.rootMatrix),owner:rigid(draw.ownerMatrix),parent:rigid(draw.parentMatrix),position:numbers(draw.positionYup,3,'prop position'),scale:draw.scaleFactor};
  }
  function transformPropVertex(position,prop,draw) {
    const d=propParameters(prop,draw),r=apply(numbers(position,3,'prop vertex').map(v=>v*d.scale),d.root),q=[-r[1],-r[2],r[0]];
    return apply(apply(q,d.owner),d.parent).map((v,i)=>v+d.position[i]);
  }
  function transformPropNormal(normal,prop,draw) {
    const d=propParameters(prop,draw);
    const vector=(p,m)=>[0,1,2].map(j=>p[0]*m[j]+p[1]*m[4+j]+p[2]*m[8+j]);
    const r=vector(numbers(normal,3,'prop normal'),d.root),q=[-r[1],-r[2],r[0]],v=vector(vector(q,d.owner),d.parent),length=Math.hypot(...v);
    if(!length)throw new TypeError('nonzero prop normal');return v.map(x=>x/length);
  }
  // R355 queued +BB: replace the old basis by Rz * inverse VIEW, retain T.
  // This supports centred +D4=0, ordinary +B9=0 quads; no model S/owner here.
  function spriteVertices(record,projection) {
    camera.validateProjection(projection);
    if(record?.basisPolicy!=='queued-camera-basis-v1')throw new TypeError('sprite queued basis policy');
    const position=numbers(record.positionYup,3,'sprite world position');
    for(const key of ['width','height','angleRadians'])if(typeof record[key]!=='number'||!Number.isFinite(record[key])||(key!=='angleRadians'&&record[key]<0))throw new TypeError('sprite dimensions/angle');
    const c=Math.cos(record.angleRadians),s=Math.sin(record.angleRadians),right=projection.basis9.slice(0,3),up=projection.basis9.slice(3,6);
    return [[-.5,.5],[.5,.5],[-.5,-.5],[.5,-.5]].flatMap(([x,y])=>{
      const px=x*record.width,py=y*record.height,rx=c*px-s*py,ry=s*px+c*py;
      return position.map((v,i)=>v+rx*right[i]+ry*up[i]);
    });
  }
  const CLIPS=['walk','idle','normal_attack','hurt','special_attack','special_move'];
  function diffuseBytes(colors) {
    if(!Array.isArray(colors)||Array.from(colors).some(c=>!Number.isSafeInteger(c)||c<0||c>0xffffffff))throw new TypeError('packed unit diffuse DWORD');
    return Uint8Array.from(colors.flatMap(c=>[c>>>16&255,c>>>8&255,c&255,c>>>24&255]));
  }
  // Current nectar position recurrence from the original carry fragment.
  // Engineering 20Hz / first update next tick; original variable dt remains open.
  function nectarCarryPosition(carry,initial,bugPosition,radius,tick) {
    if(carry?.scope!=='pickup-trajectory-20hz-v1'||!Number.isSafeInteger(tick)||tick<0||!Number.isSafeInteger(carry.tick)||carry.tick<0||carry.tick>tick||typeof radius!=='number'||!Number.isFinite(radius)||radius<=0)throw new TypeError('nectar carry clock/radius');
    const age=tick-carry.tick,history=carry.positions;
    if(!Array.isArray(history)||history.length!==Math.min(age,10))throw new TypeError('nectar carry contiguous trajectory');
    const f=Math.fround,target=p=>numbers(p,3,'nectar bug position').map((v,i)=>f(v+(i===1?radius:0)));
    const points=Array.from(history,p=>target(p)),current=target(bugPosition);
    let position=numbers(initial,3,'nectar pickup position').map(f);
    if(age>10)return current;
    let elapsed=0;
    for(const point of points){elapsed=f(elapsed+f(1/20));const w=elapsed>.5?1:f(elapsed/.5);
      position=position.map((v,i)=>f(f(v*(1-w))+f(point[i]*w)));}
    return position;
  }
  function resourcePath(file) {return typeof file==='string'&&file.length>0&&!file.startsWith('/')&&!file.includes('\\')&&!file.split('/').includes('..')&&!/^[a-z]+:/i.test(file);}
  function effectivePropRecord(assets,worldId,observed,record) {
    if(observed&&worldId==='world_01'&&record.assetId==='flower_a'){
      const matches=(assets.worlds[worldId].propVariants?.normal??[]).filter(p=>record.id==='flower:'+p.name);
      if(matches.length!==1)throw TypeError('unique normal flower Direction required');
      return {...record,ownerMatrix:material.owner(matches[0].directionRaw),ownerPolicy:'static-ceFlower-direction-c-f-minus-u-v1'};
    }
    return record;
  }
  function frameBufferRecord(record) {
    if(!record||record.format!=='f32le-pose-v1'||!resourcePath(record.file)||!/^[a-f0-9]{64}$/.test(record.sha256??'')||!Number.isSafeInteger(record.byteLength)||record.byteLength<0||record.byteLength%4)throw new TypeError('binary frame buffer identity');
    return record;
  }
  function frameReference(ref,count,byteLength) {
    if(!ref||Array.isArray(ref)||ArrayBuffer.isView(ref)||Object.keys(ref).length!==2||!Number.isSafeInteger(ref.offset)||ref.offset<0||ref.offset%4||ref.count!==count||!Number.isSafeInteger(count)||ref.offset+count*4>byteLength)throw new TypeError('binary frame range');
    return ref;
  }
  async function decodeUnitFrameBuffer(unit,bytes) {
    const record=frameBufferRecord(unit.frameBuffer),count=unit.positions?.length;
    if(!(bytes instanceof ArrayBuffer)||bytes.byteLength!==record.byteLength)throw new TypeError('binary frame byte length');
    const ranges=[];
    for(const clip of Object.values(unit.clips??{}))for(const frame of clip.frames??[])for(const field of ['positions','normals'])ranges.push(frameReference(frame[field],count,bytes.byteLength));
    let end=0;for(const ref of ranges){if(ref.offset!==end)throw new TypeError('binary frame order/overlap/unreferenced range');end+=ref.count*4;}
    if(end!==bytes.byteLength)throw new TypeError('binary frame unreferenced bytes');
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
    if(hash!==record.sha256)throw new Error('binary frame SHA mismatch');
    const littleEndian=new Uint8Array(new Uint16Array([1]).buffer)[0]===1,view=new DataView(bytes),clips={};
    function values(ref){
      const result=littleEndian?new Float32Array(bytes,ref.offset,ref.count):Float32Array.from({length:ref.count},(_,i)=>view.getFloat32(ref.offset+4*i,true));
      for(const value of result)if(!Number.isFinite(value))throw new TypeError('finite binary frame values');return result;
    }
    for(const [key,clip] of Object.entries(unit.clips))clips[key]={...clip,frames:(clip.frames??[]).map(frame=>({positions:values(frame.positions),normals:values(frame.normals)}))};
    return {...unit,clips};
  }
  function validateAssets(assets,requiredUnitIds=[]) {
    if(!assets||assets.schema!=='engine-mesh-v1'||assets.posePolicy!=='engine-pose-v1'||!assets.units||!assets.worlds||!assets.textures)throw new TypeError('engine mesh schema');
    if(Object.hasOwn(assets,'unitMaterialContract')&&assets.unitMaterialContract!=='script-diffuse-unit-v1')throw new TypeError('unit material contract');
    if(Object.hasOwn(assets,'nectarCarryContract')&&assets.nectarCarryContract!=='same-bug-radius-trajectory-v1')throw new TypeError('nectar carry contract');
    for(const id of requiredUnitIds)if(!Object.hasOwn(assets.units,id))throw new TypeError('missing unit '+id);
    function mesh(m,propId=null) {
      const hasFlip=Object.hasOwn(m,'textureVFlip'),hasScope=Object.hasOwn(m,'textureUvScope');
      if(hasFlip||hasScope){
        if(!hasFlip||!hasScope||typeof m.textureVFlip!=='boolean'||
            !['engineering-explicit-v1','observed-normal-flower-a-v1'].includes(m.textureUvScope)||
            (m.textureUvScope==='observed-normal-flower-a-v1'&&
             (propId!=='flower_a'||m.assetId!=='flower_a'||m.textureVFlip!==false)))throw new TypeError('texture UV policy/scope');
      }
      const n=m.positions?.length/3;
      if(!Number.isSafeInteger(n)||n<1)throw new TypeError('positions');
      numbers(m.positions,n*3,'positions');numbers(m.normals,n*3,'normals');numbers(m.uvs,n*2,'UV');
      if(!Array.isArray(m.groups)||!m.groups.length)throw new TypeError('groups');
      for(const g of m.groups){
        if(!Array.isArray(g.indices)||!g.indices.length||g.indices.length%3||g.indices.some(i=>!Number.isSafeInteger(i)||i<0||i>=n))throw new TypeError('mesh index');
        if(g.texture!==null&&!Object.hasOwn(assets.textures,g.texture))throw new TypeError('missing texture '+g.texture);
      }
      return n;
    }
    for(const [uid,u] of Object.entries(assets.units)) {
      const n=mesh(u);numbers(u.anchor,3,'anchor');matrix(u.rootMatrix);
      if(Object.hasOwn(assets,'nectarCarryContract')){
        if(typeof u.radius!=='number'||!Number.isFinite(u.radius)||u.radius<=0||u.radiusSource!=='scripts/bugs/'+uid+'.vsc'||!/^[a-f0-9]{64}$/.test(u.radiusSourceSHA256??''))throw new TypeError('unit radius source');
        if(assets.inputHashes&&assets.inputHashes[u.radiusSource]!==u.radiusSourceSHA256)throw new TypeError('unit radius source closure');
      }
      if(Object.hasOwn(assets,'unitMaterialContract')){
        if(u.unitId!==uid||u.diffuseScope!=='raw-bind-diffuse-v1'||!Array.isArray(u.diffuseARGB)||u.diffuseARGB.length!==n||!resourcePath(u.modelSource)||!/^[a-f0-9]{64}$/.test(u.modelSHA??''))throw new TypeError('unit diffuse/model identity');
        diffuseBytes(u.diffuseARGB);
        for(const [index,g] of u.groups.entries()){
          const b=g.unitMaterial;
          if(!b||b.bindingScope!=='script-unit-material-v1'||b.groupIndex!==index||!Number.isSafeInteger(b.groupIndex)||b.source!=='scripts/bugs/'+uid+'.vsc'||!/^[a-f0-9]{64}$/.test(b.sourceSHA256??'')||b.name!==null&&(typeof b.name!=='string'||!b.name||b.name.trim().split(/\s+/).length!==1))throw new TypeError('unit script material binding');
          if(assets.inputHashes&&assets.inputHashes[b.source]!==b.sourceSHA256)throw new TypeError('unit material source closure');
        }
        if(assets.inputHashes&&assets.inputHashes[u.modelSource]!==u.modelSHA)throw new TypeError('unit model source closure');
      }else if(Object.hasOwn(u,'diffuseARGB')||Object.hasOwn(u,'diffuseScope')||u.groups.some(g=>Object.hasOwn(g,'unitMaterial')))throw new TypeError('missing unit material contract');
      const binary=u.frameBuffer===undefined?null:frameBufferRecord(u.frameBuffer);
      if(u.rootPolicy!=='engineering-fixed-S-v1'||u.coordinatePolicy!=='raw-to-engine-yup-Q-v1'||u.anchorPolicy!=='raw-bind-ground-pivot-v1'||u.frameBasis!=='raw-model-v1'||u.rootApplied!==false||u.scaleApplied!==false||typeof u.scaleFactor!=='number'||!Number.isFinite(u.scaleFactor))throw new TypeError('explicit engineering root/scale');
      for(const key of CLIPS){
        const clip=u.clips?.[key];if(!clip||!['sampled','static','missing'].includes(clip.kind))throw new TypeError('clip '+key);
        if(clip.kind==='missing'){if(clip.fallbackClip!==null&&!CLIPS.includes(clip.fallbackClip))throw new TypeError('clip fallback');continue;}
        if(typeof clip.duration!=='number'||!Number.isFinite(clip.duration)||clip.duration<0||typeof clip.loop!=='boolean'||!Array.isArray(clip.frames)||!clip.frames.length||!Array.isArray(clip.sampleTimes)||clip.sampleTimes.length!==clip.frames.length)throw new TypeError('clip frames');
        numbers(clip.sampleTimes,clip.frames.length,'sample times');
        if(clip.sampleTimes.some((t,i)=>t<0||t>clip.duration||(i>0&&t<=clip.sampleTimes[i-1])))throw new TypeError('ordered sample times');
        for(const frame of clip.frames){if(binary){frameReference(frame.positions,n*3,binary.byteLength);frameReference(frame.normals,n*3,binary.byteLength);}else{numbers(frame.positions,n*3,'pose vertices');numbers(frame.normals,n*3,'pose normals');}}
      }
      for(const key of CLIPS){let c=key;const seen=new Set();while(u.clips[c].kind==='missing'&&u.clips[c].fallbackClip!==null){if(seen.has(c))throw new TypeError('clip fallback cycle');seen.add(c);c=u.clips[c].fallbackClip;}}
    }
    for(const w of Object.values(assets.worlds)){
      if(!['loaded-yup-v1','legacy-grid-v1'].includes(w.basisVersion)||!Array.isArray(w.meshes)||!w.meshes.length)throw new TypeError('world mesh basis');
      for(const m of w.meshes)mesh(m);
    }
    if(assets.props!==undefined){
      if(!assets.props||Array.isArray(assets.props)||typeof assets.props!=='object')throw new TypeError('prop assets');
      for(const [id,p] of Object.entries(assets.props)){
        mesh(p,id);propParameters(p,{positionYup:[0,0,0],scaleFactor:1,ownerMatrix:I,parentMatrix:I,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1'});
        if(p.animationScope==='normal-flower-node-keys-v1'){
          if(!flowerPose)throw new TypeError('flower pose module required');
          flowerPose.validateProp(p);
          const r=p.animationRig;
          if(r.assetId!==id||p.nodeCount!==r.nodes.length)throw new TypeError('flower rig identity');
          if(assets.inputHashes&&(assets.inputHashes[r.modelSource]!==r.modelSHA||assets.inputHashes[r.animationSource]!==r.animationSHA))throw new TypeError('flower animation source closure');
        }else if(['animationRig','animationRigJson','animationSkin'].some(k=>Object.hasOwn(p,k)))throw new TypeError('flower animation scope required');
        if(p.attachments!==undefined){
          if(!p.attachments||Array.isArray(p.attachments)||typeof p.attachments!=='object')throw new TypeError('prop attachments');
          for(const [name,a] of Object.entries(p.attachments)){
            if(name!=='nektar'||a?.name!==name||a.poseScope!=='bind-model-attachment-v1'||!Number.isSafeInteger(p.nodeCount)||!Number.isSafeInteger(a.node)||a.node<0||a.node>=p.nodeCount||!Array.isArray(a.parentChain)||a.parentChain[0]!==a.node||new Set(a.parentChain).size!==a.parentChain.length||a.parentChain.some(i=>!Number.isSafeInteger(i)||i<0||i>=p.nodeCount))throw new TypeError('named bind attachment');
            numbers(a.positionRaw,3,'attachment position');
          }
        }
      }
    }
    if(assets.nectarSprites!==undefined){const n=assets.nectarSprites;
      if(n?.contract!=='bind-flower-nectar-v1'||!['texture','glowTexture'].every(k=>typeof n[k]==='string'&&Object.hasOwn(assets.textures,n[k])))throw new TypeError('nectar sprite texture contract');}
    if(Object.hasOwn(assets,'propVariantContract')&&assets.propVariantContract!=='level-flower-variants-v1')throw new TypeError('prop variant contract');
    for(const w of Object.values(assets.worlds)){
      if(!Object.hasOwn(assets,'propVariantContract')){
        if(Object.hasOwn(w,'propVariants'))throw new TypeError('missing prop variant contract');
        continue;
      }
      if(Object.hasOwn(w,'propInstances')||!w.propVariants||Array.isArray(w.propVariants)||typeof w.propVariants!=='object'||!Object.keys(w.propVariants).length)throw new TypeError('world prop variants');
      for(const [variant,instances] of Object.entries(w.propVariants)){
        if(!['normal','rescue'].includes(variant)||!Array.isArray(instances))throw new TypeError('prop variant');
        const seen=new Set();
        for(const instance of instances){
          if(variant==='rescue'&&instance?.flowerType===2)throw new TypeError('unverified original type2 rescue model binding');
          const spec={1:['flower_a',2.5],2:['flower_b',2.5],3:['cactus_a',1]}[instance?.flowerType];
          if(!instance||typeof instance.name!=='string'||!instance.name||seen.has(instance.name)
              ||!Number.isInteger(instance.flowerType)||!spec||instance.rescue!==(variant==='rescue')
              ||instance.assetId!==spec[0]+(variant==='rescue'?'_swap':'')
              ||instance.scaleFactor!==(variant==='rescue'&&instance.flowerType===1?4:spec[1])
              ||!Object.hasOwn(assets.props??{},instance.assetId))throw new TypeError('prop variant instance');
          seen.add(instance.name);propParameters(assets.props[instance.assetId],instance);
        }
      }
    }
    for(const texture of Object.values(assets.textures)) {
      const {width,height}=texture;
      if(!Number.isSafeInteger(width)||!Number.isSafeInteger(height)||width<1||height<1||width>8192||height>8192)throw new TypeError('texture extent');
      if(texture.pixels){const pixels=numbers(texture.pixels,width*height*4,'texture pixels');if(pixels.some(x=>!Number.isInteger(x)||x<0||x>255))throw new TypeError('RGBA bytes');}
      else if(!resourcePath(texture.file)||!/^[a-f0-9]{64}$/.test(texture.sha256??texture.fileSHA256??''))throw new TypeError('encoded texture path/SHA');
    }
    return assets;
  }
  const VS=`#version 300 es
  precision highp float;
  layout(location=0) in vec3 aPosition; layout(location=1) in vec2 aUV;layout(location=2) in vec3 aNormal;layout(location=3) in vec4 aDiffuse;
  uniform bool uUnit; uniform vec3 uAnchor,uPosition; uniform float uScale,uHeading;
  uniform mat4 uRoot,uOwner,uParent;
  uniform vec3 uC,uR0,uR1,uR2; uniform float uCot,uAspect,uNear,uFar;
  uniform bool uLit,uColor1;uniform vec3 uAmbient,uDiffuse,uLight,uDirection;
  out vec2 vUV;out vec3 vLit;out float vEye,vDiffuseAlpha;
  void main(){
    vec3 world=aPosition;
    if(uUnit){vec3 raw=(uRoot*vec4((aPosition-uAnchor)*uScale,1.0)).xyz;
      vec3 q=vec3(-raw.y,-raw.z,raw.x);float c=cos(uHeading),s=sin(uHeading);
      vec3 h=vec3(c*q.x+s*q.z,q.y,-s*q.x+c*q.z);
      world=(uParent*uOwner*vec4(h,1.0)).xyz+uPosition;}
    vec3 d=world-uC;vec3 p=vec3(dot(uR0,d),dot(uR1,d),dot(uR2,d));
    float A=(uFar+uNear)/(uFar-uNear),B=-2.0*uFar*uNear/(uFar-uNear);
    gl_Position=vec4(uCot*p.x/uAspect,uCot*p.y,A*p.z+B,p.z);vUV=aUV;
    vEye=p.z;vec3 n=aNormal;if(uUnit){vec3 r=(uRoot*vec4(aNormal,0.0)).xyz;vec3 q=vec3(-r.y,-r.z,r.x);float c=cos(uHeading),s=sin(uHeading);n=(uParent*uOwner*vec4(c*q.x+s*q.z,q.y,-s*q.x+c*q.z,0.0)).xyz;}
    vLit=uLit?clamp(uAmbient+uDiffuse*uLight*max(dot(n,uDirection),0.0),0.0,1.0):vec3(1.0);
    float ndl=dot(n,uDirection);if(ndl<0.0)ndl=0.0;
    if(uColor1)vLit=uLit?clamp(aDiffuse.rgb*(uAmbient+uDiffuse*uLight*ndl),0.0,1.0):aDiffuse.rgb;
    vDiffuseAlpha=uColor1?aDiffuse.a:1.0;
  }`;
  const FS=`#version 300 es
  precision highp float;uniform sampler2D uTexture;uniform bool uVFlip,uObserved,uSprite,uColor1;
  uniform vec4 uVertexColor;
  uniform float uFactor,uAlphaRef,uDiffuseAlpha,uFogStart,uFogEnd;uniform vec3 uFogColor;
  in vec2 vUV;in vec3 vLit;in float vEye,vDiffuseAlpha;out vec4 color;
  void main(){vec4 t=texture(uTexture,vec2(vUV.x,uVFlip?1.0-vUV.y:vUV.y));
    if(uSprite){t*=uVertexColor;if(t.a<1.0/255.0)discard;color=t;return;}
    if(t.a*(uObserved?uDiffuseAlpha:1.0)*vDiffuseAlpha<(uObserved?uAlphaRef:64.0/255.0))discard;
    color=vec4(uObserved?clamp(t.rgb*vLit*uFactor,0.0,1.0):min(vec3(1.0),t.rgb*.25+vec3(40.0/255.0)),uObserved?clamp(t.a*uDiffuseAlpha,0.0,1.0):1.0);
    if(uColor1)color.a*=vDiffuseAlpha;
    if(uObserved){float f=clamp((uFogEnd-vEye)/(uFogEnd-uFogStart),0.0,1.0);color.rgb=mix(uFogColor,color.rgb,f);}}`;
  async function prepareMeshScene({assets,projection,signal,baseURL,worldId,requiredUnitIds=[],unitIds=null,canvas:providedCanvas,materialPolicy=null}={}) {
    validateAssets(assets,requiredUnitIds);camera.validateProjection(projection);
    // Hashing and all subsequent samplers/uploads use one private pre-await snapshot.
    assets=JSON.parse(JSON.stringify(assets));projection=JSON.parse(JSON.stringify(projection));
    if(materialPolicy!==null&&materialPolicy!==material?.POLICY)throw TypeError('mesh material policy');
    const observed=materialPolicy!==null;
    if(!Object.hasOwn(assets.worlds,worldId)||assets.worlds[worldId].basisVersion!=='loaded-yup-v1')throw new TypeError('selected mesh world must be loaded-yup-v1');
    if(unitIds!==null){
      if(!Array.isArray(unitIds)||!unitIds.length||new Set(unitIds).size!==unitIds.length||unitIds.some(id=>typeof id!=='string'||!Object.hasOwn(assets.units,id))||requiredUnitIds.some(id=>!unitIds.includes(id)))throw new TypeError('selected unit dependency closure');
      assets.units=Object.fromEntries(unitIds.map(id=>[id,assets.units[id]]));
      assets.worlds={[worldId]:assets.worlds[worldId]};
      const needed=new Set();
      for(const mesh of [...Object.values(assets.units),...assets.worlds[worldId].meshes,...Object.values(assets.props??{})])for(const group of mesh.groups)if(group.texture!==null)needed.add(group.texture);
      if(assets.nectarSprites){needed.add(assets.nectarSprites.texture);needed.add(assets.nectarSprites.glowTexture);}
      assets.textures=Object.fromEntries([...needed].map(id=>[id,assets.textures[id]]));
    }
    const canvas=providedCanvas??(typeof OffscreenCanvas==='function'?new OffscreenCanvas(640,640):Object.assign(document.createElement('canvas'),{width:640,height:640}));
    const gl=canvas.getContext('webgl2',{alpha:false,antialias:false,preserveDrawingBuffer:true});
    if(!gl)throw new Error('WebGL2 unavailable');
    let disposed=false,lost=false;const buffers=[],textures=[],shaders=[],vaos=[];let program;
    const aborted=()=>{if(signal?.aborted)throw new DOMException('Mesh preparation aborted','AbortError');};
    function wait(promise,lateClose,waitSignal=signal){return new Promise((resolve,reject)=>{
      let settled=false;
      const abort=()=>{if(!settled){settled=true;waitSignal?.removeEventListener('abort',abort);reject(new DOMException('Mesh preparation aborted','AbortError'));}};
      waitSignal?.addEventListener('abort',abort,{once:true});if(waitSignal?.aborted)abort();
      promise.then(value=>{if(settled){lateClose?.(value);return;}settled=true;waitSignal?.removeEventListener('abort',abort);resolve(value);},error=>{if(!settled){settled=true;waitSignal?.removeEventListener('abort',abort);reject(error);}});
    });}
    const loss=()=>{lost=true;};canvas.addEventListener?.('webglcontextlost',loss);
    function dispose(){if(disposed)return;disposed=true;for(const v of vaos)gl.deleteVertexArray(v);for(const b of buffers)gl.deleteBuffer(b);for(const t of textures)gl.deleteTexture(t);for(const s of shaders)gl.deleteShader(s);if(program)gl.deleteProgram(program);canvas.removeEventListener?.('webglcontextlost',loss);}
    try {
      aborted();
      const propSamplers=new Map();
      for(const [id,p] of Object.entries(assets.props??{}))if(p.animationScope==='normal-flower-node-keys-v1'){
        const bytes=new TextEncoder().encode(p.animationRigJson);
        const hash=Array.from(new Uint8Array(await wait(crypto.subtle.digest('SHA-256',bytes))),v=>v.toString(16).padStart(2,'0')).join('');
        if(hash!==p.animationRig.rigSHA256)throw new Error('flower rig SHA mismatch');
        propSamplers.set(id,flowerPose.createSampler(p));aborted();
      }
      function shader(type,source){const s=gl.createShader(type);if(!s)throw new Error('shader allocation');shaders.push(s);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s)||'shader compile');return s;}
      program=gl.createProgram();if(!program)throw new Error('program allocation');gl.attachShader(program,shader(gl.VERTEX_SHADER,VS));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,FS));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program)||'program link');
      const locations={};for(const n of ['Unit','Anchor','Position','Scale','Heading','Root','Owner','Parent','C','R0','R1','R2','Cot','Aspect','Near','Far','Texture','VFlip','Observed','Lit','Ambient','Diffuse','Light','Direction','Factor','AlphaRef','DiffuseAlpha','FogStart','FogEnd','FogColor','Sprite','VertexColor','Color1'])locations[n]=gl.getUniformLocation(program,'u'+n);
      function createTexture(width,height,pixels){const t=gl.createTexture();if(!t)throw new Error('texture allocation');textures.push(t);gl.bindTexture(gl.TEXTURE_2D,t);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
        if(pixels instanceof Uint8Array)gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,width,height,0,gl.RGBA,gl.UNSIGNED_BYTE,pixels);else gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,pixels);if(observed)gl.generateMipmap(gl.TEXTURE_2D);return t;}
      const textureMap=new Map([[null,createTexture(1,1,new Uint8Array([255,255,255,255]))]]);
      // Download independent resources together; decode and GL uploads stay ordered.
      const downloads=new Map(),files=[...new Set([
        ...Object.values(assets.units).filter(u=>u.frameBuffer!==undefined).map(u=>u.frameBuffer.file),
        ...Object.values(assets.textures).filter(t=>!t.pixels).map(t=>t.file)])];
      const transfer=new AbortController();let nextFile=0,transferError=null;
      const abortTransfer=()=>transfer.abort();
      signal?.addEventListener('abort',abortTransfer,{once:true});if(signal?.aborted)abortTransfer();
      async function download(){
        try{
          while(nextFile<files.length){
            aborted();if(transfer.signal.aborted)throw new DOMException('Mesh download aborted','AbortError');
            const file=files[nextFile++];
            const response=await wait(fetch(new URL(file,baseURL??globalThis.location?.href),{signal:transfer.signal}),undefined,transfer.signal);
            if(!response.ok)throw new Error('mesh resource fetch '+response.status);
            downloads.set(file,await wait(response.arrayBuffer(),undefined,transfer.signal));
          }
        }catch(error){if(transferError===null)transferError=error;transfer.abort();throw error;}
      }
      try{
        await Promise.allSettled(Array.from({length:Math.min(4,files.length)},download));
        if(transferError!==null)throw transferError;
        aborted();
      }finally{signal?.removeEventListener('abort',abortTransfer);}
      const runtimeUnits={};
      for(const [id,unit] of Object.entries(assets.units)){
        aborted();
        if(unit.frameBuffer===undefined){runtimeUnits[id]=unit;continue;}
        runtimeUnits[id]=await wait(decodeUnitFrameBuffer(unit,downloads.get(unit.frameBuffer.file)));
      }
      for(const [id,t] of Object.entries(assets.textures)){
        aborted();
        if(t.pixels)textureMap.set(id,createTexture(t.width,t.height,new Uint8Array(t.pixels)));
        else {
          const bytes=downloads.get(t.file);if(t.size!==undefined&&bytes.byteLength!==t.size)throw new Error('encoded texture size');
          const hash=Array.from(new Uint8Array(await wait(crypto.subtle.digest('SHA-256',bytes))),v=>v.toString(16).padStart(2,'0')).join('');
          if(hash!==(t.sha256??t.fileSHA256))throw new Error('texture encoded SHA mismatch');
          const image=await wait(createImageBitmap(new Blob([bytes],{type:'image/png'}),{premultiplyAlpha:'none',colorSpaceConversion:'none'}),image=>image.close());
          try{aborted();if(image.width!==t.width||image.height!==t.height)throw new Error('decoded texture extent');textureMap.set(id,createTexture(t.width,t.height,image));}finally{image.close();}
        }
      }
      downloads.clear();
      function buffer(target,data){const b=gl.createBuffer();if(!b)throw new Error('buffer allocation');buffers.push(b);gl.bindBuffer(target,b);gl.bufferData(target,data,gl.STATIC_DRAW);return b;}
      function gpuMesh(mesh,positions,normals=mesh.normals){
        const vao=gl.createVertexArray();if(!vao)throw new Error('VAO allocation');vaos.push(vao);gl.bindVertexArray(vao);
        const positionBuffer=buffer(gl.ARRAY_BUFFER,new Float32Array(positions));gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,0,0);
        const normalBuffer=buffer(gl.ARRAY_BUFFER,new Float32Array(normals));gl.enableVertexAttribArray(2);gl.vertexAttribPointer(2,3,gl.FLOAT,false,0,0);
        buffer(gl.ARRAY_BUFFER,new Float32Array(mesh.uvs));gl.enableVertexAttribArray(1);gl.vertexAttribPointer(1,2,gl.FLOAT,false,0,0);
        if(mesh.diffuseARGB){buffer(gl.ARRAY_BUFFER,diffuseBytes(mesh.diffuseARGB));gl.enableVertexAttribArray(3);gl.vertexAttribPointer(3,4,gl.UNSIGNED_BYTE,true,0,0);}else{gl.disableVertexAttribArray(3);gl.vertexAttrib4f(3,1,1,1,1);}
        const groups=mesh.groups.map((g,index)=>({state:observed?(mesh.unitId?material.unitGroup(mesh,index):material.group(mesh.materialName,index)):null,buffer:buffer(gl.ELEMENT_ARRAY_BUFFER,new Uint32Array(g.indices)),count:g.indices.length,texture:textureMap.get(g.texture)}));return {vao,groups,positionBuffer,normalBuffer,textureVFlip:mesh.textureVFlip??true};
      }
      const terrain=new Map(Object.entries(assets.worlds).filter(([,w])=>w.basisVersion==='loaded-yup-v1').map(([id,w])=>[id,w.meshes.map(m=>gpuMesh({...m,materialName:id==='world_01'?m.name:null},m.positions))]));
      const props=new Map(Object.entries(assets.props??{}).map(([id,p])=>[id,gpuMesh({...p,materialName:worldId==='world_01'&&id==='flower_a'?id:null},p.positions)]));
      const dynamicProps=new Map();
      function propMesh(record,pose){
        if(!pose)return props.get(record.assetId);
        const key=record.assetId+'|'+record.id;let item=dynamicProps.get(key);
        if(!item){
          const prop=assets.props[record.assetId];
          item={gpu:gpuMesh({...prop,materialName:worldId==='world_01'&&record.assetId==='flower_a'?record.assetId:null},pose.positions,pose.normals),phase:record.animationPhase,pose};
          dynamicProps.set(key,item);
        }else if(item.phase!==record.animationPhase){
          for(const [b,values] of [[item.gpu.positionBuffer,pose.positions],[item.gpu.normalBuffer,pose.normals]]){
            gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(values),gl.DYNAMIC_DRAW);
          }
          item.phase=record.animationPhase;item.pose=pose;
        }
        return item.gpu;
      }
      const frames=new Map();
      function frameMesh(id,clip,frame){const key=id+'|'+clip+'|'+frame;if(!frames.has(key)){const unit=runtimeUnits[id];frames.set(key,gpuMesh(unit,unit.clips[clip].frames[frame].positions,unit.clips[clip].frames[frame].normals));}return frames.get(key);}
      function resolve(unit,key,frame){if(!CLIPS.includes(key))throw new TypeError('unknown clip');let clip=key;while(unit.clips[clip].kind==='missing'){clip=unit.clips[clip].fallbackClip;if(clip===null)return null;}const count=unit.clips[clip].frames.length;if(!Number.isSafeInteger(frame)||frame<0)throw new TypeError('frame index');return {clip,frame:unit.clips[clip].loop?frame%count:Math.min(frame,count-1)};}
      function draw(mesh,light){
        gl.uniform1i(locations.Sprite,0);
        gl.uniform1i(locations.VFlip,mesh.textureVFlip?1:0);gl.bindVertexArray(mesh.vao);
        for(let passIndex=0;passIndex<2;passIndex++)for(const group of mesh.groups){
          const s=light?group.state:null,p=s?.passes[passIndex];if(s&&!p||!s&&passIndex)continue;
          gl.uniform1i(locations.Observed,s?1:0);gl.uniform1i(locations.Lit,s?.lighting?1:0);
          gl.uniform1i(locations.Color1,s?.color1?1:0);
          gl.uniform3fv(locations.Ambient,s?light.ambientBytes.map(v=>Math.min(255,Math.trunc(v*s.ambientScale))/255):[0,0,0]);
          gl.uniform3fv(locations.Diffuse,s?.diffuse??[0,0,0]);gl.uniform3fv(locations.Light,s?light.light:[0,0,0]);gl.uniform3fv(locations.Direction,s?light.direction:[0,0,0]);
          gl.uniform1f(locations.Factor,s?.factor??1);gl.uniform1f(locations.AlphaRef,s?.alphaRef??64/255);gl.uniform1f(locations.DiffuseAlpha,s?.diffuseAlpha??1);
          gl.uniform1f(locations.FogStart,s?.fogStart??light?.fogStart??0);gl.uniform1f(locations.FogEnd,s?.fogEnd??light?.fogEnd??1);gl.uniform3fv(locations.FogColor,light?.fogColor??[0,0,0]);
          if(p){gl.enable(gl.CULL_FACE);gl.frontFace(p.cull===3?gl.CW:gl.CCW);gl.cullFace(gl.BACK);}else gl.disable(gl.CULL_FACE);
          if(s?.alphaBlend){gl.enable(gl.BLEND);gl.blendEquation(gl.FUNC_ADD);gl.blendFunc(gl.SRC_ALPHA,p.dstBlend===2?gl.ONE:gl.ONE_MINUS_SRC_ALPHA);}else gl.disable(gl.BLEND);
          gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.depthMask(p?!!p.zWrite:true);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,group.buffer);gl.bindTexture(gl.TEXTURE_2D,group.texture);
          gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,s?gl.LINEAR_MIPMAP_LINEAR:gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,s?gl.LINEAR:gl.NEAREST);
          gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,s?gl.REPEAT:gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,s?gl.REPEAT:gl.CLAMP_TO_EDGE);
          gl.drawElements(gl.TRIANGLES,group.count,gl.UNSIGNED_INT,0);
        }
      }
      let spriteGPU=null;
      function drawSprite({record,positions,rgba}) {
        if(!spriteGPU){
          const vao=gl.createVertexArray();if(!vao)throw new Error('sprite VAO allocation');vaos.push(vao);gl.bindVertexArray(vao);
          const positionsBuffer=buffer(gl.ARRAY_BUFFER,new Float32Array(12));gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,0,0);
          buffer(gl.ARRAY_BUFFER,new Float32Array([0,1,1,1,0,0,1,0]));gl.enableVertexAttribArray(1);gl.vertexAttribPointer(1,2,gl.FLOAT,false,0,0);
          gl.disableVertexAttribArray(2);gl.vertexAttrib3f(2,0,0,1);
          gl.disableVertexAttribArray(3);gl.vertexAttrib4f(3,1,1,1,1);
          buffer(gl.ELEMENT_ARRAY_BUFFER,new Uint32Array([0,1,2,3,2,1]));spriteGPU={vao,positionsBuffer};
        }
        gl.bindVertexArray(spriteGPU.vao);gl.bindBuffer(gl.ARRAY_BUFFER,spriteGPU.positionsBuffer);gl.bufferSubData(gl.ARRAY_BUFFER,0,new Float32Array(positions));
        gl.uniform1i(locations.Unit,0);gl.uniform1i(locations.Sprite,1);gl.uniform1i(locations.VFlip,0);gl.uniform4fv(locations.VertexColor,rgba);
        gl.disable(gl.CULL_FACE);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.depthMask(false);
        gl.enable(gl.BLEND);gl.blendEquation(gl.FUNC_ADD);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
        gl.bindTexture(gl.TEXTURE_2D,textureMap.get(record.texture));
        // Explicit engineering address policy; original current sampler is unverified.
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
        gl.drawElements(gl.TRIANGLES,6,gl.UNSIGNED_INT,0);
      }
      function setProjection(next) {
        if(disposed||lost||gl.isContextLost())throw new Error('mesh scene disposed/context lost');
        camera.validateProjection(next);
        const candidate=JSON.parse(JSON.stringify(next));camera.validateProjection(candidate);
        projection=candidate;
      }
      function renderFrame({snapshot,drawRecords=[],propRecords=[],spriteRecords=[],dpr=1,worldId:frameWorld=worldId}={}) {
        if(disposed||lost||gl.isContextLost())throw new Error('mesh scene disposed/context lost');
        if(!snapshot||!Number.isSafeInteger(snapshot.tick)||!Array.isArray(drawRecords)||!Array.isArray(propRecords)||!Array.isArray(spriteRecords)||typeof dpr!=='number'||!Number.isFinite(dpr)||dpr<=0||dpr>4)throw new TypeError('frame/tick/DPR');
        const world=terrain.get(frameWorld);if(!world)throw new TypeError('unknown mesh world');
        const light=observed&&frameWorld==='world_01'?material.frameLight(snapshot):null;
        // Validate every record before clear/publication. No half new frame on malformed input.
        const pending=drawRecords.map(record=>{if(!Object.hasOwn(runtimeUnits,record.unitId))throw new TypeError('unknown unit');const unit=runtimeUnits[record.unitId];if(record.rootPolicy&&record.rootPolicy!=='engineering-fixed-S-v1')throw new TypeError('root policy');if(record.anchorPolicy&&record.anchorPolicy!=='raw-bind-ground-pivot-v1')throw new TypeError('anchor policy');return {record,unit,p:parameters(unit,record),resolved:resolve(unit,record.clip,record.frame)};});
        const seenPropIds=new Set();
        const pendingProps=propRecords.map(record=>{if(!Object.hasOwn(assets.props??{},record.assetId))throw new TypeError('unknown prop');
          record=effectivePropRecord(assets,frameWorld,observed,record);
          let pose=null;const sampler=propSamplers.get(record.assetId);
          if(sampler){
            if(typeof record.id!=='string'||!record.id||seenPropIds.has(record.id))throw new TypeError('unique animated prop ID required');
            seenPropIds.add(record.id);
            if(typeof record.animationPhase!=='number'||!Number.isFinite(record.animationPhase)||record.animationPhase<0)throw new TypeError('flower snapshot phase required');
            const previous=dynamicProps.get(record.assetId+'|'+record.id);
            pose=previous?.phase===record.animationPhase?previous.pose:sampler.sample(record.animationPhase);
          }
          return {record,pose,p:propParameters(assets.props[record.assetId],record)};});
        const pendingSprites=spriteRecords.map(record=>{
          if(typeof record?.id!=='string'||!record.id||record.materialPolicy!=='xblended-ctor-conditional-v1'||record.samplerPolicy!=='linear-clamp-engineering-v1'||typeof record.texture!=='string'||!Object.hasOwn(assets.textures,record.texture))throw new TypeError('sprite identity/material/texture');
          const rgba=numbers(record.rgbaBytes,4,'sprite RGBA');if(rgba.some(v=>!Number.isInteger(v)||v<0||v>255))throw new TypeError('sprite RGBA bytes');
          if(record.attachment){
            const a=record.attachment;
            if(a.name!=='nektar'||Object.hasOwn(record,'positionYup'))throw new TypeError('sprite named attachment/no duplicate position');
            const parents=pendingProps.filter(p=>p.record.id===a.propId);
            if(parents.length!==1)throw new TypeError('sprite unique prop attachment');
            const parent=parents[0].record,prop=assets.props[parent.assetId],node=prop.attachments?.[a.name];
            if(node?.poseScope!=='bind-model-attachment-v1'||node.name!==a.name)throw new TypeError('sprite bind attachment scope');
            record={...record,positionYup:transformPropVertex(parents[0].pose?.attachmentPointRaw??node.positionRaw,prop,parent)};
          }
          return {record,positions:spriteVertices(record,projection),rgba:rgba.map(v=>v/255)};
        });
        const size=Math.round(640*dpr);if(canvas.width!==size||canvas.height!==size){canvas.width=size;canvas.height=size;}
        gl.useProgram(program);gl.disable(gl.BLEND);gl.disable(gl.CULL_FACE);gl.disable(gl.SCISSOR_TEST);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.depthMask(true);gl.clearColor(12/255,14/255,16/255,1);gl.clearDepth(1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
        const content=Math.round(size/projection.aspect),offset=Math.floor((size-content)/2);gl.viewport(0,offset,size,content);gl.enable(gl.SCISSOR_TEST);gl.scissor(0,offset,size,content);gl.clearColor(24/255,28/255,24/255,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
        gl.uniform3fv(locations.C,projection.cameraPosition);for(let i=0;i<3;i++)gl.uniform3fv(locations['R'+i],projection.basis9.slice(i*3,i*3+3));for(const n of ['Cot','Aspect','Near','Far'])gl.uniform1f(locations[n],projection[n.toLowerCase()]);gl.uniform1i(locations.Texture,0);gl.activeTexture(gl.TEXTURE0);
        gl.uniform1i(locations.Unit,0);for(const mesh of world)draw(mesh,light);
        const propDraws=[];for(const {record,p,pose} of pendingProps){
          gl.uniform1i(locations.Unit,1);gl.uniform3fv(locations.Anchor,[0,0,0]);gl.uniform3fv(locations.Position,p.position);gl.uniform1f(locations.Scale,p.scale);gl.uniform1f(locations.Heading,0);
          for(const [n,m] of [['Root',p.root],['Owner',p.owner],['Parent',p.parent]])gl.uniformMatrix4fv(locations[n],false,new Float32Array(m));
          draw(propMesh(record,pose),light);propDraws.push({id:record.id,assetId:record.assetId,positionYup:[...p.position],scaleFactor:p.scale,transformScope:'engineering-bind-owner-v1',transformPolicy:'engine-prop-v1',ownerMatrix:[...p.owner],ownerPolicy:record.ownerPolicy??'packaged-engineering-owner',animationPhase:pose?record.animationPhase:null,animationScope:pose?'normal-flower-node-keys-v1':'raw-bind-only-unverified',attachmentPointYup:pose?transformPropVertex(pose.attachmentPointRaw,assets.props[record.assetId],record):null,submitted:true});
        }
        const draws=[];for(const {record,p,resolved} of pending){
          if(!resolved){draws.push({id:record.id,unit:record.unitId,culled:'missing-clip',clip:record.clip,frame:record.frame});continue;}
          gl.uniform1i(locations.Unit,1);gl.uniform3fv(locations.Anchor,p.anchor);gl.uniform3fv(locations.Position,p.position);gl.uniform1f(locations.Scale,p.scale);gl.uniform1f(locations.Heading,p.heading);for(const [n,m] of [['Root',p.root],['Owner',p.owner],['Parent',p.parent]])gl.uniformMatrix4fv(locations[n],false,new Float32Array(m));
          const gpu=frameMesh(record.unitId,resolved.clip,resolved.frame);draw(gpu,light);draws.push({id:record.id,unit:record.unitId,clip:resolved.clip,frame:resolved.frame,positionYup:[...p.position],headingRadians:p.heading,orientationPolicy:p.orientationPolicy,ownerMatrix:[...p.owner],directionYup:record.directionYup?[...record.directionYup]:null,scaleFactor:p.scale,posePolicy:'engine-pose-v1',sourceScope:'engineering',diffuseScope:runtimeUnits[record.unitId].diffuseScope??null,materialScopes:gpu.groups.map(g=>light&&g.state?.scope||'unobserved-neutral-quarter-plus-40'),submitted:true});
        }
        const spriteDraws=[];for(const item of pendingSprites){drawSprite(item);const r=item.record;
          spriteDraws.push({id:r.id,texture:r.texture,positionYup:[...r.positionYup],width:r.width,height:r.height,angleRadians:r.angleRadians,rgbaBytes:[...r.rgbaBytes],basisPolicy:r.basisPolicy,materialPolicy:r.materialPolicy,samplerPolicy:r.samplerPolicy,attachment:r.attachment?{...r.attachment}:null,placementPolicy:r.placementPolicy??null,pickupPositionScope:r.pickupPositionScope??null,carrierId:r.carrierId??null,pickupTick:r.pickupTick??null,submitted:true});}
        gl.finish();if(lost||gl.isContextLost()||gl.getError()!==gl.NO_ERROR)throw new Error('mesh GPU frame failure');return {canvas,draws,propDraws,spriteDraws,tick:snapshot.tick};
      }
      aborted();return {canvas,renderFrame,setProjection,dispose};
    } catch(error){dispose();throw error;}
  }
  return {transformVertex,transformNormal,transformPropVertex,transformPropNormal,spriteVertices,diffuseBytes,nectarCarryPosition,effectivePropRecord,samplePropPose:(prop,phase)=>flowerPose.samplePropPose(prop,phase),validateAssets,decodeUnitFrameBuffer,prepareMeshScene};
});
