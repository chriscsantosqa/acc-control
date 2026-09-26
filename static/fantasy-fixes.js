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

  async function authMode() {
    try {
      const response = await fetch('/api/status', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) return {enabled: true};
      const payload = await response.json();
      return payload?.auth || {enabled: true};
    } catch (_) {
      return {enabled: true};
    }
  }

  /* In authenticated mode logout lands on /login. In intentionally-open local
     mode the backend auto-identifies the owner, so /login redirects back to /.
     For that case we intentionally display the static local-mode login screen. */
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
      const mode = await authMode();
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

      if (mode.enabled === false) {
        location.replace('/static/login.html?local=1&logout=1');
      } else {
        location.replace('/login?logout=1');
      }
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
