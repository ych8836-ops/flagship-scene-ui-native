// A small, self-contained virtual set. Interleaved position / normal / color / material.
const palette={floor:[.73,.72,.68],wall:[.68,.68,.63],stone:[.83,.80,.73],ivory:[.87,.83,.73],skin:[.73,.52,.37],hair:[.12,.09,.075],cloth:[.69,.75,.68],pants:[.15,.19,.18],brass:[.61,.43,.23],mint:[.31,.58,.46],dark:[.105,.14,.13],leaf:[.23,.39,.27]};
export function buildCameraStage(){
    const groups={set:[],actor:[],vehicle:[],gate:[]};let out=groups.set;
    const vertex=(p,n,c,m)=>out.push(...p,...n,...c,m);
    const tri=(a,b,c,color,material=0)=>{const u=b.map((v,i)=>v-a[i]),v=c.map((x,i)=>x-a[i]),n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],l=Math.hypot(...n)||1;n.forEach((v,i)=>n[i]=v/l);for(const p of [a,b,c])vertex(p,n,color,material);};
    const quad=(a,b,c,d,color,material=0)=>{tri(a,b,c,color,material);tri(a,c,d,color,material);};
    const box=(x,y,z,w,h,d,color,material=0)=>{
        const a=[x-w/2,y,z-d/2],b=[x+w/2,y,z-d/2],c=[x+w/2,y,z+d/2],e=[x-w/2,y,z+d/2],top=p=>[p[0],p[1]+h,p[2]];
        quad(a,e,c,b,color,material);quad(top(a),top(b),top(c),top(e),color,material);
        for(const [p,q] of [[a,b],[b,c],[c,e],[e,a]])quad(p,q,top(q),top(p),color,material);
    };
    const ellipsoid=(cx,cy,cz,rx,ry,rz,color,material=0,segments=20,rings=12,thetaMax=Math.PI)=>{
        const at=(t,p)=>({p:[cx+rx*Math.sin(t)*Math.cos(p),cy+ry*Math.cos(t),cz+rz*Math.sin(t)*Math.sin(p)],n:[Math.sin(t)*Math.cos(p)/rx,Math.cos(t)/ry,Math.sin(t)*Math.sin(p)/rz]});
        const emit=a=>{const n=Math.hypot(...a.n);vertex(a.p,a.n.map(v=>v/n),color,material);};
        for(let j=0;j<rings;j++)for(let i=0;i<segments;i++){
            const a=at(j/rings*thetaMax,i/segments*Math.PI*2),b=at((j+1)/rings*thetaMax,i/segments*Math.PI*2),c=at((j+1)/rings*thetaMax,(i+1)/segments*Math.PI*2),d=at(j/rings*thetaMax,(i+1)/segments*Math.PI*2);
            for(const v of [a,b,c,a,c,d])emit(v);
        }
    };
    const cylinder=(x,y,z,rt,rb,height,color,material=0,n=32)=>{
        for(let i=0;i<n;i++){
            const a=i/n*Math.PI*2,b=(i+1)/n*Math.PI*2;
            const p=[x+rb*Math.cos(a),y,z+rb*Math.sin(a)],q=[x+rb*Math.cos(b),y,z+rb*Math.sin(b)],r=[x+rt*Math.cos(b),y+height,z+rt*Math.sin(b)],s=[x+rt*Math.cos(a),y+height,z+rt*Math.sin(a)];
            const normal=t=>{const v=[Math.cos(t),(rb-rt)/height,Math.sin(t)],len=Math.hypot(...v);return v.map(x=>x/len);};
            for(const [v,t] of [[p,a],[q,b],[r,b],[p,a],[r,b],[s,a]])vertex(v,normal(t),color,material);
            tri([x,y+height,z],s,r,color,material);tri([x,y,z],q,p,color,material);
        }
    };
    const arch=(x,z,r,y,width,color)=>{
        for(let i=0;i<48;i++){
            const a=i/48*Math.PI,b=(i+1)/48*Math.PI,p=(t,rad,zz)=>[x+Math.cos(t)*rad,y+Math.sin(t)*rad,zz];
            quad(p(a,r,z),p(b,r,z),p(b,r+width,z),p(a,r+width,z),color);
            quad(p(a,r+width,z),p(b,r+width,z),p(b,r+width,z-.14),p(a,r+width,z-.14),color);
        }
        box(x-r-width/2,0,z-.07,width,y,.14,color);box(x+r+width/2,0,z-.07,width,y,.14,color);
    };
    const leaf=(x,y,z,rx,ry,rz,color)=>ellipsoid(x,y,z,rx,ry,rz,color,0,12,8);
    // Warm gallery with a recessed arch, distant architecture and a low circular stage.
    box(0,-.2,-2,30,.05,30,palette.floor,1);
    box(0,-.15,-6.3,16,7,.22,palette.wall);
    box(0,0,-6.15,3.15,2.4,.1,palette.dark);
    ellipsoid(0,2.4,-6.08,1.57,1.57,.06,palette.dark,0,36,16,Math.PI/2);
    arch(0,-5.95,1.6,2.4,.11,palette.stone);
    for(const side of [-1,1]){
        box(side*3.5,0,-5.8,.8,4.6,.55,[.39,.32,.26]);
        for(let i=0;i<5;i++)box(side*(2.7+i*.15),.35,-6,.018,3.7,.05,palette.brass,2);
        cylinder(side*2.4,0,-3.8,.035,.04,2.8,palette.brass,2);
        ellipsoid(side*2.4,2.8,-3.8,.23,.23,.23,palette.ivory,3);
    }
    cylinder(0,-.15,0,1.05,1.13,.14,palette.stone);
    cylinder(0,-.16,0,1.14,1.15,.035,palette.brass,2);
    // Foreground lamp, foliage and a walnut table give real depth/parallax cues.
    cylinder(-1.8,-.14,2.5,.29,.31,.065,palette.dark,2);
    cylinder(-1.8,-.08,2.5,.025,.025,2.7,palette.brass,2);
    cylinder(-1.8,2.5,2.5,.22,.39,.36,palette.ivory);
    cylinder(-1.8,2.52,2.5,.2,.2,.02,palette.ivory,3);
    cylinder(-2,-.15,.65,.3,.23,.48,[.49,.30,.22]);
    for(let i=0;i<9;i++){const a=i*2.399,r=.16+(i%3)*.09,y=.6+(i%4)*.18;leaf(-2+Math.cos(a)*r,y,.65+Math.sin(a)*r,.13,.28,.07,i%2?palette.leaf:palette.mint);}
    cylinder(1.15,-.15,.4,.14,.24,.82,palette.dark);
    cylinder(1.15,.66,.4,.46,.46,.075,[.37,.20,.12],1);
    cylinder(1.15,.73,.4,.12,.1,.28,palette.mint);
    ellipsoid(1.15,.98,.4,.12,.06,.12,palette.mint);
    cylinder(1.15,1,.4,.055,.055,.07,palette.mint);
    box(1.36,.74,.37,.15,.025,.24,palette.ivory);
    box(2.7,.05,-2.8,1.7,.22,.65,palette.stone);
    for(const x of [2.1,3.3])cylinder(x,-.15,-2.8,.035,.035,.2,palette.brass,2);
    // The car is shown only for car-rig controls.
    out=groups.vehicle;
    ellipsoid(0,.43,0,.85,.29,1.65,[.22,.38,.34],2,32,14);
    ellipsoid(0,.68,-.12,.67,.39,.85,[.13,.21,.20],2,28,16);
    for(const x of [-.73,.73])for(const z of [-1,1])ellipsoid(x,.21,z,.16,.22,.22,palette.dark,0,16,12);
    for(const x of [-.53,.53])ellipsoid(x,.43,1.49,.19,.045,.04,palette.ivory,3,16,8);
    // A genuine opening for the through-object controls.
    out=groups.gate;arch(0,4,1.5,1.6,.22,palette.stone);
    return Object.fromEntries(Object.entries(groups).map(([key,value])=>[key,new Float32Array(value)]));
}
