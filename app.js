document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form").forEach(form => {
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"], button:not([type])');
      if (button && !form.hasAttribute("onsubmit")) {
        button.dataset.originalText = button.textContent;
        button.textContent = "Saving…";
      }
    });
  });
});

document.addEventListener("DOMContentLoaded", () => {
  const feeInputs = Array.from(document.querySelectorAll(".service-fee-input"));
  const currencySelect = document.querySelector('select[name="currency"]');
  const amountField = document.getElementById("proposal-amount");

  const currencySymbols = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };
  const formatMoney = (value, currency) => {
    const symbol = currencySymbols[currency] || currency + " ";
    return symbol + Number(value || 0).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  };

  function updateServiceTotals() {
    if (!feeInputs.length) return;
    const subtotal = feeInputs.reduce((sum, input) => sum + Math.max(0, Number(input.value) || 0), 0);
    const igst = subtotal * 0.18;
    const currency = currencySelect ? currencySelect.value : "INR";
    const subtotalEl = document.getElementById("service-subtotal");
    const igstEl = document.getElementById("service-igst");
    const totalEl = document.getElementById("service-grand-total");
    if (subtotalEl) subtotalEl.textContent = formatMoney(subtotal, currency);
    if (igstEl) igstEl.textContent = formatMoney(igst, currency);
    if (totalEl) totalEl.textContent = formatMoney(subtotal + igst, currency);
    if (amountField) amountField.value = subtotal.toFixed(2);
  }

  feeInputs.forEach(input => input.addEventListener("input", updateServiceTotals));
  if (currencySelect) currencySelect.addEventListener("change", updateServiceTotals);
  updateServiceTotals();

  const serviceSelect = document.getElementById("individual-service-select");
  if (serviceSelect) {
    const currency = serviceSelect.dataset.currency || "INR";
    const currencySymbol = currencySymbols[currency] || currency + " ";
    const formatSelected = value => currencySymbol + Number(value || 0).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
    function updateSelectedService() {
      const option = serviceSelect.options[serviceSelect.selectedIndex];
      const fee = Number(option ? option.dataset.fee : 0);
      const igst = fee * 0.18;
      document.getElementById("individual-fee").textContent = formatSelected(fee);
      document.getElementById("individual-igst").textContent = formatSelected(igst);
      document.getElementById("individual-total").textContent = formatSelected(fee + igst);
    }
    serviceSelect.addEventListener("change", updateSelectedService);
    updateSelectedService();
  }
});
