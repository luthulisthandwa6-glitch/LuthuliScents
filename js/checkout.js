/* LuthuliScents — checkout flow (cart page).
   Flat-rate shipping, order summary, Yoco payment link and a WhatsApp order
   handoff so orders are still captured for fulfilment on a static site.
   Mirrors the Streamlit checkout (views/cart.py) minus the server-side
   BobGo rate lookup, which cannot run on GitHub Pages. */

(function () {
  'use strict';

  var WHATSAPP_NUMBER = '27692380796';

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function readShipping() {
    var cfg = (window.LS_DATA && window.LS_DATA.shipping) || {};
    return {
      flat: Number(cfg.flat || 120),
      flatMetro: Number(cfg.flat_metro != null ? cfg.flat_metro : 85),
      metroPrefixes: cfg.metro_prefixes || ['2'],
      freeThreshold: Number(cfg.free_threshold != null ? cfg.free_threshold : cfg.free_shipping_threshold || 500)
    };
  }

  function shippingFee(cfg, postalCode, subtotal) {
    if (subtotal > cfg.freeThreshold) return 0; // free shipping over R500
    var isMetro = cfg.metroPrefixes.some(function (p) { return postalCode.indexOf(p) === 0; });
    return isMetro ? cfg.flatMetro : cfg.flat;
  }

  function renderEmpty() {
    var container = document.getElementById('cart-lines');
    if (container) container.innerHTML = '<p>Your cart is empty. Visit the <a href="products.html">Shop</a> page to add your signature scent.</p>';
    var checkout = document.getElementById('checkout');
    if (checkout) checkout.style.display = 'none';
  }

  function renderCart() {
    var container = document.getElementById('cart-lines');
    if (!container) return;

    var items = window.cartItems();
    if (items.length === 0) {
      renderEmpty();
      return;
    }

    container.innerHTML = items.map(function (item) {
      var p = item.product;
      return (
        '<div class="cart-line">' +
        '<img src="' + escapeHtml(p.image) + '" alt="' + escapeHtml(p.name) + '">' +
        '<div><div class="cart-name">' + escapeHtml(p.name) + '</div>' +
        '<div class="cart-meta">' + escapeHtml(p.family) + ' &middot; ' + escapeHtml(p.size) + '</div></div>' +
        '<div class="qty-wrap"><div class="qty-control">' +
        '<button class="btn" data-dec="' + escapeHtml(p.key) + '">\u2212</button>' +
        '<span>' + item.quantity + '</span>' +
        '<button class="btn" data-inc="' + escapeHtml(p.key) + '">+</button>' +
        '</div></div>' +
        '<div class="line-total cart-total">' + window.LS_MONEY(p.price * item.quantity) + '</div>' +
        '<button class="btn ghost" data-remove="' + escapeHtml(p.key) + '" title="Remove">Remove</button>' +
        '</div>'
      );
    }).join('');

    window.updateCartBadge();
  }

  function renderSummary() {
    var subtotal = window.cartSubtotal();
    var el = document.getElementById('cart-subtotal');
    if (el) el.textContent = window.LS_MONEY(subtotal);
  }

  function buildCheckoutResult(form) {
    var items = window.cartItems();
    var subtotal = window.cartSubtotal();
    var cfg = readShipping();
    var postalCode = form.elements.postal ? form.elements.postal.value.trim() : '';
    var shipping = shippingFee(cfg, postalCode, subtotal);
    var total = subtotal + shipping;

    var freeShipping = shipping === 0 && subtotal > cfg.freeThreshold;

    var absolute = function (page) {
      return new URL(page, window.location.href).href;
    };
    var email = (form.elements.email && form.elements.email.value.trim()) || '';

    var lines = items.map(function (i) {
      return '- ' + i.product.name + ' \u00d7 ' + i.quantity + ' \u2014 ' + window.LS_MONEY(i.product.price * i.quantity);
    }).join('\n');

    var waText =
      'Hi LuthuliScents! I\u2019d like to place an order.\n' +
      'Name: ' + (form.elements.name ? form.elements.name.value : '') + '\n' +
      'Email: ' + (form.elements.email ? form.elements.email.value : '') + '\n' +
      'Phone: ' + (form.elements.phone ? form.elements.phone.value : '') + '\n' +
      'Items:\n' + lines + '\n' +
      'Subtotal: ' + window.LS_MONEY(subtotal) + '\n' +
      'Shipping: ' + (freeShipping ? window.LS_MONEY(0) + ' (free \u2014 over R' + cfg.freeThreshold + ')' : window.LS_MONEY(shipping)) + '\n' +
      'Total to pay: ' + window.LS_MONEY(total) + '\n' +
      'Delivery: ' + (form.elements.address ? form.elements.address.value : '') +
      (form.elements.suburb ? ', ' + form.elements.suburb.value : '') +
      (form.elements.city ? ', ' + form.elements.city.value : '') +
      ', ' + postalCode;

    return {
      items: items,
      subtotal: subtotal,
      shipping: shipping,
      total: total,
      totalCents: Math.round(total * 100),
      email: email,
      freeShipping: freeShipping,
      threshold: cfg.freeThreshold,
      postalCode: postalCode,
      successUrl: absolute('success.html'),
      cancelUrl: absolute('cart.html'),
      whatsappUrl: 'https://wa.me/' + WHATSAPP_NUMBER + '?text=' + encodeURIComponent(waText)
    };
  }

  function startPayment(result) {
    var btn = document.getElementById('startPayBtn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = 'Starting payment\u2026';

    var api = window.LS_DATA.yoco_checkout_link || '';
    if (!api) {
      btn.disabled = false;
      btn.textContent = 'Pay ' + window.LS_MONEY(result.total) + ' through Yoco Checkout';
      note('Payment isn\u2019t configured yet. Please pay on delivery or use WhatsApp, then the merchant will add the Yoco Worker URL.');
      return;
    }

    fetch(api, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        total: result.totalCents,
        items: result.items.map(function (i) { return { name: i.product.name, quantity: i.quantity }; }),
        email: result.email,
        successUrl: result.successUrl,
        cancelUrl: result.cancelUrl
      })
    })
      .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (r) {
        if (r.ok && r.data.redirectUrl) {
          window.location.assign(r.data.redirectUrl);
        } else {
          btn.disabled = false;
          btn.textContent = 'Pay ' + window.LS_MONEY(result.total) + ' through Yoco Checkout';
          note('Could not start payment: ' + (r.data.error || 'unknown error'));
        }
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = 'Pay ' + window.LS_MONEY(result.total) + ' through Yoco Checkout';
        note('Could not start payment: ' + err.message);
      });
  }

  function note(html) {
    var notice = document.getElementById('checkout-notice');
    if (notice) notice.innerHTML = '<div class="alert warning">' + html + '</div>';
  }

  function showSummary(result) {
    var summary = document.getElementById('checkout-summary');
    if (!summary) return;

    var itemRows = result.items.map(function (i) {
      return '<div class="summary-row"><span>' + escapeHtml(i.product.name) + ' \u00d7 ' + i.quantity +
        '</span><span>' + window.LS_MONEY(i.product.price * i.quantity) + '</span></div>';
    }).join('');

    var freeNote = result.freeShipping
      ? ' <em>(free \u2014 over R' + result.threshold + ')</em>'
      : '';

    summary.innerHTML =
      '<div class="summary-box">' +
      '<h3>Order summary</h3>' +
      itemRows +
      '<div class="summary-row"><span>Subtotal</span><span>' + window.LS_MONEY(result.subtotal) + '</span></div>' +
      '<div class="summary-row"><span>Shipping</span><span>' + window.LS_MONEY(result.shipping) + freeNote + '</span></div>' +
      '<div class="summary-row total"><span>Total to pay</span><span>' + window.LS_MONEY(result.total) + '</span></div>' +
      '<div class="alert success" style="margin-top:18px;">' +
      '<p><strong>Complete your payment</strong></p>' +
      '<button id="startPayBtn" type="button" class="btn primary">Pay ' + window.LS_MONEY(result.total) + ' through Yoco Checkout</button>' +
      '<p class="caption" style="margin-top:10px;">After payment, send your order via WhatsApp below and we will prepare it for shipping.</p>' +
      '<a class="btn" href="' + escapeHtml(result.whatsappUrl) + '" target="_blank" rel="noopener">Send order via WhatsApp</a>' +
      '</div>' +
      '</div>';

    var payBtn = document.getElementById('startPayBtn');
    if (payBtn) payBtn.addEventListener('click', function (e) { e.preventDefault(); startPayment(result); });

    summary.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function handleSubmit(event) {
    event.preventDefault();
    var form = event.target;
    var postal = form.elements.postal ? form.elements.postal.value.trim() : '';
    if (!postal) {
      var notice = document.getElementById('checkout-notice');
      if (notice) {
        notice.innerHTML = '<div class="alert warning">Please enter your postal code to calculate shipping.</div>';
      }
      return;
    }
    var result = buildCheckoutResult(form);
    showSummary(result);
  }

  var QUOTE_API = (window.LS_DATA && window.LS_DATA.quote_checkout_api) || '';
  var QUOTE_BUSY = false;

  function quoteMessage(html) {
    var el = document.getElementById('quote-result');
    if (el) el.innerHTML = html;
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; });
    }
    var ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return Promise.resolve(ok);
  }

  function generateQuoteLink(form) {
    var btn = document.getElementById('quote-pay-btn');
    if (!btn || QUOTE_BUSY) return;
    if (!QUOTE_API) {
      quoteMessage('<div class="alert warning">Live shipping isn\u2019t configured yet. Add a quote API URL to data/products.json.</div>');
      return;
    }
    var items = window.cartItems().map(function (i) { return { key: i.product.key, quantity: i.quantity }; });
    if (items.length === 0) {
      quoteMessage('<div class="alert warning">Your cart is empty.</div>');
      return;
    }
    var val = function (nm) { return (form.elements[nm] ? form.elements[nm].value.trim() : ''); };
    var postal = val('postal');
    var phone = val('phone');
    var email = val('email');
    if (!postal) { quoteMessage('<div class="alert warning">Please enter the delivery postal code above.</div>'); return; }
    if (!phone && !email) { quoteMessage('<div class="alert warning">Please enter the buyer\u2019s phone or email so Bob Go can quote.</div>'); return; }

    var body = {
      items: items,
      delivery: {
        name: val('name'),
        phone: phone,
        email: email,
        address: val('address'),
        city: val('city'),
        postal: postal
      },
      successUrl: new URL('success.html', window.location.href).href,
      cancelUrl: new URL('cart.html', window.location.href).href
    };

    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Getting live courier price\u2026';
    QUOTE_BUSY = true;
    quoteMessage('<div class="alert info">Quoting with Bob Go \u2014 this can take a few seconds\u2026</div>');

    fetch(QUOTE_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, data: d }; }); })
      .then(function (r) {
        if (r.ok && r.data.paymentLink) {
          return copyText(r.data.paymentLink).then(function () {
            return { copied: true, data: r.data };
          });
        }
        throw new Error(r.data.error || 'Could not generate payment link');
      })
      .then(function (res) {
        var d = res.data;
        quoteMessage(
          '<div class="alert success">' +
          '<p><strong>Payment link ready</strong> \u2014 it is copied to your clipboard.</p>' +
          '<p>Subtotal: ' + window.LS_MONEY(d.subtotalCents / 100) +
          ' &middot; Shipping (' + (d.shipping.provider + ' \u00b7 ' + d.shipping.service) + '): ' +
          window.LS_MONEY(d.shippingCents / 100) +
          ' &middot; <strong>Total: ' + window.LS_MONEY(d.totalCents / 100) + '</strong></p>' +
          '<p><a class="btn" target="_blank" rel="noopener" href="' + d.paymentLink + '">Open payment link</a></p>' +
          '<p class="caption">Paste the copied link into WhatsApp to send the buyer the payment page.</p>' +
          '</div>'
        );
      })
      .catch(function (err) {
        quoteMessage('<div class="alert warning">' + escapeHtml(err.message) + '</div>');
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = old;
        QUOTE_BUSY = false;
      });
  }

  function boot() {
    window.onCartChange = function () {
      renderCart();
      renderSummary();
      var summary = document.getElementById('checkout-summary');
      if (summary) summary.innerHTML = '';
    };

    document.addEventListener('click', function (event) {
      var t = event.target;
      var inc = t.closest('[data-inc]');
      var dec = t.closest('[data-dec]');
      var rem = t.closest('[data-remove]');
      if (inc) { window.incrementCart(inc.getAttribute('data-inc')); event.preventDefault(); }
      else if (dec) { window.decrementCart(dec.getAttribute('data-dec')); event.preventDefault(); }
      else if (rem) { window.removeFromCart(rem.getAttribute('data-remove')); event.preventDefault(); }
    });

    var form = document.getElementById('checkout-form');
    if (form) form.addEventListener('submit', handleSubmit);

    var quoteBtn = document.getElementById('quote-pay-btn');
    if (quoteBtn) quoteBtn.addEventListener('click', function () { generateQuoteLink(document.getElementById('checkout-form')); });

    var clearBtn = document.getElementById('clear-cart');
    if (clearBtn) clearBtn.addEventListener('click', function () { window.clearCart(); });

    renderCart();
    renderSummary();
  }

  window.LS_READY.then(function () {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot);
    } else {
      boot();
    }
  });
})();