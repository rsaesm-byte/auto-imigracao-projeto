/* Garante que TODA data no sistema apareça em formato americano
 * (mm/dd/yyyy), pedido explícito do usuário -- 2026-08-07.
 *
 * `<input type="date">` nativo do Chrome exibe o seletor (e o popup de
 * calendário) no idioma do NAVEGADOR (Accept-Language do SO), não no
 * `lang` do elemento nem no idioma da página escolhido no site --
 * testado ao vivo com `lang="en-US"` no próprio input: não muda nada, o
 * Chrome ignora esse atributo pra este widget. O valor submetido
 * continua ISO/correto sempre; só o texto exibido segue o navegador.
 * Como não dá pra forçar o formato do widget nativo (nem o popup, que é
 * renderizado pelo SO, fora do DOM -- nenhum z-index consegue ficar por
 * cima dele), este script adiciona um rótulo mm/dd/yyyy sempre visível
 * -- posicionado à DIREITA do campo (`position:absolute`, fora do fluxo
 * normal) porque o popup do calendário sempre abre ABAIXO do campo; um
 * rótulo abaixo ficaria escondido atrás do popup bem na hora em que
 * alguém for conferir a data (bug real encontrado 2026-08-07: o rótulo
 * já existia e já mostrava o valor certo, só que embaixo do campo,
 * exatamente onde o calendário nativo cobre ele quando aberto).
 * `position:absolute` também evita qualquer efeito colateral de layout
 * -- o rótulo não ocupa espaço no fluxo, então não empurra nada nem
 * quebra grids/flexbox existentes.
 */
(function () {
  function formatIso(iso) {
    var parts = iso.split('-');
    if (parts.length !== 3) return '';
    return parts[1] + '/' + parts[2] + '/' + parts[0];
  }

  function attachLabel(input) {
    if (input.dataset.dateLabelAttached) return;
    input.dataset.dateLabelAttached = '1';

    // Envolve o input num wrapper só pra dar uma âncora de posicionamento
    // ao rótulo -- copia a largura explícita do input (quando houver,
    // ex. `style="width:100%"` dentro de um grid) pro wrapper, senão o
    // wrapper (inline-block) encolheria pro tamanho do conteúdo e
    // quebraria layouts que dependiam do input preencher a célula.
    var wrapper = document.createElement('span');
    wrapper.style.position = 'relative';
    wrapper.style.display = 'inline-block';
    wrapper.style.verticalAlign = 'middle';
    if (input.style.width) wrapper.style.width = input.style.width;
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    // Acima do campo, encostado na borda direita: nunca colide com o
    // popup do calendário (sempre abaixo) nem com um <label> comum
    // ("Date of birth" etc., alinhado à esquerda -- ancorado à direita
    // aqui evita a maioria das colisões) nem com o próximo campo do
    // formulário (não fica na mesma linha à direita).
    var label = document.createElement('span');
    label.className = 'muted date-format-label';
    label.style.cssText = 'position:absolute;bottom:100%;right:0;margin-bottom:2px;' +
      'font-size:0.68rem;white-space:nowrap;pointer-events:none;z-index:1;';
    wrapper.appendChild(label);

    function sync() {
      label.textContent = input.value ? formatIso(input.value) : '';
    }
    sync();
    input.addEventListener('input', sync);
    input.addEventListener('change', sync);
  }

  function scan() {
    document.querySelectorAll('input[type="date"]').forEach(attachLabel);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scan);
  } else {
    scan();
  }
})();
