(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const body = document.body;
  if (!body) return;

  const isLogin = Boolean(document.querySelector('form.box#f')) || location.pathname.includes('login');
  body.classList.add(isLogin ? 'login-page' : 'dashboard-page');

  /* Cache-safe critical faceoff styles. The complete visual rules still live in
     faceoff-theme.css, but these rules guarantee that the two characters are
     visible and never block interaction even if an older stylesheet is cached. */
  if (!document.getElementById('faceoff-critical')) {
    const critical = document.createElement('style');
    critical.id = 'faceoff-critical';
    critical.textContent = `
      .faceoff-scene{position:fixed;inset:0;z-index:1;overflow:hidden;pointer-events:none!important;user-select:none}
      .faceoff-scene *{pointer-events:none!important}
      .faceoff-character{position:absolute;top:64px;z-index:1;width:clamp(340px,34vw,650px);height:calc(100vh - 64px);opacity:.42;display:flex;align-items:flex-start;justify-content:center;filter:drop-shadow(0 24px 55px rgba(0,0,0,.48));will-change:transform}
      .faceoff-character img{display:block;width:100%;height:100%;object-fit:contain;object-position:center top}
      .faceoff-platform .faceoff-left{left:clamp(255px,17vw,330px);transform:translate3d(var(--faceoff-left-x,0),var(--faceoff-left-y,0),0)}
      .faceoff-platform .faceoff-right{right:-2vw;transform:translate3d(var(--faceoff-right-x,0),var(--faceoff-right-y,0),0) scaleX(-1)}
      .faceoff-login .faceoff-character{top:66px;width:clamp(420px,38vw,720px);height:calc(100vh - 66px);opacity:.66}
      .faceoff-login .faceoff-left{left:-3vw;transform:translate3d(var(--faceoff-left-x,0),var(--faceoff-left-y,0),0)}
      .faceoff-login .faceoff-right{right:-3vw;transform:translate3d(var(--faceoff-right-x,0),var(--faceoff-right-y,0),0) scaleX(-1)}
      .shell{position:relative;z-index:4}.login-page .box{position:relative;z-index:4}
      .modal-bg{position:fixed!important;inset:0!important;z-index:1000!important}.modal-bg.open{display:flex!important}.modal{position:relative;z-index:1001}
      @media(max-width:780px){.faceoff-scene{display:none}}
    `;
    document.head.appendChild(critical);
  }

  /* Load the full faceoff stylesheet with a new cache key. */
  let faceoffCss = document.querySelector('link[data-faceoff-theme]');
  if (!faceoffCss) {
    faceoffCss = document.createElement('link');
    faceoffCss.rel = 'stylesheet';
    faceoffCss.dataset.faceoffTheme = '1';
    document.head.appendChild(faceoffCss);
  }
  faceoffCss.href = '/static/faceoff-theme.css?v=20260926-5';

  /* Characters are a global background layer, never an interactive overlay. */
  let faceoff = document.querySelector('.faceoff-scene');
  if (!faceoff) {
    faceoff = document.createElement('div');
    faceoff.className = `faceoff-scene ${isLogin ? 'faceoff-login' : 'faceoff-platform'}`;
    faceoff.setAttribute('aria-hidden', 'true');

    const left = document.createElement('div');
    left.className = 'faceoff-character faceoff-left';
    const leftImg = document.createElement('img');
    leftImg.alt = '';
    leftImg.decoding = 'async';
    leftImg.src = '/static/assets/branding/soul-weaver.webp?v=20260926-5';
    left.appendChild(leftImg);

    const right = document.createElement('div');
    right.className = 'faceoff-character faceoff-right';
    const rightImg = document.createElement('img');
    rightImg.alt = '';
    rightImg.decoding = 'async';
    rightImg.src = '/static/assets/branding/void-archmage.webp?v=20260926-5';
    right.appendChild(rightImg);

    faceoff.append(left, right);
    body.prepend(faceoff);

    leftImg.addEventListener('error', () => console.error('Falha ao carregar soul-weaver.webp'));
    rightImg.addEventListener('error', () => console.error('Falha ao carregar void-archmage.webp'));
  }

  /* Ambient FX remain separate from the character scene. */
  const fx = document.createElement('div');
  fx.className = 'coc-fx';
  fx.setAttribute('aria-hidden', 'true');
  fx.innerHTML = '<div class="fx-stars"></div>';
  body.prepend(fx);

  const progress = document.createElement('div');
  progress.className = 'scroll-progress';
  progress.setAttribute('aria-hidden', 'true');
  body.appendChild(progress);

  function updateScroll() {
    const root = document.documentElement;
    const max = Math.max(1, root.scrollHeight - root.clientHeight);
    root.style.setProperty('--scroll', `${Math.min(100, (root.scrollTop / max) * 100)}%`);
  }
  updateScroll();
  addEventListener('scroll', updateScroll, {passive: true});
  addEventListener('resize', updateScroll, {passive: true});

  if (!reduceMotion) {
    let raf = 0;
    addEventListener('pointermove', event => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const x = event.clientX;
        const y = event.clientY;
        const nx = x / Math.max(innerWidth, 1) - .5;
        const ny = y / Math.max(innerHeight, 1) - .5;

        document.documentElement.style.setProperty('--mx', `${x}px`);
        document.documentElement.style.setProperty('--my', `${y}px`);
        document.documentElement.style.setProperty('--faceoff-left-x', `${nx * -12}px`);
        document.documentElement.style.setProperty('--faceoff-left-y', `${ny * -8}px`);
        document.documentElement.style.setProperty('--faceoff-right-x', `${nx * 12}px`);
        document.documentElement.style.setProperty('--faceoff-right-y', `${ny * -8}px`);
      });
    }, {passive: true});
  }

  const selector = '.hero,.section,.card,.resource,.item,.planner-help';
  let observer = null;
  if ('IntersectionObserver' in window && !reduceMotion) {
    observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('fx-in');
        observer.unobserve(entry.target);
      });
    }, {threshold: .08, rootMargin: '0px 0px -24px 0px'});
  }

  function enhance(root = document) {
    root.querySelectorAll?.(selector).forEach(node => {
      if (node.dataset.fxReady) return;
      node.dataset.fxReady = '1';
      if (observer) {
        node.classList.add('fx-reveal');
        observer.observe(node);
      } else {
        node.classList.add('fx-in');
      }
    });
  }

  enhance();
  const mutation = new MutationObserver(records => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType === 1) enhance(node);
      }
    }
  });
  mutation.observe(body, {childList: true, subtree: true});

  document.addEventListener('click', event => {
    const target = event.target.closest('.btn,.tab,.village');
    if (!target || reduceMotion) return;
    const rect = target.getBoundingClientRect();
    const pulse = document.createElement('span');
    pulse.setAttribute('aria-hidden', 'true');
    Object.assign(pulse.style, {
      position: 'absolute', left: `${event.clientX - rect.left}px`, top: `${event.clientY - rect.top}px`,
      width: '6px', height: '6px', borderRadius: '999px', pointerEvents: 'none', zIndex: '5',
      background: 'rgba(160,231,255,.42)', transform: 'translate(-50%,-50%) scale(1)',
      transition: 'transform .55s ease,opacity .55s ease', opacity: '1'
    });
    if (getComputedStyle(target).position === 'static') target.style.position = 'relative';
    target.appendChild(pulse);
    requestAnimationFrame(() => {
      pulse.style.transform = 'translate(-50%,-50%) scale(22)';
      pulse.style.opacity = '0';
    });
    setTimeout(() => pulse.remove(), 600);
  });
})();
