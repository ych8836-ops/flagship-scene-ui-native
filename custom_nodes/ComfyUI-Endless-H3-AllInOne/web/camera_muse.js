import * as THREE from './vendor/build/three.module.js';

// Purpose-built camera-preview figure: a single riggable group, no images or services.
export function createCameraMuse(){
    const root=new THREE.Group();root.name='Camera Muse';
    const material=(color,roughness=.65)=>new THREE.MeshStandardMaterial({color,roughness,flatShading:true});
    const skin=material('#e6b99e'),blue=material('#83bfda'),blueEdge=material('#639ebd'),ivory=material('#f2eddf'),sole=material('#ded8c8'),hair=material('#24303c',.42),hairHighlight=material('#303d49',.48),ink=material('#36414a'),gold=material('#c6a16a',.38);
    const mesh=(name,geometry,mat,position=[0,0,0],scale=[1,1,1])=>{const obj=new THREE.Mesh(geometry,mat);obj.name=name;obj.position.set(...position);obj.scale.set(...scale);obj.castShadow=true;obj.receiveShadow=true;root.add(obj);return obj;};
    const egg=(name,position,scale,mat,segments=12,rings=7)=>mesh(name,new THREE.SphereGeometry(1,segments,rings),mat,position,scale);
    const cylinder=(name,position,rt,rb,length,mat,n=10)=>mesh(name,new THREE.CylinderGeometry(rt,rb,length,n,1,false),mat,position);
    const link=(name,a,b,r1,r2,mat,n=10)=>{const mid=new THREE.Vector3(...a).add(new THREE.Vector3(...b)).multiplyScalar(.5),direction=new THREE.Vector3(...b).sub(new THREE.Vector3(...a));const o=cylinder(name,mid.toArray(),r2,r1,direction.length(),mat,n);o.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),direction.normalize());return o;};
    const profile=(name,rows,mat,n=16)=>{
        const verts=[],indices=[];
        for(const [y,rx,rz,z] of rows)for(let i=0;i<n;i++){const t=i/n*Math.PI*2;verts.push(rx*Math.cos(t),y,(z||0)+rz*Math.sin(t));}
        for(let j=0;j<rows.length-1;j++)for(let i=0;i<n;i++){const a=j*n+i,b=j*n+(i+1)%n,c=b+n,d=a+n;indices.push(a,d,b,b,d,c);}
        const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));g.setIndex(indices);g.computeVertexNormals();return mesh(name,g,mat);
    };
    const patch=(name,points,mat)=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(points.flat(),3));g.setIndex([0,1,2,0,2,3]);g.computeVertexNormals();const m=mat.clone();m.side=THREE.DoubleSide;return mesh(name,g,m);};

    // Long clean leg lines, compact platform shoes, and subtle sock cuffs.
    for(const side of [-1,1]){
        const x=side*.105;
        link('Leg upper',[x,.81,0],[side*.115,.47,.015],.078,.061,skin);
        link('Leg lower',[side*.115,.47,.015],[side*.115,.13,.025],.061,.038,skin);
        egg('Knee',[side*.115,.47,.015],[.061,.065,.057],skin,10,5);
        cylinder('Sock',[side*.115,.13,.025],.043,.044,.15,ivory);
        cylinder('Sock cuff',[side*.115,.205,.025],.046,.046,.025,sole);
        mesh('Platform sole',new THREE.BoxGeometry(.105,.032,.19),sole,[side*.115,.025,.07]);
        egg('White shoe',[side*.115,.055,.07],[.054,.044,.1],ivory,10,5);
    }
    profile('Ivory skirt',[[.71,.205,.13],[.75,.218,.14],[.87,.226,.15],[.98,.171,.117]],ivory,16);
    profile('Waistband',[[.965,.173,.12],[1.005,.166,.115]],ivory,16);
    profile('Waist',[[.99,.158,.107],[1.10,.165,.11]],skin,16);
    profile('Blue blouse',[[1.055,.169,.12],[1.09,.183,.13],[1.22,.225,.16],[1.35,.229,.13],[1.405,.15,.10]],blue,16);
    cylinder('Neck',[0,1.44,0],.058,.066,.13,skin,12);
    // Collar shapes, button line and short gathered sleeves make the outfit readable.
    patch('Collar left',[[-.115,1.395,.10],[-.025,1.31,.165],[-.012,1.425,.066],[-.058,1.44,.044]],blueEdge);
    patch('Collar right',[[.115,1.395,.10],[.058,1.44,.044],[.012,1.425,.066],[.025,1.31,.165]],blueEdge);
    for(const y of [1.10,1.17,1.24,1.31])egg('Button',[0,y,.156],[.007,.007,.004],ivory,8,4);
    for(const side of [-1,1]){
        egg('Puff sleeve',[side*.235,1.315,0],[.102,.118,.105],blue,10,6);
        link('Upper arm',[side*.263,1.255,.005],[side*.302,1.06,.015],.047,.042,skin);
        egg('Elbow',[side*.302,1.06,.015],[.044,.047,.045],skin,10,5);
        link('Lower arm',[side*.302,1.06,.015],[side*.282,.9,.04],.041,.032,skin);
        egg('Hand',[side*.28,.865,.04],[.035,.062,.025],skin,10,5);
    }

    // An intentionally minimal sculpt avoids uncanny facial detail at tooltip size.
    egg('Face',[0,1.65,.015],[.159,.185,.145],skin,14,9);
    egg('Hair crown',[0,1.755,-.025],[.176,.135,.157],hair,14,7);
    egg('Back hair',[0,1.48,-.13],[.17,.34,.079],hair,12,8);
    const curl=(side,phase,z,mat)=>{
        const points=[];for(let i=0;i<9;i++){const t=i/8;points.push(new THREE.Vector3(side*(.13+.045*Math.sin(t*Math.PI)+.022*Math.sin(t*10+phase)),1.78-.66*t,z+.025*Math.sin(t*9+phase)));}
        const curve=new THREE.CatmullRomCurve3(points);return mesh('Wavy hair lock',new THREE.TubeGeometry(curve,16,.036,5,false),mat);
    };
    for(const side of [-1,1]){curl(side,0,-.09,hair);curl(side,1.7,-.045,hairHighlight);curl(side,2.5,.005,hair);}
    curl(-1,.6,.10,hair);
    const bang=egg('Swept fringe',[-.045,1.755,.105],[.125,.055,.05],hair,12,5);bang.rotation.z=.26;
    const bang2=egg('Side fringe',[.125,1.69,.045],[.042,.115,.065],hair,10,6);bang2.rotation.z=.16;
    // Closed, gently curved lashes read as a calm friendly expression.
    for(const side of [-1,1]){
        const points=[new THREE.Vector3(side*.035,1.665,.153),new THREE.Vector3(side*.058,1.657,.153),new THREE.Vector3(side*.08,1.664,.14)];
        mesh('Soft eyelash',new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),6,.0024,4,false),ink);
        egg('Earring',[side*.158,1.57,.01],[.011,.016,.009],gold,8,5);
    }
    // A restrained smile, without protruding facial primitives.
    mesh('Smile',new THREE.TubeGeometry(new THREE.CatmullRomCurve3([new THREE.Vector3(-.023,1.584,.145),new THREE.Vector3(0,1.579,.15),new THREE.Vector3(.023,1.584,.145)]),8,.0017,4,false),material('#a46d60'));
    return root;
}
