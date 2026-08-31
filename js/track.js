/* LuthuliScents — order tracking page.
   Sends the customer's waybill / tracking reference to the Vercel function
   `/api/tcg-track` (The Courier Guy tracking proxy — the Courier Guy key never leaves the
   server) and renders the events as a vertical timeline. */

(function () {
  'use strict';

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function note(html) {
    var el = document.getElementById('track-notice');
    if (el) el.innerHTML = html;
  }

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return escapeHtml(iso);
    var opts = { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' };
    return d.toLocaleString('en-ZA', opts);
  }

  function renderResult(result) {
    var box = document.getElementById('track-result');
    if (!box) return;
    box.hidden = false;

    var events = (result.events || []).slice().sort(function (a, b) {
      return new Date(a.date || 0) - new Date(b.date || 0);
    });

    var statusLine = '<div class="alert success"><p><strong>Status:</strong> ' +
      escapeHtml(result.status || 'unknown').toUpperCase() + '</p></div>';

    if (events.length === 0) {
      box.innerHTML = statusLine +
        '<div class="alert warning">Your parcel has been booked with the courier but there are no tracking updates yet.' +
        ' Check back soon — new scans appear as the parcel moves.</div>';
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    var rows = events.map(function (ev) {
      return '<div class="track-event">' +
        '<div class="track-dot"></div>' +
        '<div class="track-body">' +
        '<div class="track-status">' + escapeHtml(ev.status || 'Update') + '</div>' +
        '<div class="track-date">' + formatDate(ev.date) + '</div>' +
        (ev.location ? '<div class="track-location">' + escapeHtml(ev.location) + '</div>' : '') +
        (ev.message ? '<div class="track-msg">' + escapeHtml(ev.message) + '</div>' : '') +
        '</div></div>';
    }).join('');

    box.innerHTML = statusLine +
      '<h3 class="sec-head" style="margin:28px 0 18px;">Delivery timeline</h3>' +
      '<div class="track-timeline">' + rows + '</div>';

    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function handleSubmit(event) {
    event.preventDefault();
    var form = event.target;
    var ref = (form.elements.ref ? form.elements.ref.value : '').trim();
    if (!ref) {
      note('<div class="alert warning">Please enter your waybill or tracking reference.</div>');
      return;
    }

    var api = (window.LS_DATA && window.LS_DATA.tracking_api) || '';
    if (!api) {
      note('<div class="alert warning">Tracking isn\u2019t configured yet. The merchant still needs to add the Courier Guy tracking URL.</div>');
      return;
    }

    var btn = form.querySelector('button[type=submit]');
    if (btn) { btn.disabled = true; btn.textContent = 'Tracking\u2026'; }
    note('<div class="alert">Looking up ' + escapeHtml(ref) + '\u2026</div>');

    var url = api + (api.indexOf('?') >= 0 ? '&' : '?') + 'ref=' + encodeURIComponent(ref);

    fetch(url)
      .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (r) {
        if (r.ok && r.data.ok) {
          renderResult(r.data);
        } else {
          note('<div class="alert warning">' + escapeHtml((r.data && r.data.error) || 'No tracking found for that reference.') + '</div>');
        }
      })
      .catch(function (err) {
        note('<div class="alert warning">Could not reach the tracking service: ' + escapeHtml(err.message) + '</div>');
      })
      .then(function () {
        if (btn) { btn.disabled = false; btn.textContent = 'Track parcel'; }
      });
  }

  function boot() {
    var form = document.getElementById('track-form');
    if (form) form.addEventListener('submit', handleSubmit);
  }

  window.LS_READY.then(function () {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot);
    } else {
      boot();
    }
  });
})();