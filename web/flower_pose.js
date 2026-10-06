/* Finite normal-flower pose kernel. No frame clock or x87/complete-skin claim. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BugBitsFlowerPose=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 function require(ok,message){if(!ok)throw new TypeError(message);}
 function vector(x,n){require(Array.isArray(x)&&x.length===n&&Array.from(x).every(finite),'finite vector required');return x;}
 function affine(x){vector(x,16);require(x[3]===0&&x[7]===0&&x[11]===0&&x[15]===1,'affine matrix required');}
 function equal(a,b){if(a===b)return true;if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;const ak=Object.keys(a),bk=Object.keys(b);return ak.length===bk.length&&ak.every(k=>Object.prototype.hasOwnProperty.call(b,k)&&equal(a[k],b[k]));}
 function validateProp(p){
  require(p&&p.animationScope==='normal-flower-node-keys-v1','unsupported animation scope');
  const r=p.animationRig;require(r&&r.contract==='flower-node-keys-v1','unsupported rig');
  for(const k of ['assetId','modelSource','animationSource'])require(typeof r[k]==='string'&&r[k].length>0,'source metadata required');
  for(const k of ['modelSHA','animationSHA','rigSHA256'])require(typeof r[k]==='string'&&/^[0-9a-f]{64}$/.test(r[k]),'SHA metadata required');
  require(finite(r.duration)&&r.duration>0,'positive duration required');
  require(Array.isArray(r.nodes)&&r.nodes.length>0,'nodes required');
  const names=new Set();
  for(const n of r.nodes){
   require(n&&typeof n.name==='string'&&n.name.length&&!names.has(n.name),'unique names required');names.add(n.name);
   require(Number.isInteger(n.parent)&&n.parent>=-1&&n.parent<r.nodes.length,'parent index required');affine(n.bind);
   require(Array.isArray(n.keys)&&n.keys.length>0,'keys required');let prev=-1;
   for(const key of n.keys){vector(key,7);require(key[0]>prev,'strict key times required');prev=key[0];}
   require(n.keys[0][0]===0&&prev===r.duration,'key duration mismatch');
  }
  for(let i=0;i<r.nodes.length;i++){const seen=new Set();let j=i;while(j!==-1){require(!seen.has(j),'cyclic hierarchy');seen.add(j);j=r.nodes[j].parent;}}
  require(Number.isInteger(r.nektarNode)&&r.nektarNode>=0&&r.nektarNode<r.nodes.length&&r.nodes[r.nektarNode].name==='nektar','nektar node mismatch');
  require(typeof p.animationRigJson==='string','source JSON required');let decoded;try{decoded=JSON.parse(p.animationRigJson);}catch(e){throw new TypeError('invalid rig JSON');}
  const unsigned={...r};delete unsigned.rigSHA256;require(equal(decoded,unsigned),'rig JSON value mismatch');
  // Synchronous validation checks content equality only; caller verifies SHA-256.
  require(Array.isArray(p.positions)&&Array.isArray(p.normals)&&p.positions.length>0&&p.positions.length%3===0&&p.normals.length===p.positions.length,'geometry shape mismatch');
  vector(p.positions,p.positions.length);vector(p.normals,p.normals.length);
  require(Array.isArray(p.animationSkin)&&p.animationSkin.length*3===p.positions.length,'skin count mismatch');
  for(let i=0;i<p.animationSkin.length;i++){
   const s=p.animationSkin[i];require(Array.isArray(s)&&s.length===3,'skin record required');vector(s[0],3);vector(s[1],3);
   for(let j=0;j<3;j++)require(s[0][j]===p.positions[i*3+j]&&s[1][j]===p.normals[i*3+j],'same-index source mismatch');
   require(Array.isArray(s[2])&&s[2].length>0,'skin influences required');let sum=0;
   for(const inf of s[2]){vector(inf,2);require(Number.isInteger(inf[0])&&inf[0]>=-1&&inf[0]<r.nodes.length&&inf[1]>0&&inf[1]<=1,'invalid influence');sum+=inf[1];}
   require(Math.abs(sum-1)<1e-5,'weights must sum to one');
  }
  return p;
 }
 function mul(a,b){return Array.from({length:16},(_,i)=>{let s=0;for(let k=0;k<4;k++)s+=a[Math.floor(i/4)*4+k]*b[k*4+i%4];return s;});}
 function inverse(m){const [a,b,c,d,e,f,g,h,i]=[0,1,2,4,5,6,8,9,10].map(j=>m[j]);const det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g);require(finite(det)&&det!==0,'singular bind world');const r=[e*i-f*h,c*h-b*i,b*f-c*e,f*g-d*i,a*i-c*g,c*d-a*f,d*h-e*g,b*g-a*h,a*e-b*d].map(x=>x/det);const t=[0,1,2].map(j=>-[0,1,2].reduce((s,k)=>s+m[12+k]*r[k*3+j],0));return [r[0],r[1],r[2],0,r[3],r[4],r[5],0,r[6],r[7],r[8],0,...t,1];}
 function hierarchy(nodes,locals){const ws=new Array(nodes.length);function resolve(i){if(!ws[i])ws[i]=nodes[i].parent===-1?locals[i].slice():mul(locals[i],resolve(nodes[i].parent));return ws[i];}for(let i=0;i<nodes.length;i++)resolve(i);return ws;}
 function keyAt(keys,t){if(t<=keys[0][0])return keys[0];if(t>=keys[keys.length-1][0])return keys[keys.length-1];for(let i=0;i<keys.length-1;i++)if(t<=keys[i+1][0]){const a=keys[i],b=keys[i+1],f=(t-a[0])/(b[0]-a[0]);return a.map((v,j)=>v+(b[j]-v)*f);}throw new Error('key interval missing');}
 function local(k){const [rx,ry,rz]=k.slice(1,4),cx=Math.cos(rx),sx=Math.sin(rx),cy=Math.cos(ry),sy=Math.sin(ry),cz=Math.cos(rz),sz=Math.sin(rz);return [cz*cy,sz*cy,-sy,0,cz*sy*sx-sz*cx,sz*sy*sx+cz*cx,cy*sx,0,cz*sy*cx+sz*sx,sz*sy*cx-cz*sx,cy*cx,0,k[4],k[5],k[6],1];}
 function apply(m,v,w){return [0,1,2].map(j=>v[0]*m[j]+v[1]*m[4+j]+v[2]*m[8+j]+w*m[12+j]);}
 function createSampler(prop){
  validateProp(prop);const p=JSON.parse(JSON.stringify(prop)),r=p.animationRig,nodes=r.nodes;
  const inv=hierarchy(nodes,nodes.map(n=>n.bind)).map(inverse);
  return Object.freeze({sample(phase){
   require(finite(phase)&&phase>=0,'finite nonnegative phase required');
   const ws=hierarchy(nodes,nodes.map(n=>local(keyAt(n.keys,phase)))),transforms=ws.map((m,i)=>mul(inv[i],m));
   require(ws.every(m=>m.every(finite))&&transforms.every(m=>m.every(finite)),'nonfinite node pose');
   const positions=[],normals=[];
   for(const [position,normal,influences] of p.animationSkin){const pos=[0,0,0],nor=[0,0,0];let total=0;for(const [bone,weight] of influences){total+=weight;const a=bone===-1?position:apply(transforms[bone],position,1),b=bone===-1?normal:apply(transforms[bone],normal,0);for(let j=0;j<3;j++){pos[j]+=a[j]*weight;nor[j]+=b[j]*weight;}}
    const point=total?pos.map(v=>v/total):position.slice();
    const length=Math.hypot(...nor);require(point.every(finite)&&nor.every(finite)&&finite(length),'nonfinite pose');positions.push(...point);normals.push(...(length?nor.map(v=>v/length):nor));}
   return {positions,normals,attachmentPointRaw:ws[r.nektarNode].slice(12,15)};
  }});
 }
 function samplePropPose(prop,phase){return createSampler(prop).sample(phase);}
 return {validateProp,createSampler,samplePropPose};
});
