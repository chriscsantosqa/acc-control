(() => {
  const cookie = name => document.cookie
    .split('; ')
    .find(value => value.startsWith(`${name}=`))
    ?.split('=')
    .slice(1)
    .join('=') || '';

  /* Safety net: decorative layers must never become click targets, even if
     another stylesheet later changes pointer-events. */
  const lockDecorativeLayers = () => {
    document.querySelectorAll('.coc-fx, .coc-fx *, .scroll-progress').forEach(node => {
      node.style.pointerEvents = 'none';
      node.setAttribute('aria-hidden', 'true');
    });
  };

  lockDecorativeLayers();
  new MutationObserver(lockDecorativeLayers).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });

  /* Logout must not depend on the generic API renderer. Keep the current
     screen intact until the server confirms that the session was cleared. */
  window.logout = async function logout() {
    const token = cookie('csrf');
    const headers = token ? {'X-CSRF': token} : {};
    const button = [...document.querySelectorAll('button')]
      .find(node => node.textContent.trim().toLowerCase() === 'sair');

    if (button) {
      button.disabled = true;
      button.dataset.originalText ||= button.textContent;
      button.textContent = 'Saindo…';
    }

    try {
      const response = await fetch('/api/logout', {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        cache: 'no-store',
      });

      if (!response.ok) {
        let detail = `Erro ${response.status}`;
        try {
          const payload = await response.json();
          detail = payload.error || detail;
        } catch (_) {}
        throw new Error(detail);
      }

      location.replace('/login?logout=1');
    } catch (error) {
      console.error('Falha ao encerrar sessão:', error);
      alert(`Não foi possível sair: ${error.message}. Recarregue a página e tente novamente.`);
      if (button) {
        button.disabled = false;
        button.textContent = button.dataset.originalText || 'Sair';
      }
    }
  };
})();
