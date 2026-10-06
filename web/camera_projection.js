// One DOM-free production matrix camera contract, shared with Node callers.
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) { module.exports = api; }
  else { root.BugBitsCameraProjection = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  function vector(value, length) {
    if (!Array.isArray(value) || value.length !== length
        || !value.every(x => typeof x === 'number' && Number.isFinite(x))) {
      throw new TypeError('finite numeric coordinates required');
    }
    return value;
  }
  function validateProjection(p) {
    if (!p || p.kind !== 'matrix-yup-v1') { throw new TypeError('matrix-yup-v1 required'); }
    const b = vector(p.basis9,9); vector(p.cameraPosition,3);
    for (const key of ['size','cot','aspect','near','far']) {
      if (typeof p[key] !== 'number' || !Number.isFinite(p[key]) || p[key] <= 0) {
        throw new TypeError('positive finite projection '+key+' required');
      }
    }
    if (!(p.near < p.far && Number.isFinite(p.size*p.aspect))) {
      throw new TypeError('invalid projection frustum');
    }
    for (let i=0;i<3;i++) for (let j=0;j<3;j++) {
      let dot=0; for (let k=0;k<3;k++) dot+=b[3*i+k]*b[3*j+k];
      if (Math.abs(dot-(i===j?1:0))>1e-6) { throw new TypeError('orthonormal basis required'); }
    }
    const det=b[0]*(b[4]*b[8]-b[5]*b[7])-b[1]*(b[3]*b[8]-b[5]*b[6])+b[2]*(b[3]*b[7]-b[4]*b[6]);
    if (Math.abs(det-1)>1e-6) { throw new TypeError('proper rotation required'); }
    return p;
  }
  function cameraSpace(p, point) {
    validateProjection(p); vector(point,3);
    const d = point.map((x,i) => x-p.cameraPosition[i]);
    return vector([0,1,2].map(i => p.basis9[i*3]*d[0]+p.basis9[i*3+1]*d[1]+p.basis9[i*3+2]*d[2]),3);
  }
  function projectWorldPoint(p, point) {
    const [x,y,z] = cameraSpace(p,point);
    if (z < p.near || z > p.far) { return null; }
    const px=(1+p.cot*x/(z*p.aspect))*p.size*p.aspect/2;
    const py=(1-p.cot*y/z)*p.size/2;
    return Number.isFinite(px)&&Number.isFinite(py) ? {px,py,camZ:z} : null;
  }
  function pixelToGround(p,px,py) {
    validateProjection(p); vector([px,py],2);
    const d=[(2*px/(p.size*p.aspect)-1)*p.aspect/p.cot,(1-2*py/p.size)/p.cot,1];
    const b=p.basis9;
    const ray=[0,1,2].map(j=>b[j]*d[0]+b[3+j]*d[1]+b[6+j]*d[2]);
    if (!ray.every(Number.isFinite)||Math.abs(ray[1])<=1e-12) { return null; }
    const s=-p.cameraPosition[1]/ray[1];
    if (!(s>=p.near && s<=p.far)) { return null; }
    const hit=[p.cameraPosition[0]+s*ray[0],p.cameraPosition[2]+s*ray[2]];
    return hit.every(Number.isFinite) ? hit : null;
  }
  return {validateProjection,cameraSpace,projectWorldPoint,pixelToGround};
});
