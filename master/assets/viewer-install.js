'use strict';
(() => {
  const button = document.getElementById('installApp');
  const help = document.getElementById('quickstart');
  let offer = null;
  const standalone = window.matchMedia('(display-mode: standalone)');
  const update = () => { button.hidden = standalone.matches || navigator.standalone === true; };
  update();
  standalone.addEventListener?.('change', update);
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); offer = event;
    button.textContent = 'Установить FIT-LAB';
  });
  window.addEventListener('appinstalled', () => { offer = null; button.hidden = true; });
  button.onclick = async () => {
    if (offer) {
      const pending = offer; offer = null;
      try { await pending.prompt(); await pending.userChoice; } catch (_) {}
    } else {
      help.open = true;
      help.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'});
    }
  };
})();
