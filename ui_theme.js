/* SPDX-License-Identifier: GPL-3.0-or-later — Copyright (c) 2026 nordseele */
/* Browser chrome only. Pixel rendering and exported artwork keep their own palette. */
(()=>{
  const root=document.documentElement,button=document.getElementById('theme');
  let theme='light';try{theme=localStorage.getItem('ui-editor-theme')||theme}catch(e){}
  function apply(){root.dataset.theme=theme;if(button){button.textContent=theme==='light'?'Dark':'Light';button.setAttribute('aria-label',theme==='light'?'Switch to dark theme':'Switch to light theme')}}
  apply();if(button)button.onclick=()=>{theme=theme==='light'?'dark':'light';apply();try{localStorage.setItem('ui-editor-theme',theme)}catch(e){}};
  fetch('/brand').then(r=>r.json()).then(brand=>{
    const heading=document.getElementById('app-name');
    if(heading&&!heading.querySelector('svg')){heading.setAttribute('aria-label',brand.name);heading.innerHTML=brand.svg}
    for(const element of document.querySelectorAll('[data-brand]'))element.textContent=brand.name;
    document.title=brand.name+' · UI editor';
  }).catch(()=>{});
})();
