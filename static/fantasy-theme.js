(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const body = document.body;
  if (!body) return;

  const isLogin = Boolean(document.querySelector('form.box#f')) || location.pathname.includes('login');
  body.classList.add(isLogin ? 'login-page' : 'dashboard-page');

  const fx = document.createElement('div');
  fx.className = 'coc-fx';
  fx.setAttribute('aria-hidden', 'true');
  fx.innerHTML = `
    <div class="fx-stars"></div>
    <img class="coc-character blue" src="/static/assets/branding/soul-weaver.webp" alt="">
    <img class="coc-character purple" src="/static/assets/branding/void-archmage.webp" alt="">
  `;
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
        document.documentElement.style.setProperty('--mx', `${x}px`);
        document.documentElement.style.setProperty('--my', `${y}px`);
        const nx = (x / Math.max(innerWidth, 1) - .5);
        const ny = (y / Math.max(innerHeight, 1) - .5);
        document.documentElement.style.setProperty('--blue-x', `${nx * 16}px`);
        document.documentElement.style.setProperty('--blue-y', `${ny * 9}px`);
        document.documentElement.style.setProperty('--purple-x', `${nx * -17}px`);
        document.documentElement.style.setProperty('--purple-y', `${ny * -10}px`);
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
