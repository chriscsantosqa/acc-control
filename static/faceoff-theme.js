(() => {
  const scene = document.querySelector('.faceoff-scene');
  if (!scene || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let raf = 0;
  let targetX = 0;
  let targetY = 0;

  const render = () => {
    raf = 0;
    scene.style.setProperty('--faceoff-left-x', `${targetX * -12}px`);
    scene.style.setProperty('--faceoff-left-y', `${targetY * -8}px`);
    scene.style.setProperty('--faceoff-right-x', `${targetX * 12}px`);
    scene.style.setProperty('--faceoff-right-y', `${targetY * -8}px`);
  };

  window.addEventListener('pointermove', event => {
    targetX = event.clientX / Math.max(window.innerWidth, 1) - 0.5;
    targetY = event.clientY / Math.max(window.innerHeight, 1) - 0.5;
    if (!raf) raf = requestAnimationFrame(render);
  }, { passive: true });
})();
