/* Lead capture form redesign (Prompt Master 4, 2026-08-08). One real
 * <form> (app/templates/_lead_intake_form.html) submitted exactly like
 * before -- this script only toggles which of the 3 `.lead-intake-step`
 * sections are visible, keeps the "selected services" summary panel in
 * sync, and does light pre-submit validation. No new route, no session
 * state: server-side validation in app/lead_intake.py::start() is still
 * the source of truth. If this script fails to load, the <noscript>
 * fallback in the template shows every step at once and the form still
 * works (see that file).
 */
(function () {
  var root = document.getElementById('lead-intake');
  if (!root) return;

  var form = document.getElementById('lead-intake-form-el');
  var steps = Array.prototype.slice.call(root.querySelectorAll('.lead-intake-step'));
  var dots = Array.prototype.slice.call(root.querySelectorAll('.lead-intake-progress-step'));

  function goToStep(n) {
    steps.forEach(function (el) {
      var isTarget = Number(el.dataset.step) === n;
      el.hidden = !isTarget;
    });
    dots.forEach(function (dot) {
      var stepNum = Number(dot.dataset.stepDot);
      dot.classList.toggle('is-active', stepNum === n);
      dot.classList.toggle('is-done', stepNum < n);
    });
    if (n === 3) fillReview();
    var target = root.querySelector('.lead-intake-step[data-step="' + n + '"]');
    if (target) {
      var focusable = target.querySelector('input, select, textarea, button');
      if (focusable) focusable.focus({ preventScroll: true });
    }
    root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ---- Step 1: service selection + "not sure" textarea + summary ----
  var checkboxes = Array.prototype.slice.call(root.querySelectorAll('.lead-intake-service-checkbox'));
  var summaryList = document.getElementById('lead-intake-summary-list');
  var summaryEmpty = document.getElementById('lead-intake-summary-empty');
  var summaryCount = document.getElementById('lead-intake-summary-count');
  var servicesError = document.getElementById('lead-intake-services-error');
  var notSureCheckbox = document.getElementById('lead-intake-not-sure-checkbox');
  var notSureNotes = document.getElementById('lead-intake-not-sure-notes');

  function checkedBoxes() {
    return checkboxes.filter(function (cb) { return cb.checked; });
  }

  function renderSummary() {
    var checked = checkedBoxes();
    summaryList.innerHTML = '';
    checked.forEach(function (cb) {
      var label = cb.closest('.lead-intake-service-card').querySelector('.lead-intake-service-name').textContent;
      var li = document.createElement('li');
      var span = document.createElement('span');
      span.textContent = label;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'lead-intake-summary-remove';
      btn.setAttribute('aria-label', summaryCount.dataset.removeLabel || 'Remove');
      btn.textContent = '×';
      btn.addEventListener('click', function () {
        cb.checked = false;
        onCheckboxChange(cb);
      });
      li.appendChild(span);
      li.appendChild(btn);
      summaryList.appendChild(li);
    });
    summaryEmpty.hidden = checked.length > 0;
    if (checked.length > 0) {
      summaryCount.hidden = false;
      summaryCount.textContent = summaryCount.dataset.template.replace('__COUNT__', String(checked.length));
    } else {
      summaryCount.hidden = true;
    }
    if (checked.length > 0) servicesError.hidden = true;
  }

  function onCheckboxChange(cb) {
    var card = cb.closest('.lead-intake-service-card');
    if (card) card.classList.toggle('selected', cb.checked);
    renderSummary();
  }

  checkboxes.forEach(function (cb) {
    cb.addEventListener('change', function () { onCheckboxChange(cb); });
  });

  if (notSureCheckbox && notSureNotes) {
    notSureCheckbox.addEventListener('change', function () {
      notSureNotes.hidden = !notSureCheckbox.checked;
    });
  }

  renderSummary();

  // Mobile: tap the summary panel's heading to expand/collapse the sticky bar.
  var summaryPanel = document.getElementById('lead-intake-summary');
  var summaryHeading = summaryPanel ? summaryPanel.querySelector('h3') : null;
  if (summaryHeading) {
    summaryHeading.addEventListener('click', function () {
      summaryPanel.classList.toggle('is-expanded');
    });
  }

  // ---- Step 2: contact fields ----
  var fullNameInput = document.getElementById('lead-intake-full-name');
  var emailInput = document.getElementById('lead-intake-email');
  var phoneInput = document.getElementById('lead-intake-phone');
  var contactTimeSelect = document.getElementById('lead-intake-contact-time');
  var contactTimeOther = document.getElementById('lead-intake-contact-time-other');
  var contactTimeValue = document.getElementById('lead-intake-contact-time-value');

  function syncContactTimeValue() {
    if (contactTimeSelect.value === '__other__') {
      contactTimeOther.hidden = false;
      contactTimeValue.value = contactTimeOther.value;
    } else {
      contactTimeOther.hidden = true;
      contactTimeValue.value = contactTimeSelect.value;
    }
  }
  if (contactTimeSelect) {
    contactTimeSelect.addEventListener('change', syncContactTimeValue);
    contactTimeOther.addEventListener('input', syncContactTimeValue);
  }

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function showFieldError(name, show) {
    var msg = root.querySelector('.lead-intake-validation-msg[data-error-for="' + name + '"]');
    if (msg) msg.hidden = !show;
  }

  function validateStep2() {
    var ok = true;
    var nameOk = fullNameInput.value.trim().length > 0;
    showFieldError('full_name', !nameOk);
    if (!nameOk) { ok = false; }

    var emailOk = EMAIL_RE.test(emailInput.value.trim());
    showFieldError('email', !emailOk);
    if (!emailOk && ok) fullNameInput.blur();
    if (!emailOk) ok = false;

    var phoneOk = phoneInput.value.trim().length >= 7;
    showFieldError('phone', !phoneOk);
    if (!phoneOk) ok = false;

    if (!ok) {
      var firstInvalid = !nameOk ? fullNameInput : (!emailOk ? emailInput : phoneInput);
      firstInvalid.focus();
    }
    return ok;
  }

  // ---- Step navigation buttons ----
  root.querySelectorAll('[data-step-next]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var current = btn.closest('.lead-intake-step');
      var currentNum = Number(current.dataset.step);
      if (currentNum === 1) {
        if (checkedBoxes().length === 0) {
          servicesError.hidden = false;
          servicesError.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
      }
      if (currentNum === 2 && !validateStep2()) return;
      goToStep(Number(btn.dataset.stepNext));
    });
  });
  root.querySelectorAll('[data-step-prev]').forEach(function (btn) {
    btn.addEventListener('click', function () { goToStep(Number(btn.dataset.stepPrev)); });
  });

  // ---- Step 3: review ----
  function fillReview() {
    var reviewServices = document.getElementById('lead-intake-review-services');
    reviewServices.innerHTML = '';
    checkedBoxes().forEach(function (cb) {
      var label = cb.closest('.lead-intake-service-card').querySelector('.lead-intake-service-name').textContent;
      var li = document.createElement('li');
      li.textContent = '✓ ' + label;
      reviewServices.appendChild(li);
    });
    document.getElementById('lead-intake-review-name').textContent = fullNameInput.value.trim() || '—';
    document.getElementById('lead-intake-review-email').textContent = emailInput.value.trim() || '—';
    document.getElementById('lead-intake-review-phone').textContent = phoneInput.value.trim() ? ('+1 ' + phoneInput.value.trim()) : '—';
    document.getElementById('lead-intake-review-contact-time').textContent = contactTimeValue.value || '—';
  }

  // ---- Submit: prevent double-click, let the real POST happen ----
  var submitBtn = document.getElementById('lead-intake-submit-btn');
  form.addEventListener('submit', function () {
    if (submitBtn.disabled) return;
    submitBtn.disabled = true;
    submitBtn.textContent = submitBtn.dataset.submittingText || submitBtn.textContent;
  });
})();
