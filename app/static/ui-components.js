/* Abre/fecha os componentes <dialog class="modal"|"drawer"> definidos em
 * app/templates/_crm_ui.html (Fase 2 da reforma do CRM, 2026-08-06).
 *
 * Delegação de evento no document inteiro (em vez de bind por elemento)
 * pra funcionar também em conteúdo que aparece depois do load inicial
 * (ex.: cards de kanban renderizados por template loop) sem precisar
 * rechamar nenhum init -- mesmo raciocínio de app/static/notifications.js.
 *
 * <dialog> nativo já cuida de foco, Esc-pra-fechar e da <backdrop>; este
 * arquivo só faz showModal()/close() e fecha ao clicar fora do conteúdo.
 */
(function () {
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-open-dialog]');
    if (opener) {
      var dialog = document.getElementById(opener.dataset.openDialog);
      if (dialog) dialog.showModal();
      return;
    }

    var closer = e.target.closest('[data-close-dialog]');
    if (closer) {
      var toClose = document.getElementById(closer.dataset.closeDialog);
      if (toClose) toClose.close();
      return;
    }

    // Clique no backdrop: o <dialog> inteiro (inclusive a área da
    // ::backdrop) recebe o clique quando não é em nenhum filho -- só o
    // próprio <dialog> como e.target indica clique fora do conteúdo.
    if (e.target.tagName === 'DIALOG' && (e.target.classList.contains('modal') || e.target.classList.contains('drawer'))) {
      e.target.close();
    }
  });
})();
