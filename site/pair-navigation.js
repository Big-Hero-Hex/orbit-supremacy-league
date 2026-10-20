/** Horizontal match navigation: explicit arrows, desktop wheel/drag, native touch. */
export function setupPairNavigation(scroller,previous,next){
 let drag=null,suppressClick=false;
 function refresh(){const max=scroller.scrollWidth-scroller.clientWidth;previous.disabled=scroller.scrollLeft<=1;next.disabled=max<=1||scroller.scrollLeft>=max-1;}
 function step(direction){scroller.scrollBy({left:direction*Math.max(220,scroller.clientWidth*.7),behavior:'smooth'});}
 previous.addEventListener('click',()=>step(-1));next.addEventListener('click',()=>step(1));
 scroller.addEventListener('scroll',refresh,{passive:true});
 scroller.addEventListener('wheel',event=>{
  if(Math.abs(event.deltaX)>=Math.abs(event.deltaY))return;
  const before=scroller.scrollLeft,scale=event.deltaMode===1?16:event.deltaMode===2?scroller.clientWidth:1;
  scroller.scrollLeft+=event.deltaY*scale;
  if(scroller.scrollLeft!==before)event.preventDefault();
 },{passive:false});
 scroller.addEventListener('pointerdown',event=>{
  if(event.pointerType!=='mouse'||event.button!==0)return;
  if(event.clientY>=scroller.getBoundingClientRect().top+scroller.clientHeight)return;
  suppressClick=false;drag={id:event.pointerId,x:event.clientX,left:scroller.scrollLeft,moved:false};
 });
 window.addEventListener('pointermove',event=>{
  if(!drag||event.pointerId!==drag.id)return;
  const delta=event.clientX-drag.x;
  if(!drag.moved&&Math.abs(delta)>6){drag.moved=true;scroller.setPointerCapture(event.pointerId);scroller.classList.add('is-dragging');}
  if(drag.moved){event.preventDefault();scroller.scrollLeft=drag.left-delta;}
 });
 function finish(event){if(!drag||event.pointerId!==drag.id)return;suppressClick=drag.moved;drag=null;scroller.classList.remove('is-dragging');}
 window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',finish);
 scroller.addEventListener('click',event=>{if(suppressClick&&event.detail>0){event.preventDefault();event.stopImmediatePropagation();suppressClick=false;}},true);
 scroller.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();if(event.key==='Home')scroller.scrollTo({left:0,behavior:'smooth'});else if(event.key==='End')scroller.scrollTo({left:scroller.scrollWidth,behavior:'smooth'});else step(event.key==='ArrowLeft'?-1:1);}});
 new ResizeObserver(refresh).observe(scroller);refresh();
 function reveal(element){if(!element)return;const box=scroller.getBoundingClientRect(),tab=element.getBoundingClientRect();if(tab.left<box.left)scroller.scrollBy({left:tab.left-box.left,behavior:'smooth'});else if(tab.right>box.right)scroller.scrollBy({left:tab.right-box.right,behavior:'smooth'});}
 return {refresh:()=>requestAnimationFrame(refresh),reveal};
}
